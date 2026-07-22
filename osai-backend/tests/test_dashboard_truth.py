from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.routes.dashboard import _metrics
from db.models import (
    ActionItemRecord,
    Base,
    ConnectorAccount,
    ConnectorRecord,
    DecisionRecord,
    Org,
    SourceDocumentRecord,
    User,
    WorkflowRun,
)


def test_dashboard_metrics_come_from_records_visible_to_the_viewer():
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    now = datetime.now(UTC).replace(tzinfo=None)
    try:
        db.add(Org(id="org", name="Dashboard truth"))
        db.add_all(
            [
                User(
                    id="owner",
                    org_id="org",
                    email="owner@example.test",
                    display_name="Owner",
                    role="member",
                ),
                User(
                    id="other",
                    org_id="org",
                    email="other@example.test",
                    display_name="Other",
                    role="member",
                ),
            ]
        )
        db.add(ConnectorRecord(key="notion", display_name="Notion", capabilities=[]))
        # A legacy row can survive an upgrade, but hard-disabled Zoom must not
        # count as connected or render as a healthy dashboard connection.
        db.add(ConnectorRecord(key="zoom", display_name="Zoom", capabilities=[]))
        db.add(
            ConnectorAccount(
                org_id="org",
                connector_key="notion",
                auth_state="connected",
            )
        )
        db.add(
            ConnectorAccount(
                org_id="org",
                connector_key="zoom",
                auth_state="connected",
            )
        )
        # A document source is not proof that a connector is currently connected.
        db.add(
            SourceDocumentRecord(
                id="doc",
                org_id="org",
                source_type="stale_source",
                external_id="1",
                title="Old import",
                text="content",
            )
        )
        db.add_all(
            [
                DecisionRecord(
                    id="decision-new",
                    org_id="org",
                    title="Pending decision",
                    status="proposed",
                    decided_at=now,
                ),
                DecisionRecord(
                    id="decision-old",
                    org_id="org",
                    title="Approved decision",
                    status="approved",
                    decided_at=now - timedelta(days=1),
                ),
                WorkflowRun(
                    id="run-owner",
                    org_id="org",
                    created_by="owner",
                    kind="meeting_action_items",
                    status="completed",
                    input_text="owner run",
                ),
                WorkflowRun(
                    id="run-other",
                    org_id="org",
                    created_by="other",
                    kind="meeting_action_items",
                    status="completed",
                    input_text="other run",
                ),
            ]
        )
        db.add_all(
            [
                ActionItemRecord(
                    id="action-owner",
                    workflow_run_id="run-owner",
                    title="Owner",
                    status="needs_review",
                ),
                ActionItemRecord(
                    id="action-other",
                    workflow_run_id="run-other",
                    title="Other",
                    status="needs_review",
                ),
            ]
        )
        db.commit()

        member = _metrics(db, "org", viewer_user_id="owner")
        assert member["pending_decisions"] == 1
        assert member["pending_actions"] == 1
        assert [row["title"] for row in member["recent_decisions"]] == [
            "Pending decision",
            "Approved decision",
        ]
        assert member["connectors_connected"] == 1
        assert [(row["key"], row["auth_state"]) for row in member["connector_statuses"]] == [
            ("notion", "connected")
        ]
        assert member["documents_by_connector"] == {"stale_source": 1}

        admin = _metrics(db, "org", viewer_user_id="owner", viewer_is_admin=True)
        assert admin["pending_actions"] == 2
    finally:
        db.close()
        engine.dispose()
