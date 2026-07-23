"""Auth endpoints — email lookup (demo) + real Google OAuth sign-in."""

from __future__ import annotations

import logging
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import parse_qsl, urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from jwt import PyJWKClient
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.ratelimit import rate_limit
from config import settings
from db.models import Org, User, normalize_email
from db.repositories import (
    AmbiguousUserEmailError,
    accept_invite_by_token,
    delete_member,
    find_user_by_email,
    provision_org,
    try_db,
)
from db.session import (
    SESSION_COOKIE,
    _decode_jwt,
    assert_writable_org,
    get_claims,
    get_db,
    require_writable_org,
)

router = APIRouter(prefix="/auth", tags=["auth"])
DbSession = Annotated[Session, Depends(get_db)]
logger = logging.getLogger("osai.auth")


def _set_session_cookie(response: Response, token: str) -> None:
    """Store the session JWT in an httpOnly cookie. SameSite=Lax + first-party
    (the frontend talks to the API through its own /api proxy) is CSRF-safe for
    state-changing requests without a separate CSRF token. Secure everywhere but
    local http."""
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.jwt_expiry_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.env != "local",
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        secure=settings.env != "local",
        httponly=True,
        samesite="lax",
    )

# Google OIDC endpoints.
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
_OAUTH_STATE_COOKIE = "osai_oauth_state"
_OAUTH_STATE_AUDIENCE = "osai-google-callback"
_OAUTH_STATE_ISSUER = "osai"
_OAUTH_STATE_PURPOSE = "google-sign-in"
_OAUTH_STATE_TTL_SECONDS = 10 * 60
_INVITE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,256}$")
_OAUTH_START_FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"
_OAUTH_START_MAX_BODY_BYTES = 512


class LoginRequest(BaseModel):
    email: str


class LoginResponse(BaseModel):
    user_id: str
    org_id: str
    role: str
    token: str


def _issue_token(user: User) -> str:
    """Signed session JWT carrying the user's identity, org and role."""
    now = datetime.now(UTC)
    payload = {
        "sub": user.id,
        "org_id": user.org_id,
        "role": user.role,
        "email": user.email,
        # Token generation — bumping user.token_version invalidates this token.
        "tv": user.token_version or 0,
        "iat": now,
        "exp": now + timedelta(hours=settings.jwt_expiry_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


@router.post(
    "/login",
    response_model=LoginResponse,
    dependencies=[Depends(rate_limit(max_calls=10, window_seconds=300))],
)
async def login(body: LoginRequest, db: DbSession, response: Response) -> LoginResponse:
    """Password-less email-lookup sign-in (dev/demo only). Disabled outside local
    unless explicitly enabled; production sign-in goes through Google OAuth."""
    if not settings.email_login_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email/password sign-in is disabled. Please sign in with Google.",
        )
    try:
        user = find_user_by_email(db, body.email)
    except AmbiguousUserEmailError:
        logger.error("refused login for an ambiguous normalized user email")
        user = None
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    token = _issue_token(user)
    # Set the httpOnly session cookie (primary auth). The token is also returned
    # in the body for API clients; the browser relies on the cookie.
    _set_session_cookie(response, token)
    return LoginResponse(user_id=user.id, org_id=user.org_id, role=user.role, token=token)


class SessionExchange(BaseModel):
    token: str


@router.post("/session")
async def set_session(body: SessionExchange, response: Response) -> dict:
    """Exchange a valid JWT for an httpOnly session cookie on this (frontend)
    origin. The Google OAuth callback runs on the API domain, so the browser
    receives the token in the redirect fragment and posts it here — through the
    same-origin /api proxy — to land the cookie first-party where the app runs."""
    if _decode_jwt(body.token) is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    _set_session_cookie(response, body.token)
    return {"ok": True}


@router.get("/session")
async def get_session(
    claims: Annotated[dict, Depends(get_claims)], db: DbSession
) -> dict:
    """Who this session belongs to and what it may do (SHE-6 P0 introspection).

    The session cookie is httpOnly, so the browser cannot read its own identity
    out of it — this is how the client learns who it is and which surfaces to
    offer (e.g. admin-only Data sources) instead of guessing and rendering a 403.

    Answered from the database rather than the JWT: the token carries a role
    snapshot from up to 30 days ago, so a demotion must take effect now, not when
    the token expires. Authorization itself is still enforced per-route; this is
    for honest UI, never a substitute for the server-side gate. Revocation is
    already applied by get_claims.
    """
    user = db.get(User, claims.get("sub"))
    if user is None:
        # The token verifies but the account is gone — fail closed.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Account not found."
        )
    org = db.get(Org, user.org_id)
    return {
        "user_id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "org_id": user.org_id,
        "org_name": org.name if org else None,
        "role": user.role,
        "is_admin": user.role == "admin",
        "data_tier": user.data_tier,
        "permissions": list(user.permissions or []),
        "department_id": user.department_id,
    }


@router.post("/logout")
async def logout(response: Response) -> dict:
    """Clear this device's session cookie. (Use /auth/logout-all to revoke every
    session.) The client cannot clear an httpOnly cookie itself, so it asks the
    server to."""
    _clear_session_cookie(response)
    return {"ok": True}


@router.get("/config")
async def auth_config() -> dict[str, bool]:
    """Tell the frontend which auth methods are available on this deployment."""
    return {
        "google_enabled": settings.google_oauth_enabled,
        "email_login_enabled": bool(settings.email_login_enabled),
    }


def _issue_google_oauth_state(invite_token: str | None) -> tuple[str, str]:
    """Return the public OAuth nonce and a signed, httpOnly binding cookie."""
    nonce = secrets.token_urlsafe(24)
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "iss": _OAUTH_STATE_ISSUER,
        "aud": _OAUTH_STATE_AUDIENCE,
        "purpose": _OAUTH_STATE_PURPOSE,
        "nonce": nonce,
        "iat": now,
        "exp": now + timedelta(seconds=_OAUTH_STATE_TTL_SECONDS),
    }
    if invite_token:
        payload["invite_token"] = invite_token
    cookie = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    return nonce, cookie


def _decode_google_oauth_state(cookie: str | None) -> dict:
    try:
        payload = jwt.decode(
            cookie or "",
            settings.jwt_secret,
            algorithms=["HS256"],
            audience=_OAUTH_STATE_AUDIENCE,
            issuer=_OAUTH_STATE_ISSUER,
            options={"require": ["purpose", "nonce", "iat", "exp"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=400, detail="Invalid OAuth state.") from exc
    if payload.get("purpose") != _OAUTH_STATE_PURPOSE or not isinstance(
        payload.get("nonce"), str
    ):
        raise HTTPException(status_code=400, detail="Invalid OAuth state.")
    invite_token = payload.get("invite_token")
    if invite_token is not None and (
        not isinstance(invite_token, str) or not _INVITE_TOKEN_RE.fullmatch(invite_token)
    ):
        raise HTTPException(status_code=400, detail="Invalid OAuth state.")
    return payload


def _google_start_response(
    invite_token: str | None = None,
    *,
    redirect_status: int = status.HTTP_307_TEMPORARY_REDIRECT,
) -> RedirectResponse:
    """Kick off the Google OAuth flow — redirect the browser to Google's consent screen."""
    if not settings.google_oauth_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in is not configured on this server.",
        )

    if invite_token and not _INVITE_TOKEN_RE.fullmatch(invite_token):
        raise HTTPException(status_code=400, detail="Invalid invitation link.")
    state, state_cookie = _issue_google_oauth_state(invite_token)
    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    resp = RedirectResponse(
        f"{GOOGLE_AUTH_URL}?{urlencode(params)}",
        status_code=redirect_status,
    )
    # CSRF guard: state is echoed back by Google and must match the cookie.
    resp.set_cookie(
        _OAUTH_STATE_COOKIE,
        state_cookie,
        max_age=_OAUTH_STATE_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.env != "local",
    )
    return resp


async def _read_invite_start_form(request: Request) -> str:
    """Read one small, strict URL-encoded ``invite`` field from the request."""
    media_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
    if media_type != _OAUTH_START_FORM_CONTENT_TYPE:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="OAuth invitation start requires a URL-encoded form.",
        )

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid form body.") from exc
        if declared_length < 0:
            raise HTTPException(status_code=400, detail="Invalid form body.")
        if declared_length > _OAUTH_START_MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Form body is too large.")

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > _OAUTH_START_MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Form body is too large.")

    try:
        encoded = bytes(body).decode("ascii")
        fields = parse_qsl(
            encoded,
            keep_blank_values=True,
            strict_parsing=True,
            encoding="utf-8",
            errors="strict",
            max_num_fields=1,
        )
    except (UnicodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid form body.") from exc

    if len(fields) != 1 or fields[0][0] != "invite":
        raise HTTPException(status_code=400, detail="Invalid form body.")
    invite_token = fields[0][1]
    if not _INVITE_TOKEN_RE.fullmatch(invite_token):
        raise HTTPException(status_code=400, detail="Invalid invitation link.")
    return invite_token


@router.get("/google/start")
async def google_start(request: Request) -> RedirectResponse:
    """Start ordinary Google sign-in without invitation data in the URL."""
    if request.url.query:
        raise HTTPException(status_code=400, detail="OAuth start does not accept query data.")
    return _google_start_response()


@router.post("/google/start")
async def google_invite_start(request: Request) -> RedirectResponse:
    """Start invited Google sign-in with the opaque token in the form body."""
    if request.url.query:
        raise HTTPException(status_code=400, detail="OAuth start does not accept query data.")
    invite_token = await _read_invite_start_form(request)
    # 303 is mandatory here: 307 would forward the POST body (and invite token)
    # to Google's authorization endpoint instead of following with a clean GET.
    return _google_start_response(
        invite_token, redirect_status=status.HTTP_303_SEE_OTHER
    )


async def _exchange_code(code: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "redirect_uri": settings.google_oauth_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    if token_resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to exchange authorization code with Google.",
        )
    return token_resp.json()


def _verify_id_token(id_token: str) -> dict:
    """Verify Google's id_token signature, audience and issuer; return claims."""
    try:
        signing_key = PyJWKClient(GOOGLE_JWKS_URL).get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.google_oauth_client_id,
        )
    except Exception as exc:  # noqa: BLE001 — surface any verification failure as 401
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not verify Google identity token.",
        ) from exc

    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unexpected token issuer.",
        )
    if not claims.get("email_verified", False):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google account email is not verified.",
        )
    return claims


def _frontend_redirect(
    token: str, user: User, org_name: str, *, is_new: bool
) -> RedirectResponse:
    base = settings.frontend_redirect.rstrip("/")
    # Token is passed in the URL fragment so it never hits server access logs.
    fragment = urlencode(
        {
            "token": token,
            "org_id": user.org_id,
            "org_name": org_name,
            "user_id": user.id,
            "email": user.email,
            "name": user.display_name,
            "new": "1" if is_new else "0",
        }
    )
    return RedirectResponse(f"{base}/auth/callback#{fragment}")


@router.get("/google/callback")
async def google_callback(
    request: Request,
    db: DbSession,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> Response:
    """Handle Google's redirect: verify identity, find/create the user, hand back a session."""
    if not settings.google_oauth_enabled:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured.")
    if error:
        raise HTTPException(status_code=400, detail=f"Google sign-in failed: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code.")

    state_payload = _decode_google_oauth_state(request.cookies.get(_OAUTH_STATE_COOKIE))
    cookie_nonce = state_payload["nonce"]
    if not state or not secrets.compare_digest(state, cookie_nonce):
        raise HTTPException(status_code=400, detail="Invalid OAuth state.")
    invite_token = state_payload.get("invite_token")

    tokens = await _exchange_code(code)
    id_token = tokens.get("id_token")
    if not id_token:
        raise HTTPException(status_code=400, detail="Google did not return an identity token.")

    claims = _verify_id_token(id_token)
    email_claim = claims.get("email")
    if not email_claim:
        raise HTTPException(status_code=400, detail="Google identity has no email.")
    email = normalize_email(str(email_claim))
    display_name = claims.get("name") or email.split("@")[0]

    try:
        user = find_user_by_email(db, email)
    except AmbiguousUserEmailError as exc:
        logger.error("refused Google sign-in for an ambiguous normalized user email")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Account identity is ambiguous. Contact an administrator.",
        ) from exc
    # First-ever sign-in (whether brand-new org owner OR an invited teammate
    # joining) → send them to onboarding so they connect their tools.
    is_new = user is None
    if invite_token and user is not None:
        raise HTTPException(
            status_code=409,
            detail="This invitation cannot be accepted by an existing account.",
        )
    if user is None:
        if invite_token:
            # Possession of this exact link selects one invite. A different,
            # newer invite for the same email must never redirect the user into
            # another workspace.
            user = accept_invite_by_token(db, invite_token, email, display_name)
            if user is None:
                raise HTTPException(
                    status_code=400,
                    detail="Invitation is invalid, expired, revoked, or already used.",
                )
        else:
            # Ordinary first sign-in, with no invite link, creates a workspace.
            org_name = f"{display_name}'s workspace"
            _, user = try_db(
                "provision_org_google",
                (None, None),
                lambda: provision_org(
                    db, name=org_name, admin_email=email, admin_name=display_name
                ),
            )
            if user is None:
                raise HTTPException(status_code=500, detail="Could not provision a workspace.")
            db.commit()

    org = db.get(Org, user.org_id)
    token = _issue_token(user)
    resp = _frontend_redirect(token, user, org.name if org else "", is_new=is_new)
    # Set the cookie on the API domain too (covers same-origin deployments). For
    # the split frontend/API domain, the callback page re-posts the fragment
    # token to /api/auth/session to land the cookie first-party (see set_session).
    _set_session_cookie(resp, token)
    resp.delete_cookie(_OAUTH_STATE_COOKIE)
    return resp


Claims = Annotated[dict, Depends(get_claims)]
WriteOrgId = Annotated[str, Depends(require_writable_org)]


@router.delete("/account")
async def delete_account(_org_id: WriteOrgId, claims: Claims, db: DbSession) -> dict:
    """Permanently delete the signed-in user's account. Requires a valid session.

    Deletes the user record only; the org and its data are left intact — which is
    only safe while someone can still administer it, hence the last-admin guard.
    The client should clear its session after this.
    """
    user = db.get(User, claims.get("sub"))
    if user is None:
        raise HTTPException(status_code=404, detail="Account not found.")
    assert_writable_org(user.org_id)
    # Reuse the serialized team deletion path so self-deletion cannot race a
    # concurrent demotion/removal and strand the workspace without an admin.
    try:
        delete_member(db, user.id, user.org_id, actor=user.id)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        if exc.status_code == 409 and detail.get("code") in {
            "member_transfer_required",
            "member_removal_blocked",
        }:
            raise HTTPException(
                status_code=409,
                detail=(
                    "This account still owns workspace data. Ask another workspace "
                    "admin to transfer or resolve it from Team before deleting your account."
                ),
            ) from exc
        raise
    return {"deleted": True}


@router.post("/logout-all")
async def logout_all(
    _org_id: WriteOrgId, claims: Claims, db: DbSession, response: Response
) -> dict:
    """Revoke every outstanding session for the signed-in user by bumping their
    token generation. All previously issued JWTs (including the one making this
    call) stop being accepted; the client should re-authenticate (SEC-002)."""
    user = db.get(User, claims.get("sub"))
    if user is None:
        raise HTTPException(status_code=404, detail="Account not found.")
    assert_writable_org(user.org_id)
    user.token_version = (user.token_version or 0) + 1
    db.commit()
    # The token generation change revokes every session, including this one.
    # Expire the current browser's now-useless cookie too so logout-all does not
    # leave stale credentials attached to later requests.
    _clear_session_cookie(response)
    return {"revoked": True, "token_version": user.token_version}
