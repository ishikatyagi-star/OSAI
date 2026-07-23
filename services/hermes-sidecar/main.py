"""Experimental OSAI ↔ Hermes-agent sidecar.

Hermes Agent (github.com/NousResearch/hermes-agent) is a single-operator agent.
This local/trusted-monolith spike gives each request a namespaced HERMES_HOME,
but every home and subprocess still uses the same OS identity. It is not a
multi-tenant security boundary and must not be exposed as a hosted shared
service. OSAI remains responsible for permissions and injected context.

Run:  uvicorn main:app --host 0.0.0.0 --port 8088
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading

from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field

app = FastAPI(title="OSAI Hermes Sidecar")
logger = logging.getLogger(__name__)

# Shared secret with the OSAI API. Even local/trusted deployments must require
# it: an environment typo must never turn /run into an unauthenticated command
# and provider-quota endpoint.
AUTH_TOKEN = os.environ.get("SIDECAR_AUTH_TOKEN")
if not AUTH_TOKEN:
    raise RuntimeError("SIDECAR_AUTH_TOKEN is required")

# org_id/user_id become filesystem path segments — restrict them so a crafted
# id can't escape HERMES_HOME_ROOT (path traversal).
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")

HERMES_CMD = os.environ.get("HERMES_CMD", "hermes")
HERMES_HOME_ROOT = os.environ.get("HERMES_HOME_ROOT", "/data/hermes")
HERMES_MODEL = os.environ.get("HERMES_MODEL")  # e.g. "llama-3.3-70b-versatile"
HERMES_PROVIDER = os.environ.get("HERMES_PROVIDER")  # e.g. "openrouter", "groq"
# For providers not in hermes' built-in registry (e.g. Groq): any
# OpenAI-compatible endpoint, registered per-user as a custom provider.
HERMES_BASE_URL = os.environ.get("HERMES_BASE_URL")  # e.g. https://api.groq.com/openai/v1
# Cap completion tokens — providers like Groq reject hermes' default as too high.
HERMES_MAX_TOKENS = os.environ.get("HERMES_MAX_TOKENS")
# Keep the tool schema small: full hermes toolsets overflow strict request-size
# limits (Groq returns 413). OSAI injects context and owns actions, so the
# sidecar only needs a minimal set. Comma-separated hermes toolset names.
HERMES_TOOLSETS = os.environ.get("HERMES_TOOLSETS", "search")
# Known provider credentials. Only the key selected by HERMES_PROVIDER is ever
# written to a home or passed to a child process.
PROVIDER_ENV_KEYS = (
    "OPENROUTER_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GROQ_API_KEY",
    "GOOGLE_API_KEY",
)
# Which env key each HERMES_PROVIDER value's credentials live in — used to seed
# the per-user config.yaml's custom_providers.key_env. Must match HERMES_PROVIDER,
# not just "whichever key happens to be set" (a dev with both GROQ_API_KEY and
# OPENAI_API_KEY in their env would otherwise get the wrong one wired up).
PROVIDER_KEY_ENV = {
    "openrouter": "OPENROUTER_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "gemini": "GOOGLE_API_KEY",
}
RUN_TIMEOUT = int(os.environ.get("HERMES_RUN_TIMEOUT", "180"))

# Deliberately small, non-secret process environment. The provider credential
# selected below is added separately. In particular, SIDECAR_AUTH_TOKEN,
# unrelated provider keys, and platform application secrets are not inherited.
CHILD_ENV_ALLOWLIST = (
    "PATH",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "TZ",
    # Required by parts of Python's process-launch implementation on Windows;
    # harmless and absent in the Linux container.
    "SYSTEMROOT",
    "WINDIR",
)


class RunRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=100_000)
    org_id: str
    user_id: str | None = None
    permissions: list[str] = Field(default_factory=list)


_HOME_CONFIG_LOCK = threading.Lock()
_RUN_LOCK_STRIPES = tuple(threading.Lock() for _ in range(64))


class UnsafeHomeError(RuntimeError):
    """The configured Hermes storage path contains an unsafe filesystem object."""


def _safe_segment(value: str) -> str:
    if value in {".", ".."} or not _SAFE_SEGMENT.match(value):
        raise HTTPException(status_code=400, detail="invalid org_id/user_id")
    return value


def _assert_no_symlink_components(path: str) -> None:
    """Reject existing symlinks in an absolute path, including ancestors.

    This narrows accidental traversal and common symlink attacks. It cannot
    make same-UID processes mutually untrusted: another such process can still
    race path operations. Production tenant isolation needs an OS/container or
    mount boundary, not path checks.
    """
    absolute = os.path.abspath(path)
    current = absolute
    components: list[str] = []
    while True:
        components.append(current)
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    for component in reversed(components):
        try:
            info = os.lstat(component)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise UnsafeHomeError("Hermes storage path contains a symlink")


def _ensure_private_directory(path: str) -> None:
    """Create a 0700 directory and reject final/ancestor symlinks."""
    _assert_no_symlink_components(path)
    try:
        os.mkdir(path, mode=0o700)
    except FileExistsError:
        pass
    _assert_no_symlink_components(path)
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode):
        raise UnsafeHomeError("Hermes storage path is not a directory")

    # fchmod on an O_NOFOLLOW directory descriptor closes the final-component
    # race on the Linux runtime. Windows cannot portably open directories this
    # way, so it uses lstat + follow_symlinks=False with a post-check.
    if os.name != "nt":
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise UnsafeHomeError("Hermes storage directory could not be opened safely") from exc
        try:
            if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise UnsafeHomeError("Hermes storage path is not a directory")
            os.fchmod(descriptor, 0o700)
        finally:
            os.close(descriptor)
    else:
        try:
            os.chmod(path, 0o700, follow_symlinks=False)
        except (NotImplementedError, TypeError):
            _assert_no_symlink_components(path)
            os.chmod(path, 0o700)
    _assert_no_symlink_components(path)


def _open_private_file_for_read(path: str):
    """Open a regular file without following its final symlink where supported."""
    _assert_no_symlink_components(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise UnsafeHomeError("Hermes generated file could not be opened safely") from exc
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode):
        os.close(descriptor)
        raise UnsafeHomeError("Hermes generated path is not a regular file")
    return os.fdopen(descriptor, encoding="utf-8")


def _selected_provider_key() -> str | None:
    return PROVIDER_KEY_ENV.get((HERMES_PROVIDER or "").strip().lower())


def _provider_configuration_ready() -> bool:
    key_name = _selected_provider_key()
    return bool(AUTH_TOKEN and HERMES_MODEL and key_name and os.environ.get(key_name))


def _child_environment(home: str) -> dict[str, str]:
    env = {key: os.environ[key] for key in CHILD_ENV_ALLOWLIST if os.environ.get(key)}
    env.update(
        {
            "HOME": home,
            "HERMES_HOME": home,
            "XDG_CONFIG_HOME": os.path.join(home, ".config"),
            "XDG_CACHE_HOME": os.path.join(home, ".cache"),
            "TMPDIR": os.path.join(home, "tmp"),
        }
    )
    key_name = _selected_provider_key()
    if key_name and os.environ.get(key_name):
        env[key_name] = os.environ[key_name]
    return env


def _run_lock_index(home: str) -> int:
    normalized_home = os.path.normcase(os.path.abspath(home))
    digest = hashlib.sha256(normalized_home.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % len(_RUN_LOCK_STRIPES)


def _atomic_write_private(path: str, content: str) -> None:
    """Atomically replace a generated credential/config file with mode 0600."""
    directory = os.path.dirname(path)
    _assert_no_symlink_components(directory)
    try:
        existing = os.lstat(path)
    except FileNotFoundError:
        existing = None
    if existing is not None and stat.S_ISLNK(existing.st_mode):
        raise UnsafeHomeError("Hermes generated path is a symlink")
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=directory, prefix=".osai-", delete=False
        ) as fh:
            temp_path = fh.name
            os.chmod(temp_path, 0o600)
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_path, path)
        # The temporary file was already mode 0600, and replace preserves it.
        # Avoid a post-replace path chmod that could follow a swapped symlink.
        _assert_no_symlink_components(path)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


def _write_private_if_changed(path: str, desired: str) -> None:
    current = None
    try:
        with _open_private_file_for_read(path) as fh:
            current = fh.read()
    except FileNotFoundError:
        pass
    if current != desired:
        _atomic_write_private(path, desired)
    else:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise UnsafeHomeError("Hermes generated file could not be opened safely") from exc
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise UnsafeHomeError("Hermes generated path is not a regular file")
            if os.name != "nt" and hasattr(os, "fchmod"):
                os.fchmod(descriptor, 0o600)
            else:
                _assert_no_symlink_components(path)
                try:
                    os.chmod(path, 0o600, follow_symlinks=False)
                except (NotImplementedError, TypeError):
                    _assert_no_symlink_components(path)
                    os.chmod(path, 0o600)
        finally:
            os.close(descriptor)
        _assert_no_symlink_components(path)


def _ensure_home(org_id: str, user_id: str | None) -> str:
    """Namespaced home with the selected provider key and generated config."""
    safe_org = _safe_segment(org_id)
    safe_user = _safe_segment(user_id or "_org")
    root = os.path.abspath(HERMES_HOME_ROOT)
    org_home = os.path.join(root, safe_org)
    home = os.path.join(org_home, safe_user)

    # Uvicorn executes synchronous endpoints in worker threads. Serialize
    # generated-home updates so first requests cannot observe partial files.
    with _HOME_CONFIG_LOCK:
        for directory in (root, org_home, home):
            _ensure_private_directory(directory)
        for directory in (".config", ".cache", "tmp"):
            _ensure_private_directory(os.path.join(home, directory))

        key_env = _selected_provider_key()
        if not key_env:
            raise RuntimeError("Unsupported or missing HERMES_PROVIDER")
        credential = os.environ.get(key_env)
        if not credential:
            raise RuntimeError("Selected provider credential is missing")
        if "\n" in credential or "\r" in credential:
            raise RuntimeError("Selected provider credential is invalid")
        env_lines = [f"{key_env}={credential}"]
        desired_env = "\n".join(env_lines) + ("\n" if env_lines else "")
        _write_private_if_changed(os.path.join(home, ".env"), desired_env)

        config_lines: list[str] = []
        if HERMES_MODEL:
            if HERMES_BASE_URL and HERMES_PROVIDER:
                config_lines += [
                    "custom_providers:",
                    f"  - name: {HERMES_PROVIDER}",
                    f"    base_url: {HERMES_BASE_URL}",
                    f"    key_env: {key_env}",
                    f"    default_model: {HERMES_MODEL}",
                ]
            config_lines += ["model:"]
            if HERMES_PROVIDER:
                config_lines.append(f"  provider: {HERMES_PROVIDER}")
            config_lines.append(f"  model: {HERMES_MODEL}")
            if HERMES_MAX_TOKENS:
                config_lines.append(f"  max_tokens: {HERMES_MAX_TOKENS}")
        desired_config = "\n".join(config_lines) + ("\n" if config_lines else "")
        # Rewrite only on change — this is the whole file (not user-editable),
        # so a diff means the env-driven settings changed since it was last
        # written; a redeploy/key rotation shouldn't leave stale per-user config
        # (e.g. a since-lowered HERMES_MAX_TOKENS) on the persistent disk.
        _write_private_if_changed(os.path.join(home, "config.yaml"), desired_config)
    return home


def _storage_ready() -> bool:
    """Probe private atomic storage without touching a tenant namespace."""
    root = os.path.abspath(HERMES_HOME_ROOT)
    probe_dir = ""
    probe_file = ""
    try:
        with _HOME_CONFIG_LOCK:
            _ensure_private_directory(root)
            probe_dir = tempfile.mkdtemp(prefix=".readiness-", dir=root)
            _ensure_private_directory(probe_dir)
            probe_file = os.path.join(probe_dir, "probe")
            _atomic_write_private(probe_file, "ready\n")
            with _open_private_file_for_read(probe_file) as fh:
                if fh.read() != "ready\n":
                    return False
            if os.name != "nt" and stat.S_IMODE(os.lstat(probe_file).st_mode) & 0o077:
                return False
        return True
    except (OSError, RuntimeError):
        logger.exception("Hermes readiness storage probe failed")
        return False
    finally:
        try:
            if probe_file:
                os.unlink(probe_file)
            if probe_dir:
                os.rmdir(probe_dir)
        except OSError:
            logger.exception("Hermes readiness storage probe cleanup failed")


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/health/ready")
def readiness(response: Response) -> dict:
    checks = {
        "auth": bool(AUTH_TOKEN),
        "provider": _selected_provider_key() is not None,
        "provider_credential": _provider_configuration_ready(),
        "hermes_cli": shutil.which(HERMES_CMD) is not None,
        "model_configured": bool(HERMES_MODEL),
        "private_storage": _storage_ready(),
    }
    ok = all(checks.values())
    if not ok:
        response.status_code = 503
    # Do not expose which credential or storage prerequisite failed.
    return {"ok": ok}


@app.post("/run")
def run(req: RunRequest, x_sidecar_token: str | None = Header(default=None)) -> dict:
    if not hmac.compare_digest(x_sidecar_token or "", AUTH_TOKEN):
        raise HTTPException(status_code=401, detail="missing/invalid X-Sidecar-Token")
    if not _provider_configuration_ready():
        raise HTTPException(status_code=503, detail="sidecar is not ready")
    try:
        home = _ensure_home(req.org_id, req.user_id)
    except (OSError, RuntimeError):
        logger.exception("Hermes home preparation failed")
        raise HTTPException(status_code=503, detail="sidecar storage unavailable") from None
    env = _child_environment(home)
    # -z = single prompt in, final text out. Provider/model/max_tokens come from
    # the per-user config.yaml seeded by _ensure_home (custom providers like
    # Groq aren't addressable via -m/--provider flags).
    cmd = [HERMES_CMD, "-z", req.prompt]
    if HERMES_TOOLSETS:
        cmd += ["-t", HERMES_TOOLSETS]
    try:
        # A bounded striped lock prevents concurrent Hermes processes from
        # sharing one home while avoiding an unbounded lock-per-user cache.
        # Different homes can run concurrently unless they hash to one stripe.
        with _RUN_LOCK_STRIPES[_run_lock_index(home)]:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=RUN_TIMEOUT,
                env=env,
            )
    except FileNotFoundError:
        return {"result": None, "error": "hermes CLI not installed in this sidecar"}
    except subprocess.TimeoutExpired:
        return {"result": None, "error": "hermes run timed out"}
    if proc.returncode != 0:
        # Provider/CLI stderr can include request context or credentials. Keep
        # the public error stable and record only non-sensitive diagnostics.
        logger.error("Hermes exited unsuccessfully (code=%s)", proc.returncode)
        return {"result": None, "error": "hermes run failed"}
    return {"result": proc.stdout.strip()}
