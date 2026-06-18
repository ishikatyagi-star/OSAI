from collections.abc import Generator
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config import settings

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
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except Exception:  # noqa: BLE001 — any decode/verify failure = unauthenticated
        return None


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
