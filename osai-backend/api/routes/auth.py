"""Auth endpoints — email lookup (demo) + real Google OAuth sign-in."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from jwt import PyJWKClient
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from db.models import Org, User
from db.repositories import accept_invite_for_email, provision_org, try_db
from db.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])
DbSession = Annotated[Session, Depends(get_db)]

# Google OIDC endpoints.
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
_OAUTH_STATE_COOKIE = "osai_oauth_state"


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
        "iat": now,
        "exp": now + timedelta(hours=settings.jwt_expiry_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: DbSession) -> LoginResponse:
    """Simulate a password-free lookup authentication returning a mock JWT token."""
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    return LoginResponse(
        user_id=user.id,
        org_id=user.org_id,
        role=user.role,
        token=_issue_token(user),
    )


@router.get("/config")
async def auth_config() -> dict[str, bool]:
    """Tell the frontend which auth methods are available on this deployment."""
    return {"google_enabled": settings.google_oauth_enabled}


@router.get("/google/start")
async def google_start() -> RedirectResponse:
    """Kick off the Google OAuth flow — redirect the browser to Google's consent screen."""
    if not settings.google_oauth_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in is not configured on this server.",
        )

    state = secrets.token_urlsafe(24)
    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    resp = RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")
    # CSRF guard: state is echoed back by Google and must match the cookie.
    resp.set_cookie(
        _OAUTH_STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=settings.env != "local",
    )
    return resp


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

    cookie_state = request.cookies.get(_OAUTH_STATE_COOKIE)
    if not state or not cookie_state or not secrets.compare_digest(state, cookie_state):
        raise HTTPException(status_code=400, detail="Invalid OAuth state.")

    tokens = await _exchange_code(code)
    id_token = tokens.get("id_token")
    if not id_token:
        raise HTTPException(status_code=400, detail="Google did not return an identity token.")

    claims = _verify_id_token(id_token)
    email = claims.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Google identity has no email.")
    display_name = claims.get("name") or email.split("@")[0]

    user = db.scalar(select(User).where(User.email == email))
    # First-ever sign-in (whether brand-new org owner OR an invited teammate
    # joining) → send them to onboarding so they connect their tools.
    is_new = user is None
    if user is None:
        # If an admin invited this email, join that existing org with the assigned
        # role/department — so a team lands in one workspace.
        user = accept_invite_for_email(db, email, display_name)
        if user is None:
            # No invite: this is a brand-new org owner (e.g. the first admin).
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
    resp = _frontend_redirect(
        _issue_token(user), user, org.name if org else "", is_new=is_new
    )
    resp.delete_cookie(_OAUTH_STATE_COOKIE)
    return resp
