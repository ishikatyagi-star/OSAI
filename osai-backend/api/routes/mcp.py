"""Authenticated MCP gateway for OSAI's context and approval plane.

The gateway intentionally exposes only OSAI-owned capabilities: permissioned
retrieval, organization memory, and approval-brokered action proposals. External
agents authenticate with an existing user session token; the tenant and access
scope are always resolved from that token, never tool arguments.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from agent.orchestrator import run_ask
from api.schemas.agent import AskRequest
from api.schemas.search import SearchRequest
from db.api_keys import hash_mcp_api_key, issue_mcp_api_key
from db.models import McpApiKey, now_utc
from db.repositories import load_proposed_action, user_clearance, user_permissions
from db.session import get_claims, get_db
from memory.retriever import retrieve_answer

router = APIRouter(prefix="/mcp", tags=["mcp"])
DbSession = Annotated[Session, Depends(get_db)]
Claims = Annotated[dict, Depends(get_claims)]

_PROTOCOL_VERSION = "2025-03-26"


class McpApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)

_TOOLS = [
    {
        "name": "osai_search",
        "description": "Search organization knowledge using the caller's permissions and data clearance.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string", "minLength": 1}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True},
        "_meta": {"osai_policy": {"data_tiers": ["normal", "amber", "red"], "approval": "none"}},
    },
    {
        "name": "osai_org_memory",
        "description": "Retrieve relevant durable organization memory with the caller's access policy applied.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string", "minLength": 1}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True},
        "_meta": {"osai_policy": {"data_tiers": ["normal", "amber", "red"], "approval": "none"}},
    },
    {
        "name": "osai_propose_action",
        "description": "Ask OSAI to create an approval-gated action proposal. This tool never executes a write.",
        "inputSchema": {
            "type": "object",
            "properties": {"request": {"type": "string", "minLength": 1}},
            "required": ["request"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
        "_meta": {"osai_policy": {"data_tiers": ["normal", "amber", "red"], "approval": "required"}},
    },
    {
        "name": "osai_action_status",
        "description": "Read the status of an OSAI action proposal in the caller's organization.",
        "inputSchema": {
            "type": "object",
            "properties": {"action_id": {"type": "string", "minLength": 1}},
            "required": ["action_id"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True},
        "_meta": {"osai_policy": {"data_tiers": ["normal", "amber", "red"], "approval": "none"}},
    },
]


def _result(request_id: Any, value: dict[str, Any]) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": value})


def _error(request_id: Any, code: int, message: str, *, status_code: int = 400) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}},
        status_code=status_code,
    )


def _tool_text(value: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(value, default=str)}],
        "isError": is_error,
    }


def _serialize_api_key(key: McpApiKey) -> dict[str, Any]:
    return {
        "id": key.id,
        "name": key.name,
        "prefix": key.token_prefix,
        "created_at": key.created_at.isoformat(),
        "revoked_at": key.revoked_at.isoformat() if key.revoked_at else None,
    }


@router.get("/keys")
async def list_api_keys(db: DbSession, claims: Claims) -> list[dict[str, Any]]:
    return [
        _serialize_api_key(key)
        for key in db.query(McpApiKey)
        .filter(McpApiKey.org_id == claims["org_id"], McpApiKey.user_id == claims["sub"])
        .order_by(McpApiKey.created_at.desc())
        .all()
    ]


@router.post("/keys", status_code=201)
async def create_api_key(body: McpApiKeyCreate, db: DbSession, claims: Claims) -> dict[str, Any]:
    prefix, token = issue_mcp_api_key()
    key = McpApiKey(
        org_id=claims["org_id"],
        user_id=claims["sub"],
        name=body.name.strip(),
        token_prefix=prefix,
        token_hash=hash_mcp_api_key(token),
    )
    db.add(key)
    db.commit()
    db.refresh(key)
    return {**_serialize_api_key(key), "token": token}


@router.delete("/keys/{key_id}")
async def revoke_api_key(key_id: str, db: DbSession, claims: Claims) -> dict[str, bool]:
    key = db.get(McpApiKey, key_id)
    if key is None or key.org_id != claims["org_id"] or key.user_id != claims["sub"]:
        raise HTTPException(status_code=404, detail="MCP API key not found")
    if key.revoked_at is None:
        key.revoked_at = now_utc()
        db.commit()
    return {"revoked": True}


async def _search(
    query: str, *, org_id: str, permissions: list[str], clearance: str, memory_only: bool = False
) -> dict[str, Any]:
    request = SearchRequest(
        org_id=org_id,
        query=(f"Organization memory relevant to: {query}" if memory_only else query),
        requester_permissions=permissions,
        requester_tier=clearance,
    )
    response = await retrieve_answer(request)
    return {
        "answer": response.answer,
        "enough_context": response.enough_context,
        "citations": [citation.model_dump() for citation in response.citations],
    }


async def _call_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    org_id: str,
    user_id: str | None,
    permissions: list[str],
    clearance: str,
) -> dict[str, Any]:
    if name in {"osai_search", "osai_org_memory"}:
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise ValueError("query is required")
        result = await _search(
            query,
            org_id=org_id,
            permissions=permissions,
            clearance=clearance,
            memory_only=name == "osai_org_memory",
        )
        return _tool_text(result)

    if name == "osai_propose_action":
        request_text = str(arguments.get("request", "")).strip()
        if not request_text:
            raise ValueError("request is required")
        response = await run_ask(
            AskRequest(org_id=org_id, question=request_text),
            requester_permissions=permissions,
            requester_tier=clearance,
            user_id=user_id,
        )
        return _tool_text(
            {
                "answer": response.answer,
                "proposed_actions": [action.model_dump() for action in response.proposed_actions],
                "approval_required": bool(response.proposed_actions),
            }
        )

    if name == "osai_action_status":
        action_id = str(arguments.get("action_id", "")).strip()
        if not action_id:
            raise ValueError("action_id is required")
        action = load_proposed_action(action_id)
        if action is None or action.get("org_id") != org_id:
            raise HTTPException(status_code=404, detail="Action not found")
        return _tool_text({"action": action})

    raise LookupError(f"Unknown tool: {name}")


@router.post("")
async def mcp(payload: dict[str, Any], db: DbSession, claims: Claims) -> Response:
    """Serve the MCP JSON-RPC tools protocol over authenticated HTTP.

    A bearer token is deliberately required even for initialize: tool metadata
    reveals the product's governance capabilities and every later request needs
    the same per-user organization context.
    """
    request_id = payload.get("id")
    if payload.get("jsonrpc") != "2.0":
        return _error(request_id, -32600, "JSON-RPC 2.0 is required")

    method = payload.get("method")
    if method == "notifications/initialized":
        return Response(status_code=204)
    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "osai-policy-plane", "version": "0.1.0"},
            },
        )
    if method == "tools/list":
        return _result(request_id, {"tools": _TOOLS})
    if method != "tools/call":
        return _error(request_id, -32601, f"Method not found: {method}", status_code=404)

    params = payload.get("params") or {}
    if not isinstance(params, dict) or not isinstance(params.get("arguments", {}), dict):
        return _error(request_id, -32602, "tools/call requires an arguments object")

    org_id = claims.get("org_id")
    if not org_id:
        return _error(request_id, -32603, "Authenticated user has no organization", status_code=403)
    try:
        result = await _call_tool(
            str(params.get("name", "")),
            params.get("arguments", {}),
            org_id=org_id,
            user_id=claims.get("sub"),
            permissions=user_permissions(db, claims),
            clearance=user_clearance(db, claims),
        )
    except HTTPException as exc:
        return _error(request_id, -32001, str(exc.detail), status_code=exc.status_code)
    except (LookupError, ValueError) as exc:
        return _error(request_id, -32602, str(exc))
    except Exception:  # noqa: BLE001 - details stay in server logs, not the MCP client
        return _error(request_id, -32603, "OSAI tool invocation failed", status_code=500)
    return _result(request_id, result)
