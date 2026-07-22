from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts import production_canary as canary


def payload(value: dict) -> bytes:
    return json.dumps(value).encode()


class ProductionCanaryValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.headers = {
            name: expected or "present"
            for name, expected in canary.SECURITY_HEADERS.items()
        }

    def test_web_requires_security_headers_and_page_marker(self) -> None:
        canary.validate_web(
            "web-home",
            b"Run your company on autopilot",
            self.headers,
            b"autopilot",
        )

        with self.assertRaisesRegex(AssertionError, "missing x-frame-options"):
            canary.validate_web(
                "web-home",
                b"Run your company on autopilot",
                {k: v for k, v in self.headers.items() if k != "x-frame-options"},
                b"autopilot",
            )
        with self.assertRaisesRegex(AssertionError, "page marker is missing"):
            canary.validate_web(
                "web-home", b"unrelated page", self.headers, b"autopilot"
            )

    def test_web_markers_are_backed_by_tracked_pages(self) -> None:
        sources = {
            "/": Path("osai-web/public/saas.html").read_bytes(),
            "/login": Path("osai-web/app/login/page.tsx").read_bytes(),
        }
        for _, path, marker in canary.WEB_CHECKS:
            self.assertIn(marker, sources[path])

    def test_same_origin_auth_proxy_must_expose_production_auth_config(self) -> None:
        canary.validate_auth_config(
            payload({"google_enabled": True, "email_login_enabled": False})
        )
        web_api_paths = {label: path for label, path, _ in canary.WEB_API_CHECKS}
        self.assertEqual(web_api_paths["web-api-auth"], "/api/auth/config")

        with self.assertRaisesRegex(AssertionError, "Google OAuth"):
            canary.validate_auth_config(
                payload({"google_enabled": False, "email_login_enabled": False})
            )
        with self.assertRaisesRegex(AssertionError, "email login"):
            canary.validate_auth_config(
                payload({"google_enabled": True, "email_login_enabled": True})
            )

    def test_every_github_action_is_commit_pinned(self) -> None:
        action_ref = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)", re.MULTILINE)
        immutable_ref = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")

        for workflow in sorted(Path(".github/workflows").glob("*.yml")):
            source = workflow.read_text()
            refs = action_ref.findall(source)
            for ref in refs:
                self.assertRegex(ref, immutable_ref, f"mutable action in {workflow}: {ref}")

    def test_workflow_paths_track_the_build_identity_contract(self) -> None:
        workflow = Path(".github/workflows/production-canary.yml").read_text()
        self.assertIn('"osai-web/app/build-info/route.ts"', workflow)
        self.assertIn('"osai-backend/api/routes/health.py"', workflow)
        self.assertIn('OSAI_CANARY_REQUIRE_BUILD_ID: "1"', workflow)

        backend_ci = Path(".github/workflows/ci.yml").read_text()
        self.assertGreaterEqual(backend_ci.count('"scripts/production_canary.py"'), 2)
        self.assertGreaterEqual(
            backend_ci.count('".github/workflows/production-canary.yml"'), 2
        )

    def test_fetch_rejects_a_redirect_to_another_healthy_page(self) -> None:
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b"healthy but wrong page"
        response.headers.items.return_value = []
        response.status = 200
        response.geturl.return_value = "https://example.test/dashboard"
        with (
            patch.object(canary, "urlopen", return_value=response),
            self.assertRaisesRegex(AssertionError, "redirected to"),
        ):
            canary.fetch("web-login", "https://example.test/login")

    def test_health_requires_the_expected_deploy(self) -> None:
        good = payload(
            {
                "status": "ok",
                "service": "osai-api",
                "environment": "production",
                "build_sha": "abc123",
            }
        )
        with (
            patch.object(canary, "REQUIRE_BUILD", True),
            patch.object(canary, "EXPECTED_BUILD_SHA", "abc123"),
        ):
            self.assertEqual(canary.validate_health(good), "abc123")
            with self.assertRaisesRegex(AssertionError, "expected build_sha"):
                canary.validate_health(
                    payload(
                        {
                            "status": "ok",
                            "service": "osai-api",
                            "environment": "production",
                            "build_sha": "stale",
                        }
                    )
                )

            with self.assertRaisesRegex(AssertionError, "production environment"):
                canary.validate_health(
                    payload(
                        {
                            "status": "ok",
                            "service": "osai-api",
                            "environment": "local",
                            "build_sha": "abc123",
                        }
                    )
                )

    def test_frontend_build_info_requires_the_expected_deploy(self) -> None:
        good = payload(
            {
                "status": "ok",
                "service": "osai-web",
                "environment": "production",
                "build_sha": "abc123",
            }
        )
        with (
            patch.object(canary, "REQUIRE_BUILD", True),
            patch.object(canary, "EXPECTED_BUILD_SHA", "abc123"),
        ):
            self.assertEqual(canary.validate_frontend_build(good), "abc123")
            with self.assertRaisesRegex(AssertionError, "expected build_sha"):
                canary.validate_frontend_build(
                    payload(
                        {
                            "status": "ok",
                            "service": "osai-web",
                            "environment": "production",
                            "build_sha": "stale",
                        }
                    )
                )
            with self.assertRaisesRegex(AssertionError, "build_sha is unknown"):
                canary.validate_frontend_build(
                    payload(
                        {
                            "status": "ok",
                            "service": "osai-web",
                            "environment": "production",
                            "build_sha": "unknown",
                        }
                    )
                )
            with self.assertRaisesRegex(AssertionError, "build_sha is missing"):
                canary.validate_frontend_build(
                    payload(
                        {
                            "status": "ok",
                            "service": "osai-web",
                            "environment": "production",
                        }
                    )
                )

        with self.assertRaisesRegex(AssertionError, "production environment"):
            canary.validate_frontend_build(
                payload(
                    {
                        "status": "ok",
                        "service": "osai-web",
                        "environment": "local",
                        "build_sha": "abc123",
                    }
                )
            )

    def test_frontend_build_info_route_has_portable_fallbacks(self) -> None:
        source = Path("osai-web/app/build-info/route.ts").read_text()
        self.assertIn('service: "osai-web"', source)
        self.assertIn('envValue("VERCEL_ENV")', source)
        self.assertIn('envValue("VERCEL_GIT_COMMIT_SHA")', source)
        self.assertIn('envValue("OSAI_BUILD_SHA")', source)
        self.assertIn('"unknown"', source)
        self.assertIn('"Cache-Control": "no-store"', source)
        web_api_paths = {label: path for label, path, _ in canary.WEB_API_CHECKS}
        self.assertEqual(web_api_paths["web-build"], "/build-info")

    def test_frontend_and_backend_build_shas_must_match(self) -> None:
        canary.validate_matching_build_shas("abc123", "abc123")
        with self.assertRaisesRegex(AssertionError, "identity is incomplete"):
            canary.validate_matching_build_shas("unreported", "unreported")
        with self.assertRaisesRegex(AssertionError, "deploy identity mismatch"):
            canary.validate_matching_build_shas("frontend", "backend")

    def test_main_rejects_frontend_backend_deploy_mismatch(self) -> None:
        with (
            patch.object(canary, "WEB_CHECKS", ()),
            patch.object(
                canary,
                "WEB_API_CHECKS",
                (("web-build", "/build-info", lambda _body: "frontend"),),
            ),
            patch.object(
                canary,
                "API_CHECKS",
                (("health", "/health", lambda _body: "backend"),),
            ),
            patch.object(canary, "fetch", return_value=(b"{}", {}, 1.0)),
            patch("builtins.print"),
            self.assertRaisesRegex(AssertionError, "deploy identity mismatch"),
        ):
            canary.main()

    def test_unknown_sha_is_only_allowed_when_build_gate_is_disabled(self) -> None:
        with (
            patch.object(canary, "REQUIRE_BUILD", False),
            patch.object(canary, "EXPECTED_BUILD_SHA", ""),
        ):
            self.assertEqual(canary.validate_build_sha("local", "unknown"), "unknown")

    def test_readiness_and_capability_contracts_fail_closed(self) -> None:
        canary.validate_ready(
            payload({"status": "ready", "checks": {"db": {"ok": True}}})
        )
        with self.assertRaisesRegex(AssertionError, "failed checks: db"):
            canary.validate_ready(
                payload({"status": "ready", "checks": {"db": {"ok": False}}})
            )

        capabilities = {
            "scheduler": False,
            "automation_cadences": ["manual"],
            "connectors": [],
            "sql_sources": True,
            "workflow_execution": True,
            "semantic_embeddings": True,
            "embedding_model": "test",
            "google_oauth": True,
            "email_login": False,
        }
        canary.validate_capabilities(payload(capabilities))
        capabilities["automation_cadences"] = ["manual", "daily"]
        with self.assertRaisesRegex(AssertionError, "scheduler/cadence"):
            canary.validate_capabilities(payload(capabilities))

        capabilities["automation_cadences"] = ["manual"]
        capabilities["google_oauth"] = False
        with self.assertRaisesRegex(AssertionError, "Google OAuth"):
            canary.validate_capabilities(payload(capabilities))

        capabilities["google_oauth"] = True
        capabilities["email_login"] = True
        with self.assertRaisesRegex(AssertionError, "email login"):
            canary.validate_capabilities(payload(capabilities))


if __name__ == "__main__":
    unittest.main()
