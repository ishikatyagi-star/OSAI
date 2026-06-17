"""Single source of truth mapping Composio toolkit slugs ↔ OSAI native connector
keys, so a Composio OAuth connection drives the one native integration card
(e.g. Composio's `googledrive` is OSAI's `google_drive`)."""

from __future__ import annotations

# Composio slug -> native connector key (ConnectorRecord.key).
COMPOSIO_TO_NATIVE: dict[str, str] = {
    "notion": "notion",
    "googledrive": "google_drive",
    "slack": "slack",
    "gmail": "gmail",
    "freshdesk": "freshdesk",
}

# Reverse: native key -> Composio slug.
NATIVE_TO_COMPOSIO: dict[str, str] = {v: k for k, v in COMPOSIO_TO_NATIVE.items()}


def to_native_key(toolkit_slug: str) -> str:
    return COMPOSIO_TO_NATIVE.get(toolkit_slug, toolkit_slug)
