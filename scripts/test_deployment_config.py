from __future__ import annotations

import ast
import configparser
import re
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def read_utf8(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def env_assignments(source: str) -> dict[str, str]:
    assignments: dict[str, str] = {}
    for line in source.splitlines():
        match = re.fullmatch(r"\s*#?\s*([A-Z][A-Z0-9_]*)=(.*)", line)
        if match:
            assignments[match.group(1)] = match.group(2).strip()
    return assignments


def compose_service(source: str, name: str) -> str:
    lines = source.splitlines()
    marker = f"  {name}:"
    try:
        start = lines.index(marker)
    except ValueError as exc:
        raise AssertionError(f"missing Compose service: {name}") from exc

    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line and not line.startswith(" "):
            end = index
            break
        if re.fullmatch(r"  [a-z0-9_-]+:", line):
            end = index
            break
    return "\n".join(lines[start:end])


def compose_list(block: str, name: str) -> list[str]:
    match = re.search(
        rf"(?m)^    {re.escape(name)}:\n(?P<body>(?:      - [^\n]*(?:\n|$))*)",
        block,
    )
    if match is None:
        raise AssertionError(f"missing Compose list: {name}")
    return [line.removeprefix("      - ").strip('"') for line in match.group("body").splitlines()]


def render_service(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^  - type: [a-z]+\n    name: {re.escape(name)}\n"
        rf"(?P<body>.*?)(?=^  - type:|\Z)",
        source,
    )
    if match is None:
        raise AssertionError(f"missing Render service: {name}")
    return match.group("body")


class DeploymentConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.compose = read_utf8(ROOT / "docker-compose.yml")

    def assert_dependency(self, service: str, dependency: str, condition: str) -> None:
        block = compose_service(self.compose, service)
        pattern = (
            rf"(?m)^      {re.escape(dependency)}:\n"
            rf"        condition: {re.escape(condition)}$"
        )
        self.assertRegex(block, pattern)

    def test_production_image_never_seeds_during_startup(self) -> None:
        dockerfile = read_utf8(ROOT / "osai-backend" / "Dockerfile")
        command = next(line for line in dockerfile.splitlines() if line.startswith("CMD "))

        self.assertIn("alembic upgrade head", command)
        self.assertIn("uvicorn api.main:app", command)
        self.assertIn("--no-proxy-headers", command)
        self.assertNotIn("db.seed", dockerfile)

    def test_app_is_the_only_proxy_header_trust_owner(self) -> None:
        api = compose_service(self.compose, "api")
        self.assertIn("--no-proxy-headers", api)

        for path in ("README.md", "osai-backend/README.md"):
            documented_commands = [
                line
                for line in read_utf8(ROOT / path).splitlines()
                if "uvicorn api.main:app" in line
            ]
            self.assertTrue(documented_commands, path)
            self.assertTrue(
                all("--no-proxy-headers" in line for line in documented_commands),
                path,
            )

        render_api = render_service(read_utf8(ROOT / "render.yaml"), "osai-api")
        self.assertRegex(
            render_api,
            r"(?m)^      - key: OSAI_RATE_LIMIT_FORWARDED_FOR_MODE\n"
            r"        value: render_first$",
        )

    def test_compose_runs_migrations_once_before_api_and_worker(self) -> None:
        migrate = compose_service(self.compose, "migrate")
        self.assertIn("command: uv run alembic upgrade head", migrate)
        self.assertIn('restart: "no"', migrate)
        self.assert_dependency("migrate", "postgres", "service_healthy")

        for service in ("api", "worker"):
            self.assert_dependency(service, "migrate", "service_completed_successfully")
            for datastore in ("postgres", "redis", "qdrant"):
                self.assert_dependency(service, datastore, "service_healthy")

    def test_compose_datastores_are_healthy_and_loopback_only(self) -> None:
        expected_ports = {
            "postgres": "127.0.0.1:5433:5432",
            "redis": "127.0.0.1:6379:6379",
            "qdrant": "127.0.0.1:6333:6333",
        }
        expected_checks = {
            "postgres": "pg_isready",
            "redis": "redis-cli",
            "qdrant": "/dev/tcp/127.0.0.1/6333",
        }
        for service, port in expected_ports.items():
            block = compose_service(self.compose, service)
            self.assertIn("healthcheck:", block)
            self.assertIn(expected_checks[service], block)
            self.assertEqual(compose_list(block, "ports"), [port])

        api = compose_service(self.compose, "api")
        self.assertIn("/health/ready", api)

    def test_render_and_alembic_use_deployment_safe_settings(self) -> None:
        render = read_utf8(ROOT / "render.yaml")
        self.assertIn("healthCheckPath: /health/ready", render_service(render, "osai-api"))
        self.assertNotIn("name: osai-hermes", render)
        for service in ("osai-api", "osai-worker"):
            self.assertNotIn("OSAI_HERMES_SIDECAR", render_service(render, service))

        alembic = configparser.ConfigParser(interpolation=None)
        alembic.read(ROOT / "osai-backend" / "alembic.ini")
        self.assertEqual(alembic["alembic"]["path_separator"], "os")

    def test_env_examples_match_runtime_configuration(self) -> None:
        backend_env = env_assignments(read_utf8(ROOT / "osai-backend" / ".env.example"))
        render = read_utf8(ROOT / "render.yaml")
        render_vars: set[str] = set()
        for service in ("osai-api", "osai-worker"):
            render_vars.update(
                re.findall(r"(?m)^      - key: (OSAI_[A-Z0-9_]+)$", render_service(render, service))
            )
        self.assertLessEqual(render_vars, backend_env.keys())

        config_tree = ast.parse(read_utf8(ROOT / "osai-backend" / "config.py"))
        settings_class = next(
            node
            for node in config_tree.body
            if isinstance(node, ast.ClassDef) and node.name == "Settings"
        )
        settings_vars = {
            f"OSAI_{node.target.id.upper()}"
            for node in settings_class.body
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        }
        self.assertLessEqual(render_vars, settings_vars)

        for name, value in backend_env.items():
            if re.search(r"(?:API_KEY|TOKEN|SECRET)$", name):
                self.assertEqual(value, "", f"secret placeholder must be blank: {name}")

        host_urls = {
            "postgres": backend_env["OSAI_DATABASE_URL"],
            "redis": backend_env["OSAI_REDIS_URL"],
            "qdrant": backend_env["OSAI_QDRANT_URL"],
        }
        for service, url in host_urls.items():
            _, published_port, _ = compose_list(compose_service(self.compose, service), "ports")[
                0
            ].rsplit(":", 2)
            self.assertEqual(urlsplit(url).port, int(published_port))

        frontend_env = env_assignments(read_utf8(ROOT / "osai-web" / ".env.example"))
        frontend_sources = "\n".join(
            read_utf8(ROOT / path)
            for path in (
                "osai-web/next.config.ts",
                "osai-web/lib/api.ts",
                "osai-web/lib/demo.ts",
            )
        )
        referenced = set(re.findall(r"process\.env\.(NEXT_PUBLIC_[A-Z0-9_]+)", frontend_sources))
        documented = {name for name in frontend_env if name.startswith("NEXT_PUBLIC_")}
        self.assertEqual(documented, referenced)

    def test_local_markdown_links_resolve(self) -> None:
        documents = sorted(ROOT.glob("*.md")) + sorted((ROOT / "docs").glob("*.md"))
        documents.append(ROOT / "services" / "hermes-sidecar" / "README.md")
        link_pattern = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")

        for document in documents:
            for raw_target in link_pattern.findall(read_utf8(document)):
                raw_target = raw_target.strip()
                if raw_target.startswith("<") and ">" in raw_target:
                    target = raw_target[1 : raw_target.index(">")]
                else:
                    target = raw_target.split(maxsplit=1)[0]
                if target.startswith(("#", "/")) or re.match(
                    r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE
                ):
                    continue
                path = unquote(target.split("#", 1)[0].split("?", 1)[0])
                if path:
                    self.assertTrue(
                        (document.parent / path).exists(),
                        f"broken local link in {document.relative_to(ROOT)}: {target}",
                    )


if __name__ == "__main__":
    unittest.main()
