from collections.abc import Generator
from typing import Annotated

import jwt
from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config import settings

# Name of the httpOnly session cookie. The browser sends the JWT here so it never
# needs to live in JS-readable storage (localStorage), shrinking the XSS
# token-theft blast radius (SEC-009). The Authorization header path is retained
# for API clients and tests.
SESSION_COOKIE = "osai_session"

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session]:
    with SessionLocal() as session:
        yield session


def _decode_jwt(token: str | None) -> dict | None:
    """Verify a bare session JWT; return its claims, or None if missing/invalid."""
    if not token:
        return None
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except Exception:  # noqa: BLE001 — any decode/verify failure = unauthenticated
        return None


def _decode_token(authorization: str | None) -> dict | None:
    """Verify a Bearer session JWT from an Authorization header."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return _decode_jwt(authorization.split(" ", 1)[1].strip())


def _claims_from(authorization: str | None, session_cookie: str | None) -> dict | None:
    """Resolve JWT claims from the Authorization header, falling back to the
    httpOnly session cookie. Header wins so an explicit API token overrides a
    stale browser cookie."""
    return _decode_token(authorization) or _decode_jwt(session_cookie)


async def get_optional_claims(
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict | None:
    """Return JWT claims if a valid token is present, else None (no 401). For
    endpoints that work in demo mode but want per-user context when available."""
    return _claims_from(authorization, session_cookie)


async def get_claims(
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict:
    """Require a valid session JWT and return its claims (sub, org_id, role, …)."""
    claims = _claims_from(authorization, session_cookie)
    if not claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
        )
    return claims


async def require_admin(
    claims: Annotated[dict, Depends(get_claims)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Gate an endpoint to org admins, rejecting revoked/deleted-user tokens.

    Admin routes change org-wide state, so they must honour token revocation too
    (SEC-002) — not just verify the signature and the role claim."""
    # Lazy import avoids a module-load cycle (repositories imports SessionLocal).
    from db.repositories import assert_token_current

    assert_token_current(db, claims)
    if claims.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required."
        )
    return claims


async def get_org_id(
    authorization: str | None = Header(default=None),
    x_org_id: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> str:
    """Resolve the caller's org. The org is taken from the verified JWT — never
    from a client-supplied header — so a user cannot read another org's data by
    spoofing X-Org-Id. The public demo workspace is the only header-trusted case."""
    claims = _claims_from(authorization, session_cookie)
    if claims and claims.get("org_id"):
        return claims["org_id"]
    if x_org_id == settings.default_org_id:  # public demo sample data only
        return settings.default_org_id
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
    )


async def require_writable_org(
    authorization: str | None = Header(default=None),
    x_org_id: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> str:
    """Resolve the org for a *state-changing* request, refusing the public demo
    workspace.

    The demo workspace is reached without a real session — it is trusted only via
    the X-Org-Id header (see get_org_id). Anonymous callers must therefore never
    drive writes or side effects there: mutating settings, running workflows,
    triggering syncs, executing SQL, or confirming connector actions (SEC-003).

    Outside local dev the shared demo org is read-only *even with a valid JWT*
    (e.g. a leaked/seeded demo-org token) — demo isolation is a property of the
    org, not of how the caller authenticated. Local dev signs into seeded
    demo-org users and still needs writes, so the env gate keeps that working."""
    claims = _claims_from(authorization, session_cookie)
    org_id = claims.get("org_id") if claims else None
    if org_id and (org_id != settings.default_org_id or settings.env == "local"):
        return org_id
    if org_id == settings.default_org_id or x_org_id == settings.default_org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The demo workspace is read-only.",
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
    )
