"""Central model-egress policy — the one place that decides whether content of
a given data tier may be sent to a cloud LLM.

The org's data-routing settings (Org.data_routing, edited on the Data Routing
tab) declare `llm_allowed` per tier. Before this module existed those settings
were stored but never consulted on the Ask path, so red/amber content could
reach the configured cloud provider (production-readiness audit, "red-tier
routing is not consistently enforced"). Every synthesis path must ask this
policy before egress: retrieval synthesis (memory/retriever), and the Hermes
sidecar context builder (agent/hermes_client).
"""

from __future__ import annotations

import logging

logger = logging.getLogger("osai.policy")

# Source of truth for tier policy defaults. The /settings/data-routing route
# serves and edits per-org overrides of this shape.
DEFAULT_DATA_ROUTING: dict[str, dict] = {
    "normal": {
        "allowed_connectors": ["notion", "slack", "freshdesk", "google_drive"],
        "llm_allowed": True,
    },
    # Must match the Amber policy copy in the UI ("only Notion and Google Drive"):
    # a governance default that contradicts its own description reads as a
    # security bug (QA ISSUE-005).
    "amber": {"allowed_connectors": ["notion", "google_drive"], "llm_allowed": False},
    "red": {"allowed_connectors": [], "llm_allowed": False},
}


def load_data_routing(org_id: str) -> dict[str, dict]:
    """The org's routing config, falling back to defaults per missing tier.
    Best-effort: any DB failure returns the (restrictive-for-amber/red) defaults
    rather than raising into a request path."""
    routing = dict(DEFAULT_DATA_ROUTING)
    try:
        from db.models import Org
        from db.session import SessionLocal

        with SessionLocal() as session:
            org = session.get(Org, org_id)
            if org and org.data_routing:
                routing.update(org.data_routing)
    except Exception as exc:  # noqa: BLE001 — policy must never 500 a request
        logger.warning("Could not load data routing for org (using defaults): %s", exc)
    return routing


def cloud_llm_allowed(routing: dict[str, dict], tier: str | None) -> bool:
    """May content of this tier be sent to a cloud model? Unknown tiers are
    treated as most-restrictive (deny) so a typo can't open an egress hole."""
    tier_policy = routing.get(tier or "normal")
    if tier_policy is None:
        return False
    return bool(tier_policy.get("llm_allowed", False))
