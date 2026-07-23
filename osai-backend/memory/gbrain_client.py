"""Python adapter for the gbrain knowledge-graph CLI.

gbrain is a Bun/TypeScript project (vendored at services/gbrain). We invoke its
CLI with `--json` and a per-org GBRAIN_HOME. Pages + the
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

    def list_pages(self, limit: int = 100) -> list[dict]:
        """All pages ({slug, type, title, updated_at}) — feeds the org graph."""
        result = self._run(["list", "--json", "--limit", str(limit)])
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


def get_org_gbrain_client(org_id: str) -> GbrainClient:
    """Per-org brain: each org gets its own GBRAIN_HOME subdirectory so pages
    and graph edges never mix across tenants (same isolation stance as the
    Hermes sidecar's per-user HERMES_HOME)."""
    home = settings.gbrain_home
    return GbrainClient(home=str(Path(home) / org_id) if home else None)


def _page_slug(source_id: str) -> str:
    """Stable, filesystem/URL-safe page slug for a source document."""
    return "doc-" + "".join(
        c if (c.isalnum() and c.isascii()) or c in "-_" else "-" for c in source_id
    )


def mirror_documents(org_id: str, documents: list) -> int:
    """Best-effort mirror of ingested documents into the org's gbrain as pages.

    Wikilinks are not synthesized here — gbrain self-wires typed edges from the
    page content. Inert when gbrain isn't configured; any failure is logged and
    skipped so ingestion never depends on the sidecar. Returns pages written.
    """
    client = get_org_gbrain_client(org_id)
    if not client.available():
        return 0
    written = 0
    for doc in documents:
        try:
            title = getattr(doc, "title", None) or "Untitled"
            text = getattr(doc, "text", "") or ""
            source_type = getattr(doc, "source_type", "unknown")
            markdown = f"# {title}\n\nsource: {source_type}\n\n{text}"
            if client.put_page(_page_slug(getattr(doc, "source_id", title)), markdown):
                written += 1
        except Exception as exc:  # noqa: BLE001 — mirroring must never break ingestion
            logger.warning("gbrain mirror failed for a document: %s", exc)
    return written
