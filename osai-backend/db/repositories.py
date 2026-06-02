from collections.abc import Sequence

from sqlalchemy import desc, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from connectors.registry import connector_registry
from db.models import (
    ActionItemRecord,
    AuditEvent,
    ConnectorAccount,
    ConnectorAction,
    ConnectorRecord,
    ModelCall,
    Org,
    SyncRun,
    User,
    WorkflowRun,
    now_utc,
)


def seed_demo_data(session: Session, org_id: str = "demo-org") -> None:
    org = session.get(Org, org_id)
    if org is None:
        session.add(
            Org(
                id=org_id,
                name="OSAI Demo Org",
                data_routing={
                    "normal": {"cloud_allowed": True},
                    "amber": {"cloud_allowed": True, "requires_citations": True},
                    "red": {"cloud_allowed": False},
                },
            )
        )

    admin = session.scalar(select(User).where(User.email == "admin@osai.local"))
    if admin is None:
        session.add(
            User(
                org_id=org_id,
                email="admin@osai.local",
                display_name="OSAI Admin",
                permissions=["org:admin", "source:all"],
            )
        )

    for connector in connector_registry.all():
        record = session.get(ConnectorRecord, connector.key)
        if record is None:
            session.add(
                ConnectorRecord(
                    key=connector.key,
                    display_name=connector.display_name,
                    capabilities=sorted(connector.capabilities),
                )
            )

        account = session.scalar(
            select(ConnectorAccount).where(
                ConnectorAccount.org_id == org_id,
                ConnectorAccount.connector_key == connector.key,
            )
        )
        if account is None:
            session.add(ConnectorAccount(org_id=org_id, connector_key=connector.key))

    session.add(
        AuditEvent(
            org_id=org_id,
            event_type="seed.demo_data",
            actor="system",
            payload={"connectors": [connector.key for connector in connector_registry.all()]},
        )
    )
    session.commit()


def list_integrations(session: Session, org_id: str) -> list[dict[str, object]]:
    rows = session.execute(
        select(ConnectorRecord, ConnectorAccount)
        .join(
            ConnectorAccount,
            (ConnectorAccount.connector_key == ConnectorRecord.key)
            & (ConnectorAccount.org_id == org_id),
            isouter=True,
        )
        .order_by(ConnectorRecord.display_name)
    ).all()
    return [
        {
            "key": connector.key,
            "display_name": connector.display_name,
            "capabilities": connector.capabilities,
            "auth_state": account.auth_state if account else "not_configured",
            "scopes": account.scopes if account else [],
            "last_sync": (
                account.last_sync_at.isoformat() if account and account.last_sync_at else None
            ),
            "sync_error": account.last_error if account else None,
        }
        for connector, account in rows
    ]


def list_sync_runs(session: Session, org_id: str, limit: int = 50) -> Sequence[SyncRun]:
    return session.scalars(
        select(SyncRun)
        .where(SyncRun.org_id == org_id)
        .order_by(desc(SyncRun.started_at))
        .limit(limit)
    ).all()


def list_workflow_runs(session: Session, org_id: str, limit: int = 50) -> Sequence[WorkflowRun]:
    return session.scalars(
        select(WorkflowRun)
        .where(WorkflowRun.org_id == org_id)
        .order_by(desc(WorkflowRun.created_at))
        .limit(limit)
    ).all()


def get_workflow_run(session: Session, workflow_id: str) -> WorkflowRun | None:
    return session.get(WorkflowRun, workflow_id)


def list_action_items(session: Session, workflow_run_id: str) -> Sequence[ActionItemRecord]:
    return session.scalars(
        select(ActionItemRecord).where(ActionItemRecord.workflow_run_id == workflow_run_id)
    ).all()


def record_workflow_run(
    session: Session,
    *,
    run_id: str,
    org_id: str,
    input_text: str,
    destination: str,
    data_tier: str,
    status: str,
    model_route: str,
    action_items: list[dict[str, object]],
) -> None:
    workflow_run = WorkflowRun(
        id=run_id,
        org_id=org_id,
        kind="meeting_action_items",
        status=status,
        input_text=input_text,
        destination=destination,
        data_tier=data_tier,
        model_route=model_route,
    )
    session.add(workflow_run)
    session.add(
        ModelCall(
            org_id=org_id,
            workflow_run_id=run_id,
            provider=model_route.split(":", 1)[-1],
            model="configured-later",
            prompt_version="action_item_extraction.v1",
            schema_version="action_item.v1",
            data_tier=data_tier,
            trace_id=run_id,
        )
    )
    for item in action_items:
        session.add(
            ActionItemRecord(
                workflow_run_id=run_id,
                title=str(item["title"]),
                owner=item.get("owner"),
                due_date=None,
                destination=str(item.get("destination") or destination),
                source_quote=item.get("source_quote"),
                confidence=int(float(item.get("confidence") or 0) * 100),
            )
        )
    session.add(
        ConnectorAction(
            org_id=org_id,
            connector_key=destination if destination != "manual" else "notion",
            workflow_run_id=run_id,
            action_type="create_or_update_task",
            status="skipped",
            payload={"reason": "action preview only until connector credentials are configured"},
        )
    )
    session.add(
        AuditEvent(
            org_id=org_id,
            event_type="workflow.created",
            actor="api",
            payload={
                "workflow_run_id": run_id,
                "status": status,
                "action_item_count": len(action_items),
                "recorded_at": now_utc().isoformat(),
            },
        )
    )
    session.commit()


def try_db[T](_operation: str, fallback: T, fn) -> T:
    try:
        return fn()
    except SQLAlchemyError:
        return fallback
