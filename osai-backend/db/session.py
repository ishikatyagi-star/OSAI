from collections.abc import Generator

from fastapi import Header
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session]:
    with SessionLocal() as session:
        yield session


async def get_org_id(x_org_id: str | None = Header(default=None)) -> str:
    return x_org_id or settings.default_org_id
