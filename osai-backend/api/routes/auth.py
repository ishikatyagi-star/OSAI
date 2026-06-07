"""Auth endpoints — login simulation."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import User
from db.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])
DbSession = Annotated[Session, Depends(get_db)]


class LoginRequest(BaseModel):
    email: str


class LoginResponse(BaseModel):
    user_id: str
    org_id: str
    role: str
    token: str


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: DbSession) -> LoginResponse:
    """Simulate a password-free lookup authentication returning a mock JWT token."""
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    # Return a mock token format: "mock-jwt-token-{user_id}"
    token = f"mock-jwt-token-{user.id}"
    return LoginResponse(
        user_id=user.id,
        org_id=user.org_id,
        role=user.role,
        token=token,
    )
