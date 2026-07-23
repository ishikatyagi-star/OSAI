from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

import api.routes.workflows as workflow_routes
from api.main import app
from api.routes.automations import (
    MAX_AUTOMATION_NAME_CHARS,
    MAX_AUTOMATION_PROMPT_CHARS,
    MAX_DELIVERY_TARGET_CHARS,
    AutomationCreate,
)
from api.schemas.workflow_run import WorkflowRunCreate, WorkflowRunResponse

client = TestClient(app)


def test_workflow_input_accepts_realistic_maximum_and_rejects_blank_or_oversized() -> None:
    assert len(WorkflowRunCreate(input_text="x" * 100_000).input_text) == 100_000

    for invalid in ("   \n\t", "x" * 100_001):
        with pytest.raises(ValidationError):
            WorkflowRunCreate(input_text=invalid)

    assert client.post("/workflows", json={"input_text": "   \n"}).status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "x" * (MAX_AUTOMATION_NAME_CHARS + 1), "prompt": "p"},
        {"name": "n", "prompt": "x" * (MAX_AUTOMATION_PROMPT_CHARS + 1)},
        {"name": "n", "prompt": "p", "cadence": "x" * 17},
        {"name": "n", "prompt": "p", "status": "x" * 17},
        {
            "name": "n",
            "prompt": "p",
            "deliver_to": {"channel": "slack", "target": "x" * (MAX_DELIVERY_TARGET_CHARS + 1)},
        },
        {
            "name": "n",
            "prompt": "p",
            "deliver_to": {"channel": {"nested": "slack"}, "target": "#general"},
        },
        {
            "name": "n",
            "prompt": "p",
            "deliver_to": {"channel": "slack", "target": "#general", "nested": {}},
        },
    ],
)
def test_automation_create_rejects_unbounded_or_nested_fields(payload: dict) -> None:
    response = client.post("/automations", json=payload)
    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "x" * (MAX_AUTOMATION_NAME_CHARS + 1)},
        {"prompt": "x" * (MAX_AUTOMATION_PROMPT_CHARS + 1)},
        {"cadence": "x" * 17},
        {"status": "x" * 17},
        {"deliver_to": {"channel": "slack", "target": ["#general"]}},
        {"deliver_to": {"channel": "slack", "target": "#general", "extra": "no"}},
    ],
)
def test_automation_update_rejects_unbounded_or_nested_fields(payload: dict) -> None:
    response = client.patch("/automations/not-used", json=payload)
    assert response.status_code == 422


def test_automation_create_rejects_invalid_status_instead_of_silently_activating() -> None:
    response = client.post(
        "/automations",
        json={"name": "Digest", "prompt": "Summarize", "status": "unexpected"},
    )
    assert response.status_code == 400
    assert "status must be one of" in response.json()["detail"]


def test_delivery_target_requires_exact_complete_shape() -> None:
    assert AutomationCreate(name="Digest", prompt="Summarize", deliver_to={}).deliver_to is not None

    response = client.post(
        "/automations",
        json={"name": "Digest", "prompt": "Summarize", "deliver_to": {"channel": "slack"}},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Delivery target is required."


def _raise_private_database_error(*_args, **_kwargs):
    raise SQLAlchemyError("postgresql://private-user:private-password@internal-db/workflows")


def _assert_generic_database_error(response) -> None:
    assert response.status_code == 503
    assert response.json() == {
        "detail": "Workflow data is temporarily unavailable. Please try again."
    }
    assert "private-password" not in response.text
    assert "internal-db" not in response.text


def test_workflow_list_and_detail_report_database_outages(monkeypatch) -> None:
    monkeypatch.setattr(
        workflow_routes,
        "list_visible_workflow_runs",
        _raise_private_database_error,
    )
    _assert_generic_database_error(client.get("/workflows"))

    monkeypatch.setattr(workflow_routes, "get_workflow_run", _raise_private_database_error)
    _assert_generic_database_error(client.get("/workflows/workflow-private"))


async def test_workflow_create_fails_when_result_cannot_be_persisted(monkeypatch) -> None:
    async def _run(*, run_id: str, **_kwargs) -> WorkflowRunResponse:
        return WorkflowRunResponse(
            id=run_id,
            status="needs_review",
            model_route="test",
        )

    monkeypatch.setattr(workflow_routes, "run_action_item_workflow", _run)
    monkeypatch.setattr(workflow_routes, "save_workflow_run", _raise_private_database_error)

    response = client.post(
        "/workflows",
        json={"input_text": "Priya will follow up tomorrow.", "destination": "manual"},
    )
    _assert_generic_database_error(response)
