"""Slack as an Ask client: a /ask slash command backed by a tokened URL.

Setup: an org admin mints a token (Settings), then points a Slack slash
command's Request URL at /slack/ask/<token>. Slack requires an ack within
3 seconds, so the answer is computed in the background and posted to the
command's response_url. Answers run in system context scoped to org-visible
content only (no user impersonation from Slack identities).
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from typing import Annotated

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException
from sqlalchemy.orm import Session

from db.models import Org
from db.session import get_db, get_org_id, require_writable_org

logger = logging.getLogger("osai.slack_ask")

router = APIRouter(tags=["slack"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]
# Writes must never come from the anonymous demo workspace (SEC-003).
WriteOrgId = Annotated[str, Depends(require_writable_org)]


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.post("/settings/slack-ask-token")
async def mint_slack_ask_token(db: DbSession, org_id: WriteOrgId) -> dict:
    """Mint (or rotate) the org's Slack /ask token. Plaintext returned once."""
    org = db.get(Org, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Org not found.")
    token = f"osas_{secrets.token_urlsafe(32)}"
    org.slack_ask_token_hash = _hash(token)
    db.commit()
    return {
        "token": token,
        "request_url_path": f"/slack/ask/{token}",
        "note": "Point your Slack slash command's Request URL here. Shown once.",
    }


@router.delete("/settings/slack-ask-token")
async def revoke_slack_ask_token(db: DbSession, org_id: WriteOrgId) -> dict:
    org = db.get(Org, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Org not found.")
    org.slack_ask_token_hash = None
    db.commit()
    return {"revoked": True}


async def _answer_to_slack(org_id: str, question: str, response_url: str) -> None:
    """Compute the answer and post it back to Slack's response_url."""
    try:
        from agent.orchestrator import run_ask
        from api.schemas.agent import AskRequest

        res = await run_ask(AskRequest(org_id=org_id, question=question))
        answer = res.answer.strip() or "I couldn't find an answer."
        titles = ", ".join(c.source_record_title for c in res.citations[:3])
        if titles:
            answer += f"\n_Sources: {titles}_"
    except Exception as exc:  # noqa: BLE001 — always answer Slack, even on failure
        logger.warning("slack ask failed (org=%s): %s", org_id, exc)
        answer = "Something went wrong answering that — try again in OSAI."
    try:
        httpx.post(
            response_url,
            json={"response_type": "in_channel", "text": answer[:3500]},
            timeout=10.0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("slack response_url post failed: %s", exc)


# NOTE: no org-auth dependency — the URL token authenticates the workspace.
@router.post("/slack/ask/{token}")
async def slack_ask(
    token: str,
    background: BackgroundTasks,
    db: DbSession,
    text: Annotated[str, Form()] = "",
    response_url: Annotated[str, Form()] = "",
) -> dict:
    org = (
        db.query(Org).filter(Org.slack_ask_token_hash == _hash(token)).first()
        if token
        else None
    )
    if org is None:
        raise HTTPException(status_code=401, detail="Invalid Slack ask token.")
    question = text.strip()
    if not question:
        return {
            "response_type": "ephemeral",
            "text": "Ask me something, e.g. `/ask who owns infra?`",
        }
    if response_url:
        background.add_task(_answer_to_slack, org.id, question, response_url)
        return {
            "response_type": "ephemeral",
            "text": f"Looking into “{question}” — answer coming right up.",
        }
    # No response_url (e.g. curl smoke test): answer inline, best-effort.
    await _answer_to_slack(org.id, question, response_url="http://invalid.invalid")
    return {"response_type": "ephemeral", "text": "Answered (no response_url provided)."}
