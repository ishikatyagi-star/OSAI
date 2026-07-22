#!/usr/bin/env python3
"""Read-only cold/warm production smoke check using only the Python stdlib."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from urllib.request import Request, urlopen

WEB_URL = os.getenv("OSAI_CANARY_WEB_URL", "https://trysheldon.vercel.app").rstrip("/")
API_URL = os.getenv("OSAI_CANARY_API_URL", "https://osai-api-ema6.onrender.com").rstrip("/")
TIMEOUT = float(os.getenv("OSAI_CANARY_TIMEOUT_SECONDS", "120"))
REQUIRE_BUILD = os.getenv("OSAI_CANARY_REQUIRE_BUILD_ID", "1") != "0"
EXPECTED_BUILD_SHA = os.getenv("OSAI_CANARY_EXPECTED_BUILD_SHA", "").strip()

SECURITY_HEADERS = {
    "content-security-policy": None,
    "permissions-policy": None,
    "referrer-policy": None,
    "strict-transport-security": None,
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
}


def fetch(label: str, url: str) -> tuple[bytes, dict[str, str], float]:
    started = time.perf_counter()
    request = Request(url, headers={"User-Agent": "osai-production-canary/1"})
    with urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 - fixed/configured HTTPS targets
        body = response.read()
        headers = {key.lower(): value for key, value in response.headers.items()}
        status = response.status
        final_url = response.geturl()
    elapsed_ms = (time.perf_counter() - started) * 1000
    if status != 200:
        raise AssertionError(f"{label}: expected HTTP 200, got {status}")
    if final_url.rstrip("/") != url.rstrip("/"):
        raise AssertionError(
            f"{label}: redirected to {final_url!r} instead of serving {url!r}"
        )
    return body, headers, elapsed_ms


def decode_json(label: str, body: bytes) -> dict:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AssertionError(f"{label}: response is not JSON") from exc
    if not isinstance(value, dict):
        raise AssertionError(f"{label}: expected a JSON object")
    return value


def validate_web(
    label: str, body: bytes, headers: dict[str, str], marker: bytes
) -> None:
    for name, expected in SECURITY_HEADERS.items():
        actual = headers.get(name)
        if actual is None:
            raise AssertionError(f"{label}: missing {name} header")
        if expected is not None and actual.lower() != expected.lower():
            raise AssertionError(f"{label}: {name} must be {expected!r}, got {actual!r}")
    if marker not in body:
        raise AssertionError(f"{label}: expected Sheldon page marker is missing")


def validate_build_sha(label: str, build_sha: object) -> str:
    if not isinstance(build_sha, str) or not build_sha.strip():
        raise AssertionError(f"{label}: build_sha is missing")
    build_sha = build_sha.strip()
    if REQUIRE_BUILD and build_sha.lower() == "unknown":
        raise AssertionError(f"{label}: build_sha is unknown")
    if EXPECTED_BUILD_SHA and build_sha != EXPECTED_BUILD_SHA:
        raise AssertionError(
            f"{label}: expected build_sha {EXPECTED_BUILD_SHA!r}, got {build_sha!r}"
        )
    return build_sha


def validate_frontend_build(body: bytes) -> str:
    value = decode_json("web-build", body)
    if value.get("status") != "ok" or value.get("service") != "osai-web":
        raise AssertionError(f"web-build: unexpected payload {value}")
    if value.get("environment") != "production":
        raise AssertionError(
            "web-build: expected production environment, "
            f"got {value.get('environment')!r}"
        )
    return validate_build_sha("web-build", value.get("build_sha"))


def validate_health(body: bytes) -> str:
    value = decode_json("health", body)
    if value.get("status") != "ok" or value.get("service") != "osai-api":
        raise AssertionError(f"health: unexpected payload {value}")
    if value.get("environment") != "production":
        raise AssertionError(
            f"health: expected production environment, got {value.get('environment')!r}"
        )
    return validate_build_sha("health", value.get("build_sha"))


def validate_matching_build_shas(frontend_sha: str, backend_sha: str) -> None:
    if "unreported" in {frontend_sha, backend_sha}:
        raise AssertionError("deploy identity is incomplete")
    if frontend_sha != backend_sha:
        raise AssertionError(
            "deploy identity mismatch: "
            f"frontend build_sha {frontend_sha!r}, backend build_sha {backend_sha!r}"
        )


def validate_live(body: bytes) -> None:
    if decode_json("live", body).get("status") != "alive":
        raise AssertionError("live: status is not alive")


def validate_ready(body: bytes) -> None:
    value = decode_json("ready", body)
    checks = value.get("checks")
    if value.get("status") != "ready" or not isinstance(checks, dict):
        raise AssertionError(f"ready: unexpected payload {value}")
    failed = [name for name, result in checks.items() if not result.get("ok")]
    if failed:
        raise AssertionError(f"ready: failed checks: {', '.join(failed)}")


def validate_capabilities(body: bytes) -> None:
    value = decode_json("capabilities", body)
    required = {
        "scheduler",
        "automation_cadences",
        "connectors",
        "sql_sources",
        "workflow_execution",
        "semantic_embeddings",
        "embedding_model",
        "google_oauth",
        "email_login",
    }
    missing = sorted(required - value.keys())
    if missing:
        raise AssertionError(f"capabilities: missing {', '.join(missing)}")
    if value["google_oauth"] is not True:
        raise AssertionError("capabilities: Google OAuth must be enabled in production")
    if value["email_login"] is not False:
        raise AssertionError(
            "capabilities: passwordless email login must be disabled in production"
        )
    cadences = set(value["automation_cadences"])
    if "manual" not in cadences or bool(cadences - {"manual"}) != bool(value["scheduler"]):
        raise AssertionError("capabilities: scheduler/cadence contract is inconsistent")


def validate_auth_config(body: bytes) -> None:
    value = decode_json("web-api-auth", body)
    if value.get("google_enabled") is not True:
        raise AssertionError("web-api-auth: Google OAuth must be enabled in production")
    if value.get("email_login_enabled") is not False:
        raise AssertionError("web-api-auth: email login must be disabled in production")


API_CHECKS: tuple[tuple[str, str, Callable[[bytes], object]], ...] = (
    ("health", "/health", validate_health),
    ("live", "/health/live", validate_live),
    ("ready", "/health/ready", validate_ready),
    ("capabilities", "/capabilities", validate_capabilities),
)

WEB_CHECKS: tuple[tuple[str, str, bytes], ...] = (
    ("web-home", "/", b"Run your company on autopilot"),
    ("web-login", "/login", b"Welcome to Sheldon"),
)

WEB_API_CHECKS: tuple[tuple[str, str, Callable[[bytes], object]], ...] = (
    ("web-build", "/build-info", validate_frontend_build),
    ("web-api-auth", "/api/auth/config", validate_auth_config),
)


def main() -> None:
    print("phase  target        http  elapsed_ms")
    print("-----  ------------  ----  ----------")
    frontend_build_sha = "unreported"
    backend_build_sha = "unreported"
    for phase in ("cold", "warm"):
        phase_frontend_sha = "unreported"
        phase_backend_sha = "unreported"
        for label, path, marker in WEB_CHECKS:
            body, headers, elapsed = fetch(label, WEB_URL + path)
            validate_web(label, body, headers, marker)
            print(f"{phase:<5}  {label:<12}  200   {elapsed:>10.0f}")
        for label, path, validate in WEB_API_CHECKS:
            body, _, elapsed = fetch(label, WEB_URL + path)
            result = validate(body)
            if label == "web-build":
                phase_frontend_sha = str(result)
            print(f"{phase:<5}  {label:<12}  200   {elapsed:>10.0f}")
        for label, path, validate in API_CHECKS:
            body, _, elapsed = fetch(label, API_URL + path)
            result = validate(body)
            if label == "health":
                phase_backend_sha = str(result)
            print(f"{phase:<5}  {label:<12}  200   {elapsed:>10.0f}")
        validate_matching_build_shas(phase_frontend_sha, phase_backend_sha)
        frontend_build_sha = phase_frontend_sha
        backend_build_sha = phase_backend_sha
    print(f"frontend_build_sha: {frontend_build_sha}")
    print(f"backend_build_sha: {backend_build_sha}")
    print("result: healthy")


if __name__ == "__main__":
    main()
