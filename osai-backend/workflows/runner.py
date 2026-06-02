from api.schemas.workflow_run import ActionItem, WorkflowRunCreate, WorkflowRunResponse
from llm.router import model_router


async def run_action_item_workflow(
    run_id: str, request: WorkflowRunCreate
) -> WorkflowRunResponse:
    route = model_router.route("action_extraction", request.data_tier)
    action_items = _extract_stub_action_items(request.input_text, request.destination)
    return WorkflowRunResponse(
        id=run_id,
        status="needs_review" if action_items else "failed",
        model_route=route.name,
        action_items=action_items,
        audit_event_ids=[f"audit:{run_id}:created"],
    )


def _extract_stub_action_items(input_text: str, destination: str) -> list[ActionItem]:
    lines = [line.strip().lstrip("-*").strip() for line in input_text.splitlines() if line.strip()]
    candidate = next((line for line in lines if len(line) > 10), None)
    if not candidate:
        return []
    return [
        ActionItem(
            title=candidate[:120],
            destination=destination,
            source_quote=candidate,
            confidence=0.35,
        )
    ]
