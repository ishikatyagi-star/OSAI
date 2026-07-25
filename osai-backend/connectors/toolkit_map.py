"""Map Composio toolkit slugs to stable OSAI source keys.

Source keys are persisted on indexed documents and sync runs, so Google Drive
keeps its historical ``google_drive`` key even though Composio calls the
toolkit ``googledrive``.
"""

from __future__ import annotations

COMPOSIO_TO_SOURCE_KEY: dict[str, str] = {
    "notion": "notion",
    "googledrive": "google_drive",
    "slack": "slack",
    "gmail": "gmail",
    "freshdesk": "freshdesk",
}

SOURCE_KEY_TO_COMPOSIO: dict[str, str] = {
    value: key for key, value in COMPOSIO_TO_SOURCE_KEY.items()
}

HARD_DISABLED_CONNECTOR_KEYS = frozenset({"zoom"})


def to_source_key(toolkit_slug: str) -> str:
    return COMPOSIO_TO_SOURCE_KEY.get(toolkit_slug, toolkit_slug)


def to_toolkit_slug(source_key: str) -> str:
    return SOURCE_KEY_TO_COMPOSIO.get(source_key, source_key)
