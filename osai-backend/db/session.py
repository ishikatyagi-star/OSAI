from collections.abc import Generator
from typing import Annotated

import jwt
from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from config import settings

# Name of the httpOnly session cookie. The browser sends the JWT here so it never
# needs to live in JS-readable storage (localStorage), shrinking the XSS
# token-theft blast radius (SEC-009). The Authorization header path is retained
# for API clients and tests.
SESSION_COOKIE = "osai_session"
_SAFE_HTTP_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# statement_timeout: one runaway query must not wedge the single web process
# (free tier runs everything in-process). SQLite (tests) rejects `options`.
_connect_args = (
    {"options": "-c statement_timeout=15000"}
    if settings.database_url.startswith("postgres")
    else {}
)
engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=_connect_args)


if engine.dialect.name == "sqlite":

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")


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


def _assert_current(db: Session, claims: dict) -> None:
    """Reject a token whose principal is deleted or whose generation (`tv`) was
    revoked. Every dependency that turns a JWT into access must call this, not
    just admin gates — a signature check alone keeps a revoked token alive for
    its full 30-day lifetime (SEC-002)."""
    # Lazy import avoids a module-load cycle (repositories imports SessionLocal).
    from db.repositories import assert_token_current

    assert_token_current(db, claims)


async def get_optional_claims(
    db: Annotated[Session, Depends(get_db)],
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict | None:
    """Return JWT claims if a valid token is present, else None (no 401). For
    endpoints that work in demo mode but want per-user context when available.
    A revoked/deleted-principal token yields None — anonymous, never a partial
    identity — matching how an expired token behaves."""
    claims = _claims_from(authorization, session_cookie)
    if not claims:
        return None
    try:
        _assert_current(db, claims)
    except HTTPException:
        return None
    return claims


async def get_claims(
    db: Annotated[Session, Depends(get_db)],
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict:
    """Require a valid, unrevoked session JWT and return its claims."""
    claims = _claims_from(authorization, session_cookie)
    if not claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
        )
    _assert_current(db, claims)
    return claims


def assert_writable_org(org_id: str | None) -> None:
    """Reject every mutation targeting the shared public demo workspace."""
    if org_id == settings.default_org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The demo workspace is read-only.",
        )


async def require_admin(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    claims: Annotated[dict | None, Depends(get_optional_claims)],
    x_org_id: str | None = Header(default=None),
) -> dict:
    """Gate an endpoint to current org admins.

    The JWT role is only a snapshot from sign-in time. Read the current user so
    a demotion takes effect immediately instead of leaving admin access alive
    until the token expires. Unsafe requests targeting the shared demo org are
    rejected for both its anonymous header identity and valid demo-admin JWTs.
    """
    if request.method.upper() not in _SAFE_HTTP_METHODS:
        assert_writable_org(claims.get("org_id") if claims else x_org_id)
    if claims is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
        )
    from db.models import User

    user_id = claims.get("sub")
    user = db.get(User, user_id) if user_id else None
    if user is None or user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required.")
    return {**claims, "org_id": user.org_id, "role": user.role}


async def get_org_id(
    db: Annotated[Session, Depends(get_db)],
    authorization: str | None = Header(default=None),
    x_org_id: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> str:
    """Resolve the caller's org. The org is taken from the verified JWT — never
    from a client-supplied header — so a user cannot read another org's data by
    spoofing X-Org-Id. The public demo workspace is the only header-trusted case."""
    claims = _claims_from(authorization, session_cookie)
    if claims and claims.get("org_id"):
        _assert_current(db, claims)
        return claims["org_id"]
    if x_org_id == settings.default_org_id:  # public demo sample data only
        return settings.default_org_id
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")


async def require_writable_org(
    db: Annotated[Session, Depends(get_db)],
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

    The shared demo org is read-only *even with a valid JWT* (e.g. a
    leaked/seeded demo-org token) and in local development. Demo isolation is a
    property of the org, not of how the caller authenticated."""
    claims = _claims_from(authorization, session_cookie)
    org_id = claims.get("org_id") if claims else None
    if org_id:
        assert_writable_org(org_id)
        _assert_current(db, claims)
        return org_id
    assert_writable_org(x_org_id)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
