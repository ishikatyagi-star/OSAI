"""Workflow action-item approval: explicit state machine, no double execution.

Approving an item pushes a real side effect to a customer's tools (a Freshdesk
ticket, a Slack message, a Notion page). Two approvals of the same item must
therefore execute exactly once — the guarantee SEC-007 already gives the Ask
confirm path, which this path needed just as much (SHE-6 P0).

Lifecycle: needs_review -> executing -> completed | failed_preflight |
outcome_unknown, plus cancelled. Only failed_preflight is retryable.
"""

from __future__ import annotations

import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import ActionItemRecord, Base, Org, WorkflowRun
from db.repositories import cancel_action_item, claim_action_item


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed_item(session, status: str = "needs_review") -> str:
    org_id = "demo-org"
    if session.get(Org, org_id) is None:
        session.add(Org(id=org_id, name="demo"))
    run_id = f"run-{uuid.uuid4()}"
    session.add(
        WorkflowRun(
            id=run_id,
            org_id=org_id,
            kind="transcript",
            status="completed",
            input_text="Anish: I'll open a ticket for the Redis connection pool errors.",
        )
    )
    item_id = f"item-{uuid.uuid4()}"
    session.add(
        ActionItemRecord(
            id=item_id,
            workflow_run_id=run_id,
            title="Open a ticket for the Redis errors",
            destination="freshdesk",
            status=status,
        )
    )
    session.commit()
    return item_id


def test_only_one_of_two_approvals_may_execute():
    """The core guarantee: a double-click cannot create two Freshdesk tickets."""
    session = _session()
    item_id = _seed_item(session)

    first = claim_action_item(session, item_id=item_id, org_id="demo-org")
    second = claim_action_item(session, item_id=item_id, org_id="demo-org")

    assert first == "claimed"
    assert second == "taken"
    assert session.get(ActionItemRecord, item_id).status == "executing"


def test_claim_moves_the_item_out_of_needs_review():
    session = _session()
    item_id = _seed_item(session)
    assert session.get(ActionItemRecord, item_id).status == "needs_review"
    claim_action_item(session, item_id=item_id, org_id="demo-org")
    assert session.get(ActionItemRecord, item_id).status == "executing"


def test_a_preflight_failure_can_be_retried():
    """A failure proven to precede provider dispatch remains retryable."""
    session = _session()
    item_id = _seed_item(session, status="failed_preflight")
    assert claim_action_item(session, item_id=item_id, org_id="demo-org") == "claimed"


def test_ambiguous_failure_cannot_be_retried():
    session = _session()
    item_id = _seed_item(session, status="outcome_unknown")
    assert claim_action_item(session, item_id=item_id, org_id="demo-org") == "taken"


def test_completed_items_cannot_be_reclaimed():
    """Terminal means terminal: no re-executing something already done."""
    session = _session()
    item_id = _seed_item(session, status="completed")
    assert claim_action_item(session, item_id=item_id, org_id="demo-org") == "taken"


def test_cancelled_items_cannot_be_claimed():
    """A rejected item must never be executed by a later approval."""
    session = _session()
    item_id = _seed_item(session)
    assert cancel_action_item(session, item_id=item_id, org_id="demo-org") == "cancelled"
    assert session.get(ActionItemRecord, item_id).status == "cancelled"
    assert claim_action_item(session, item_id=item_id, org_id="demo-org") == "taken"


def test_cannot_cancel_an_item_already_executing():
    """Once the side effect is in flight, cancelling would lie about the outcome."""
    session = _session()
    item_id = _seed_item(session)
    assert claim_action_item(session, item_id=item_id, org_id="demo-org") == "claimed"
    assert cancel_action_item(session, item_id=item_id, org_id="demo-org") == "taken"
    assert session.get(ActionItemRecord, item_id).status == "executing"


def test_unknown_item_is_absent():
    session = _session()
    assert claim_action_item(session, item_id="nope", org_id="demo-org") == "absent"
