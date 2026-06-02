from api.schemas.workflow_run import WorkflowRunCreate
from workflows.runner import run_action_item_workflow


async def test_workflow_returns_valid_action_item_shape() -> None:
    response = await run_action_item_workflow(
        "workflow-test",
        WorkflowRunCreate(
            org_id="demo-org",
            input_text="Priya will follow up with Freshdesk on the ACME renewal by Friday.",
            destination="freshdesk",
        ),
    )
    assert response.status == "needs_review"
    assert response.model_route == "action_extraction:cloud-default"
    assert response.action_items[0].destination == "freshdesk"
