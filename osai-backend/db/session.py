from collections.abc import Generator
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from config import settings
from db.api_keys import hash_mcp_api_key, is_mcp_api_key
from db.models import McpApiKey, RevokedToken, User

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session]:
    with SessionLocal() as session:
        yield session


def _decode_token(authorization: str | None) -> dict | None:
    """Verify a Bearer session JWT; return its claims, or None if missing/invalid."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    if is_mcp_api_key(token):
        with SessionLocal() as session:
            key = session.scalar(
                select(McpApiKey).where(
                    McpApiKey.token_hash == hash_mcp_api_key(token),
                    McpApiKey.revoked_at.is_(None),
                )
            )
            if key is None:
                return None
            user = session.get(User, key.user_id)
            if user is None or user.org_id != key.org_id:
                return None
            return {
                "sub": user.id,
                "org_id": user.org_id,
                "role": user.role,
                "auth_type": "mcp_api_key",
            }
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        jti = claims.get("jti")
        if jti:
            with SessionLocal() as session:
                if session.get(RevokedToken, jti) is not None:
                    return None
        return claims
    except Exception:  # noqa: BLE001 — any decode/verify failure = unauthenticated
        return None


async def get_optional_claims(authorization: str | None = Header(default=None)) -> dict | None:
    """Return JWT claims if a valid token is present, else None (no 401). For
    endpoints that work in demo mode but want per-user context when available."""
    return _decode_token(authorization)


async def get_claims(authorization: str | None = Header(default=None)) -> dict:
    """Require a valid session JWT and return its claims (sub, org_id, role, …)."""
    claims = _decode_token(authorization)
    if not claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
        )
    return claims


async def require_admin(claims: Annotated[dict, Depends(get_claims)]) -> dict:
    """Gate an endpoint to org admins."""
    if claims.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required."
        )
    return claims


async def get_org_id(
    authorization: str | None = Header(default=None),
    x_org_id: str | None = Header(default=None),
) -> str:
    """Resolve the caller's org. The org is taken from the verified JWT — never
    from a client-supplied header — so a user cannot read another org's data by
    spoofing X-Org-Id. The public demo workspace is the only header-trusted case."""
    claims = _decode_token(authorization)
    if claims and claims.get("org_id"):
        return claims["org_id"]
    if x_org_id == settings.default_org_id:  # public demo sample data only
        return settings.default_org_id
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
    )
