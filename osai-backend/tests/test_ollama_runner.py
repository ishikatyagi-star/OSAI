"""Tests for local Ollama workflow routing and Celery task retry configurations."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from api.schemas.workflow_run import WorkflowRunCreate
from config import settings
from llm.policy import DEFAULT_DATA_ROUTING
from workers.tasks.extract import extract_action_items
from workflows.runner import run_action_item_workflow


def test_celery_tasks_retry_attributes() -> None:
    # Verify extract_action_items retry attributes
    assert extract_action_items.autoretry_for == (httpx.HTTPError, RuntimeError)
    assert extract_action_items.max_retries == 3
    assert extract_action_items.default_retry_delay == 5
    assert extract_action_items.retry_backoff is True


@pytest.mark.asyncio
async def test_workflows_runner_routes_red_tier_to_ollama() -> None:
    req = WorkflowRunCreate(
        org_id="demo-org",
        input_text="Anish: I will write the Zoom webhook endpoint by next Tuesday.",
        destination="manual",
        data_tier="red",  # Triggers local Ollama routing
    )

    mock_ollama_response = {
        "message": {
            "content": (
                '{"items": [{"title": "Write Zoom webhook endpoint", '
                '"owner": "Anish", "due_date": "2026-06-09", "destination": "manual", '
                '"source_quote": "Anish: I will write...", "confidence": 0.95}]}'
            ),
        },
    }

    # Mock context retrieval and httpx POST call to local Ollama API
    with (
        patch("workflows.enricher.get_workflow_context_async") as mock_ctx,
        patch("workflows.runner.load_data_routing", return_value=DEFAULT_DATA_ROUTING),
        patch("httpx.AsyncClient.post") as mock_post,
    ):
        mock_ctx.return_value = {"documents": [], "action_items": []}

        # Mock response from Ollama API
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_ollama_response
        mock_post.return_value = mock_response

        # Execute
        response = await run_action_item_workflow(run_id="run-ollama-1", request=req, db=None)

        # Assert correct routing to Ollama
        assert response.status == "needs_review"
        assert "ollama" in response.model_route
        assert len(response.action_items) == 1
        assert response.action_items[0].title == "Write Zoom webhook endpoint"
        assert response.action_items[0].owner == "Anish"
        assert response.action_items[0].confidence == 0.95

        # Verify POST payload parameters
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == f"{settings.ollama_url}/api/chat"
        assert kwargs["json"]["model"] == settings.ollama_model
        assert kwargs["json"]["format"] == "json"
        assert kwargs["json"]["stream"] is False


@pytest.mark.asyncio
async def test_workflows_runner_ollama_error_handling() -> None:
    req = WorkflowRunCreate(
        org_id="demo-org",
        input_text="Anish: I will write the Zoom webhook endpoint by next Tuesday.",
        destination="manual",
        data_tier="red",
    )

    with (
        patch("workflows.enricher.get_workflow_context_async") as mock_ctx,
        patch("workflows.runner.load_data_routing", return_value=DEFAULT_DATA_ROUTING),
        patch("httpx.AsyncClient.post") as mock_post,
    ):
        mock_ctx.return_value = {"documents": [], "action_items": []}
        # Simulate connection error (e.g. Ollama service offline)
        mock_post.side_effect = httpx.ConnectError("Connection refused")

        response = await run_action_item_workflow(run_id="run-ollama-fail", request=req, db=None)

        # Verify task is flagged as failed with fallback audit log
        assert response.status == "failed"
        assert len(response.action_items) == 0
        assert "ollama_error" in response.audit_event_ids[0]


@pytest.mark.asyncio
async def test_restricted_context_document_never_routes_to_gemini(monkeypatch) -> None:
    req = WorkflowRunCreate(
        org_id="demo-org",
        input_text="Normal-tier meeting transcript.",
        destination="manual",
        data_tier="normal",
    )
    ollama_payload = {
        "message": {
            "content": '{"items": [{"title": "Keep locally", "destination": "manual"}]}'
        }
    }
    monkeypatch.setattr(settings, "gemini_api_key", "configured-cloud-key")

    with (
        patch("workflows.enricher.get_workflow_context_async") as mock_ctx,
        patch("workflows.runner.load_data_routing", return_value=DEFAULT_DATA_ROUTING),
        patch("httpx.AsyncClient.post") as mock_post,
        patch("llm.gemini.generate_json") as mock_gemini,
    ):
        mock_ctx.return_value = {
            "documents": [
                {
                    "title": "Restricted plan",
                    "text": "Do not send this to a cloud model.",
                    "source_type": "notion",
                    "data_tier": "amber",
                }
            ],
            "action_items": [],
        }
        mock_response = MagicMock()
        mock_response.json.return_value = ollama_payload
        mock_post.return_value = mock_response

        response = await run_action_item_workflow(
            run_id="run-restricted-context", request=req, db=None
        )

    assert response.status == "needs_review"
    assert response.model_route.startswith("ollama:")
    mock_post.assert_called_once()
    mock_gemini.assert_not_called()
