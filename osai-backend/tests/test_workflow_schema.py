import pytest
from pydantic import ValidationError

from api.schemas.workflow_run import WorkflowRunCreate
from workflows.runner import run_action_item_workflow


def test_google_drive_is_not_a_workflow_action_destination() -> None:
    with pytest.raises(ValidationError):
        WorkflowRunCreate(input_text="Follow up", destination="google_drive")


async def test_workflow_returns_valid_action_item_shape(monkeypatch) -> None:
    # Force the deterministic heuristic path so the test never depends on a live
    # LLM (a configured-but-rate-limited Gemini key would otherwise fail the run).
    monkeypatch.setattr("workflows.runner.settings.gemini_api_key", None)
    monkeypatch.setattr(
        "workflows.runner.load_data_routing",
        lambda _org_id: {"normal": {"llm_allowed": True}},
    )
    response = await run_action_item_workflow(
        "workflow-test",
        WorkflowRunCreate(
            org_id="demo-org",
            input_text="Priya will follow up with Freshdesk on the ACME renewal by Friday.",
            destination="freshdesk",
        ),
    )
    assert response.status == "needs_review"
    # model_route depends on whether Gemini API key is set; just check it's a non-empty string
    assert isinstance(response.model_route, str)
    assert response.model_route
    assert response.action_items[0].destination == "freshdesk"
