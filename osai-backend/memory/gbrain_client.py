"""Python client for the gbrain knowledge-graph sidecar.

gbrain is a Bun/TypeScript service (vendored at services/gbrain). We talk to it
by invoking its CLI with `--json` and a per-org GBRAIN_HOME. Pages + the
self-wiring typed graph + keyword search work without any LLM key; vector/hybrid
search and synthesis require an embedding key (configured on gbrain separately).

Gated by `settings.gbrain_home`: if unset, `available()` is False and OSAI falls
back to the Postgres-derived graph (graph/provider.py). This keeps gbrain opt-in
so the backend runs with or without it.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

from config import settings

logger = logging.getLogger("osai.gbrain")


class GbrainClient:
    def __init__(
        self,
        home: str | None = None,
        cli_dir: str | None = None,
    ) -> None:
        self.home = home or settings.gbrain_home
        self.cli_dir = Path(cli_dir or settings.gbrain_cli_dir).resolve()

    def available(self) -> bool:
        return bool(
            self.home
            and shutil.which("bun")
            and (self.cli_dir / "src" / "cli.ts").exists()
        )

    def _run(self, args: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
        env = {
            **os.environ,
            "GBRAIN_HOME": str(self.home),
            "GBRAIN_NO_BANNER": "1",
            "GBRAIN_SKIP_STARTUP_HOOKS": "1",
        }
        return subprocess.run(
            ["bun", "run", str(self.cli_dir / "src" / "cli.ts"), *args],
            input=stdin,
            capture_output=True,
            text=True,
            env=env,
            cwd=str(self.cli_dir),
            timeout=60,
        )

    def put_page(self, slug: str, markdown: str) -> bool:
        """Create/update a page. Wikilinks ([[slug]]) auto-wire typed graph edges."""
        result = self._run(["put", slug], stdin=markdown)
        if result.returncode != 0:
            logger.warning("gbrain put %s failed: %s", slug, result.stderr[:200])
        return result.returncode == 0

    def get_page(self, slug: str) -> str | None:
        result = self._run(["get", slug])
        return result.stdout if result.returncode == 0 and result.stdout else None

    def search(self, query: str, limit: int = 8) -> list[dict]:
        """Keyword (tsvector) search — works without embeddings."""
        result = self._run(["search", query, "-n", str(limit), "--json"])
        return _parse_json_list(result.stdout)

    def graph_query(self, slug: str, depth: int = 2) -> list[dict]:
        """Edge-based graph traversal from a page (typed, self-wired)."""
        result = self._run(["graph", slug, "--depth", str(depth), "--json"])
        return _parse_json_list(result.stdout)

    def backlinks(self, slug: str) -> list[dict]:
        result = self._run(["backlinks", slug, "--json"])
        return _parse_json_list(result.stdout)


def _parse_json_list(stdout: str) -> list[dict]:
    stdout = (stdout or "").strip()
    if not stdout:
        return []
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("results", "nodes", "items"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def get_default_gbrain_client() -> GbrainClient:
    return GbrainClient()
