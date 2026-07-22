from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

SIDECAR_MAIN = Path(__file__).parents[2] / "services" / "hermes-sidecar" / "main.py"
SIDECAR_DOCKERFILE = SIDECAR_MAIN.with_name("Dockerfile")
SIDECAR_REQUIREMENTS = SIDECAR_MAIN.with_name("requirements.txt")
_SIDECAR_ENV = (
    "SIDECAR_AUTH_TOKEN",
    "SIDECAR_ALLOW_UNAUTHENTICATED_RUN",
    "HERMES_CMD",
    "HERMES_HOME_ROOT",
    "HERMES_MODEL",
    "HERMES_PROVIDER",
    "HERMES_BASE_URL",
    "HERMES_MAX_TOKENS",
    "HERMES_TOOLSETS",
    "HERMES_RUN_TIMEOUT",
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
)


def _load_sidecar(monkeypatch, **env):
    for key in _SIDECAR_ENV:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    name = f"hermes_sidecar_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, SIDECAR_MAIN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def test_sidecar_refuses_to_start_without_auth(monkeypatch) -> None:
    with pytest.raises(RuntimeError, match="SIDECAR_AUTH_TOKEN is required"):
        _load_sidecar(monkeypatch, SIDECAR_ALLOW_UNAUTHENTICATED_RUN="1")


def test_sidecar_build_pins_and_verifies_hermes_installer() -> None:
    dockerfile = SIDECAR_DOCKERFILE.read_text()

    assert "hermes-agent.nousresearch.com/install.sh | bash" not in dockerfile
    assert "HERMES_INSTALL_COMMIT=3ef6bbd201263d354fd83ec55b3c306ded2eb72a" in dockerfile
    assert (
        "HERMES_INSTALLER_SHA256="
        "c5ba7e89627577fab914514736ecfb3359b66956ca00199bfef616ca35953cb9" in dockerfile
    )
    assert "sha256sum -c -" in dockerfile
    assert '--commit "${HERMES_INSTALL_COMMIT}"' in dockerfile
    assert "git -C /usr/local/lib/hermes-agent rev-parse HEAD" in dockerfile
    assert 'ENV PATH="/root/.local/bin:${PATH}"' not in dockerfile
    assert "COPY --chown=osai:osai main.py /app/main.py" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert "pip install --no-cache-dir --require-hashes" in dockerfile

    requirements = SIDECAR_REQUIREMENTS.read_text()
    assert "fastapi==0.139.0" in requirements
    assert "uvicorn==0.49.0" in requirements
    assert requirements.count("--hash=sha256:") > 10


def test_sidecar_auth_and_path_validation_happen_before_execution(monkeypatch, tmp_path) -> None:
    module = _load_sidecar(
        monkeypatch,
        SIDECAR_AUTH_TOKEN="shared-secret",
        HERMES_HOME_ROOT=str(tmp_path),
        HERMES_MODEL="llama-test",
        HERMES_PROVIDER="groq",
        GROQ_API_KEY="fake-provider-key",
    )
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("Hermes must not execute for a rejected request"),
    )
    client = TestClient(module.app)

    assert client.post("/run", json={"prompt": "x", "org_id": "org-a"}).status_code == 401
    assert (
        client.post(
            "/run",
            json={"prompt": "x", "org_id": "../escape"},
            headers={"X-Sidecar-Token": "shared-secret"},
        ).status_code
        == 400
    )


def test_sidecar_runs_in_namespaced_home_with_env_driven_config(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("UNRELATED_PLATFORM_SECRET", "must-not-reach-hermes")
    module = _load_sidecar(
        monkeypatch,
        SIDECAR_AUTH_TOKEN="shared-secret",
        HERMES_HOME_ROOT=str(tmp_path),
        HERMES_CMD="hermes-test",
        HERMES_MODEL="llama-test",
        HERMES_PROVIDER="groq",
        HERMES_BASE_URL="https://api.groq.test/v1",
        HERMES_MAX_TOKENS="512",
        HERMES_TOOLSETS="search",
        GROQ_API_KEY="fake-provider-key",
        OPENAI_API_KEY="unused-provider-key",
    )
    calls = []

    def _run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return SimpleNamespace(returncode=0, stdout="answer\n", stderr="")

    monkeypatch.setattr(module.subprocess, "run", _run)
    response = TestClient(module.app).post(
        "/run",
        json={"prompt": "Summarize", "org_id": "org-a", "user_id": "user-1"},
        headers={"X-Sidecar-Token": "shared-secret"},
    )

    assert response.status_code == 200
    assert response.json() == {"result": "answer"}
    cmd, kwargs = calls[0]
    assert cmd == ["hermes-test", "-z", "Summarize", "-t", "search"]
    home = Path(kwargs["env"]["HERMES_HOME"])
    assert home == tmp_path / "org-a" / "user-1"
    expected_env = {
        key: os.environ[key] for key in module.CHILD_ENV_ALLOWLIST if os.environ.get(key)
    }
    expected_env.update(
        {
            "HOME": str(home),
            "HERMES_HOME": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "TMPDIR": str(home / "tmp"),
            "GROQ_API_KEY": "fake-provider-key",
        }
    )
    assert kwargs["env"] == expected_env
    assert "SIDECAR_AUTH_TOKEN" not in kwargs["env"]
    assert "OPENAI_API_KEY" not in kwargs["env"]
    assert "UNRELATED_PLATFORM_SECRET" not in kwargs["env"]
    assert home.joinpath(".env").read_text() == "GROQ_API_KEY=fake-provider-key\n"
    assert "key_env: GROQ_API_KEY" in home.joinpath("config.yaml").read_text()
    assert "max_tokens: 512" in home.joinpath("config.yaml").read_text()
    if os.name != "nt":
        assert stat.S_IMODE(home.stat().st_mode) & 0o077 == 0
        assert stat.S_IMODE(home.joinpath(".env").stat().st_mode) & 0o077 == 0
        assert stat.S_IMODE(home.joinpath("config.yaml").stat().st_mode) & 0o077 == 0

    monkeypatch.setenv("GROQ_API_KEY", "rotated-provider-key")
    module._ensure_home("org-a", "user-1")
    assert home.joinpath(".env").read_text() == "GROQ_API_KEY=rotated-provider-key\n"


def test_sidecar_health_distinguishes_liveness_from_readiness(monkeypatch, tmp_path) -> None:
    module = _load_sidecar(
        monkeypatch,
        SIDECAR_AUTH_TOKEN="shared-secret",
        HERMES_HOME_ROOT=str(tmp_path),
        HERMES_MODEL="llama-test",
        HERMES_PROVIDER="groq",
        GROQ_API_KEY="fake-provider-key",
    )
    client = TestClient(module.app)

    monkeypatch.setattr(module.shutil, "which", lambda _command: None)
    assert client.get("/health").json() == {"ok": True}
    unavailable = client.get("/health/ready")
    assert unavailable.status_code == 503
    assert unavailable.json() == {"ok": False}

    monkeypatch.setattr(module.shutil, "which", lambda _command: os.devnull)
    available = client.get("/health/ready")
    assert available.status_code == 200
    assert available.json() == {"ok": True}

    monkeypatch.setattr(module, "_storage_ready", lambda: False)
    unavailable_storage = client.get("/health/ready")
    assert unavailable_storage.status_code == 503
    assert unavailable_storage.json() == {"ok": False}


@pytest.mark.parametrize(
    "provider,credential",
    [("unsupported", "value"), ("groq", None)],
)
def test_sidecar_readiness_requires_supported_provider_credential(
    monkeypatch, tmp_path, provider, credential
) -> None:
    env = {
        "SIDECAR_AUTH_TOKEN": "shared-secret",
        "HERMES_HOME_ROOT": str(tmp_path),
        "HERMES_MODEL": "llama-test",
        "HERMES_PROVIDER": provider,
    }
    if credential is not None:
        env["GROQ_API_KEY"] = credential
    module = _load_sidecar(monkeypatch, **env)
    monkeypatch.setattr(module.shutil, "which", lambda _command: os.devnull)

    response = TestClient(module.app).get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"ok": False}


def _configured_sidecar(monkeypatch, tmp_path):
    return _load_sidecar(
        monkeypatch,
        SIDECAR_AUTH_TOKEN="shared-secret",
        HERMES_HOME_ROOT=str(tmp_path),
        HERMES_CMD="hermes-test",
        HERMES_MODEL="llama-test",
        HERMES_PROVIDER="groq",
        GROQ_API_KEY="fake-provider-key",
    )


def test_sidecar_rejects_symlinked_home_component(monkeypatch, tmp_path) -> None:
    module = _configured_sidecar(monkeypatch, tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (tmp_path / "org-a").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable on this platform: {exc}")

    with pytest.raises(module.UnsafeHomeError, match="symlink"):
        module._ensure_home("org-a", "user-1")


def test_sidecar_rejects_symlinked_generated_file(monkeypatch, tmp_path) -> None:
    module = _configured_sidecar(monkeypatch, tmp_path)
    home = Path(module._ensure_home("org-a", "user-1"))
    victim = tmp_path / "victim"
    victim.write_text("do-not-touch", encoding="utf-8")
    home.joinpath(".env").unlink()
    try:
        home.joinpath(".env").symlink_to(victim)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable on this platform: {exc}")

    with pytest.raises(module.UnsafeHomeError, match="symlink"):
        module._ensure_home("org-a", "user-1")
    assert victim.read_text(encoding="utf-8") == "do-not-touch"


def test_same_home_runs_are_serialized_by_bounded_striped_lock(monkeypatch, tmp_path) -> None:
    module = _configured_sidecar(monkeypatch, tmp_path)
    active = 0
    maximum_active = 0
    state_lock = threading.Lock()
    rendezvous = threading.Barrier(2)

    def _run(*_args, **_kwargs):
        nonlocal active, maximum_active
        with state_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        try:
            try:
                rendezvous.wait(timeout=0.2)
            except threading.BrokenBarrierError:
                pass
            return SimpleNamespace(returncode=0, stdout="answer\n", stderr="")
        finally:
            with state_lock:
                active -= 1

    monkeypatch.setattr(module.subprocess, "run", _run)
    request = module.RunRequest(prompt="x", org_id="org-a", user_id="user-1")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            pool.submit(module.run, request, "shared-secret"),
            pool.submit(module.run, request, "shared-secret"),
        ]
        assert [future.result(timeout=2) for future in results] == [
            {"result": "answer"},
            {"result": "answer"},
        ]

    assert maximum_active == 1
    assert len(module._RUN_LOCK_STRIPES) == 64


def test_different_lock_stripes_can_run_concurrently(monkeypatch, tmp_path) -> None:
    module = _configured_sidecar(monkeypatch, tmp_path)
    users_by_stripe: dict[int, str] = {}
    for suffix in range(256):
        user = f"user-{suffix}"
        home = str(tmp_path / "org-a" / user)
        users_by_stripe.setdefault(module._run_lock_index(home), user)
        if len(users_by_stripe) == 2:
            break
    users = list(users_by_stripe.values())
    assert len(users) == 2

    active = 0
    maximum_active = 0
    state_lock = threading.Lock()
    rendezvous = threading.Barrier(2)

    def _run(*_args, **_kwargs):
        nonlocal active, maximum_active
        with state_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        try:
            rendezvous.wait(timeout=1)
            return SimpleNamespace(returncode=0, stdout="answer\n", stderr="")
        finally:
            with state_lock:
                active -= 1

    monkeypatch.setattr(module.subprocess, "run", _run)
    requests = [module.RunRequest(prompt="x", org_id="org-a", user_id=user) for user in users]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(module.run, request, "shared-secret") for request in requests]
        assert [future.result(timeout=2) for future in results] == [
            {"result": "answer"},
            {"result": "answer"},
        ]

    assert maximum_active == 2


@pytest.mark.parametrize(
    "failure,expected",
    [
        (FileNotFoundError(), "hermes CLI not installed in this sidecar"),
        (subprocess.TimeoutExpired(cmd="hermes", timeout=1), "hermes run timed out"),
    ],
)
def test_sidecar_returns_stable_errors_for_cli_failures(monkeypatch, tmp_path, failure, expected):
    module = _load_sidecar(
        monkeypatch,
        SIDECAR_AUTH_TOKEN="shared-secret",
        HERMES_HOME_ROOT=str(tmp_path),
        HERMES_MODEL="llama-test",
        HERMES_PROVIDER="groq",
        GROQ_API_KEY="fake-provider-key",
    )

    def _fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(module.subprocess, "run", _fail)
    response = TestClient(module.app).post(
        "/run",
        json={"prompt": "x", "org_id": "org-a"},
        headers={"X-Sidecar-Token": "shared-secret"},
    )
    assert response.status_code == 200
    assert response.json() == {"result": None, "error": expected}


def test_sidecar_does_not_return_cli_stderr(monkeypatch, tmp_path) -> None:
    module = _load_sidecar(
        monkeypatch,
        SIDECAR_AUTH_TOKEN="shared-secret",
        HERMES_HOME_ROOT=str(tmp_path),
        HERMES_MODEL="llama-test",
        HERMES_PROVIDER="groq",
        GROQ_API_KEY="fake-provider-key",
    )
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="OPENAI_API_KEY=must-not-leak",
        ),
    )
    response = TestClient(module.app).post(
        "/run",
        json={"prompt": "x", "org_id": "org-a"},
        headers={"X-Sidecar-Token": "shared-secret"},
    )
    assert response.status_code == 200
    assert response.json() == {"result": None, "error": "hermes run failed"}
    assert "must-not-leak" not in response.text
