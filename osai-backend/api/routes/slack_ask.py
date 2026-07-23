"""Slack as an Ask client: a signed /ask slash-command integration.

An org admin mints a workspace URL token, then configures Slack to call
/slack/ask/<token>. Slack signs the request, the URL token selects the org, and
the Slack actor must map to an OSAI user before Ask runs with that user's grants.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.ratelimit import INTERACTIVE_AI_BUDGET, enforce_rate_limit
from config import settings
from db.models import Org, SlackRequestUse, User, normalize_email, now_utc
from db.repositories import (
    AmbiguousUserEmailError,
    find_user_by_email,
    user_clearance,
    user_permissions,
)
from db.session import (
    SessionLocal,
    assert_writable_org,
    get_db,
    get_org_id,
    require_admin,
    require_writable_org,
)

logger = logging.getLogger("osai.slack_ask")

router = APIRouter(tags=["slack"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]
# Writes must never come from the anonymous demo workspace (SEC-003).
WriteOrgId = Annotated[str, Depends(require_writable_org)]
AdminClaims = Annotated[dict, Depends(require_admin)]

_SLACK_MAX_AGE_SECONDS = 60 * 5
_SLACK_MAX_BODY_BYTES = 64 * 1024
_SLACK_RESPONSE_HOSTS = frozenset({"hooks.slack.com", "hooks.slack-gov.com"})
_SLACK_POLICY_WITHHELD = (
    "Answer withheld by the workspace data-routing policy; open Sheldon to review it."
)


@dataclass(frozen=True)
class _SlackAnswer:
    text: str
    source_tiers: list[str | None]
    # Only bounded, code-authored status messages may bypass source routing.
    # A successful Ask answer without citations is not a status message: its
    # empty source_tiers remains unknown provenance and is denied below.
    safe_system_message: bool = False


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _verify_slack_signature(raw_body: bytes, timestamp: str | None, signature: str | None) -> None:
    """Authenticate Slack's exact request bytes and reject stale requests."""
    secret = settings.slack_signing_secret
    if not secret:
        raise HTTPException(status_code=503, detail="Slack request signing is not configured.")
    timestamp_text = timestamp or ""
    try:
        issued_at = int(timestamp_text)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid Slack request signature.") from exc
    if abs(int(time.time()) - issued_at) > _SLACK_MAX_AGE_SECONDS:
        raise HTTPException(status_code=401, detail="Invalid Slack request signature.")
    base = b"v0:" + timestamp_text.encode("utf-8") + b":" + raw_body
    expected = "v0=" + hmac.new(secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid Slack request signature.")


def _claim_slack_request(db: Session, timestamp: str, raw_body: bytes) -> bool:
    """Consume a valid signed request once across workers and restarts."""
    now = now_utc()
    request_hash = hashlib.sha256(timestamp.encode("utf-8") + b":" + raw_body).hexdigest()
    db.query(SlackRequestUse).filter(SlackRequestUse.expires_at < now).delete(
        synchronize_session=False
    )
    db.add(
        SlackRequestUse(
            request_hash=request_hash,
            expires_at=datetime.fromtimestamp(int(timestamp), UTC)
            + timedelta(seconds=_SLACK_MAX_AGE_SECONDS),
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return False
    return True


async def _read_bounded_body(request: Request) -> bytes:
    """Read the signed request incrementally, stopping before unbounded buffering."""
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > _SLACK_MAX_BODY_BYTES:
                raise HTTPException(status_code=413, detail="Slack request is too large.")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header.") from exc
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > _SLACK_MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Slack request is too large.")
        chunks.append(chunk)
    return b"".join(chunks)


def _parse_slack_form(request: Request, raw_body: bytes) -> dict[str, list[str]]:
    content_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
    if content_type != "application/x-www-form-urlencoded":
        raise HTTPException(status_code=415, detail="Slack requests must be form encoded.")
    if len(raw_body) > _SLACK_MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Slack request is too large.")
    try:
        return parse_qs(raw_body.decode("utf-8"), keep_blank_values=True, max_num_fields=100)
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Malformed Slack request.") from exc


def _form_value(form: dict[str, list[str]], name: str) -> str:
    values = form.get(name, [])
    if len(values) > 1:
        raise HTTPException(status_code=422, detail=f"Duplicate Slack field: {name}.")
    return values[0] if values else ""


def _is_allowed_response_url(response_url: str) -> bool:
    """Allow only Slack's HTTPS slash-command callback endpoints."""
    try:
        parsed = urlsplit(response_url)
        port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme == "https"
        and parsed.hostname in _SLACK_RESPONSE_HOSTS
        and port in (None, 443)
        and parsed.username is None
        and parsed.password is None
        and parsed.path.startswith("/commands/")
        and not parsed.query
        and not parsed.fragment
    )


async def _slack_user_email(slack_user_id: str) -> str | None:
    """Resolve a signed Slack actor to a verified workspace email."""
    if not settings.slack_bot_token:
        raise HTTPException(status_code=503, detail="Slack user mapping is not configured.")
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
            response = await client.get(
                "https://slack.com/api/users.info",
                headers={"Authorization": f"Bearer {settings.slack_bot_token}"},
                params={"user": slack_user_id},
            )
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=502, detail="Could not verify Slack user identity."
        ) from exc
    if not body.get("ok"):
        return None
    email = (body.get("user") or {}).get("profile", {}).get("email")
    return normalize_email(str(email)) if email else None


async def _mapped_user(db: Session, org_id: str, slack_user_id: str) -> User:
    if not slack_user_id:
        raise HTTPException(status_code=403, detail="Slack user is not linked to this workspace.")
    email = await _slack_user_email(slack_user_id)
    try:
        user = find_user_by_email(db, email, org_id=org_id) if email else None
    except AmbiguousUserEmailError as exc:
        logger.error("refused ambiguous Slack user mapping (org=%s)", org_id)
        raise HTTPException(
            status_code=403,
            detail="Slack user is not linked to this workspace.",
        ) from exc
    if user is None:
        raise HTTPException(status_code=403, detail="Slack user is not linked to this workspace.")
    return user


@router.post("/settings/slack-ask-token")
async def mint_slack_ask_token(db: DbSession, org_id: WriteOrgId, _admin: AdminClaims) -> dict:
    """Mint (or rotate) the org's Slack /ask token. Plaintext returned once."""
    if not settings.slack_signing_secret or not settings.slack_bot_token:
        raise HTTPException(
            status_code=503,
            detail="Slack request signing and user mapping must be configured.",
        )
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
async def revoke_slack_ask_token(db: DbSession, org_id: WriteOrgId, _admin: AdminClaims) -> dict:
    org = db.get(Org, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Org not found.")
    org.slack_ask_token_hash = None
    db.commit()
    return {"revoked": True}


async def _build_answer(
    org_id: str,
    question: str,
    *,
    user_id: str,
    requester_permissions: list[str],
    requester_tier: str,
) -> _SlackAnswer:
    try:
        from agent.orchestrator import run_ask
        from api.schemas.agent import AskRequest

        res = await run_ask(
            AskRequest(org_id=org_id, question=question),
            requester_permissions=requester_permissions,
            requester_tier=requester_tier,
            user_id=user_id,
        )
        answer = res.answer.strip() or "I couldn't find an answer."
        titles = ", ".join(c.source_record_title for c in res.citations[:3])
        if titles:
            answer += f"\n_Sources: {titles}_"
        return _SlackAnswer(
            text=answer,
            source_tiers=[citation.data_tier for citation in res.citations],
        )
    except Exception as exc:  # noqa: BLE001 - Slack must receive a bounded failure answer
        logger.warning("slack ask failed (org=%s): %s", org_id, exc)
        return _SlackAnswer(
            text="Something went wrong answering that - try again in Sheldon.",
            source_tiers=[],
            safe_system_message=True,
        )


def _apply_slack_delivery_policy(org_id: str, answer: _SlackAnswer) -> str:
    if answer.safe_system_message:
        return answer.text
    from llm.policy import connector_egress_allowed, load_data_routing

    if connector_egress_allowed(
        load_data_routing(org_id),
        answer.source_tiers,
        "slack",
    ):
        return answer.text
    logger.warning("withheld Slack Ask answer by data-routing policy (org=%s)", org_id)
    return _SLACK_POLICY_WITHHELD


async def _answer_to_slack(
    org_id: str,
    question: str,
    response_url: str,
    *,
    slack_user_id: str,
    request_timestamp: str,
    raw_body: bytes,
) -> None:
    """Compute the permission-scoped answer and post it to a Slack-only URL."""
    if not _is_allowed_response_url(response_url):
        logger.warning("refused non-Slack response_url for org=%s", org_id)
        return
    try:
        with SessionLocal() as db:
            user = await _mapped_user(db, org_id, slack_user_id)
            if not _claim_slack_request(db, request_timestamp, raw_body):
                return
            claims = {
                "sub": user.id,
                "org_id": user.org_id,
                "tv": user.token_version or 0,
            }
            permissions = user_permissions(db, claims)
            tier = user_clearance(db, claims)
            user_id = user.id
        answer = _apply_slack_delivery_policy(
            org_id,
            await _build_answer(
                org_id,
                question,
                user_id=user_id,
                requester_permissions=permissions,
                requester_tier=tier,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - never fall through to system context
        logger.warning("slack user mapping failed (org=%s): %s", org_id, exc)
        answer = "Your Slack user is not linked to this OSAI workspace."
    try:
        httpx.post(
            response_url,
            # The answer is scoped to one mapped user's ACL and clearance. It
            # must remain private even when the slash command came from a public
            # channel; broadcasting it would bypass every document grant.
            json={"response_type": "ephemeral", "text": answer[:3500]},
            timeout=10.0,
            follow_redirects=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("slack response_url post failed: %s", exc)


# The URL token selects the org; Slack's HMAC signature authenticates the sender.
@router.post("/slack/ask/{token}")
async def slack_ask(
    token: str,
    background: BackgroundTasks,
    db: DbSession,
    request: Request,
) -> dict:
    raw_body = await _read_bounded_body(request)
    _verify_slack_signature(
        raw_body,
        request.headers.get("x-slack-request-timestamp"),
        request.headers.get("x-slack-signature"),
    )
    form = _parse_slack_form(request, raw_body)
    org = db.query(Org).filter(Org.slack_ask_token_hash == _hash(token)).first() if token else None
    if org is None:
        raise HTTPException(status_code=401, detail="Invalid Slack ask token.")
    assert_writable_org(org.id)

    question = _form_value(form, "text").strip()
    if not question:
        return {
            "response_type": "ephemeral",
            "text": "Ask me something, e.g. `/ask who owns infra?`",
        }

    response_url = _form_value(form, "response_url")
    if response_url and not _is_allowed_response_url(response_url):
        raise HTTPException(status_code=422, detail="Invalid Slack response URL.")

    await enforce_rate_limit(
        request,
        max_calls=INTERACTIVE_AI_BUDGET[0],
        window_seconds=INTERACTIVE_AI_BUDGET[1],
        verified_tenant_id=org.id,
    )

    slack_user_id = _form_value(form, "user_id")
    if response_url:
        background.add_task(
            _answer_to_slack,
            org.id,
            question,
            response_url,
            slack_user_id=slack_user_id,
            request_timestamp=request.headers["x-slack-request-timestamp"],
            raw_body=raw_body,
        )
        return {
            "response_type": "ephemeral",
            "text": f'Looking into "{question}" - answer coming right up.',
        }

    # No response_url (for example, a signed curl smoke test): answer inline.
    user = await _mapped_user(db, org.id, slack_user_id)
    if not _claim_slack_request(
        db,
        request.headers["x-slack-request-timestamp"],
        raw_body,
    ):
        return {
            "response_type": "ephemeral",
            "text": "This Slack request was already accepted.",
        }
    claims = {
        "sub": user.id,
        "org_id": user.org_id,
        "tv": user.token_version or 0,
    }
    permissions = user_permissions(db, claims)
    tier = user_clearance(db, claims)
    answer = _apply_slack_delivery_policy(
        org.id,
        await _build_answer(
            org.id,
            question,
            user_id=user.id,
            requester_permissions=permissions,
            requester_tier=tier,
        ),
    )
    return {"response_type": "ephemeral", "text": answer[:3500]}
