from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.routes.auth import _issue_token
from db.models import Base, Org, RevokedToken, User
import db.session as db_session


def test_revoked_session_token_is_rejected(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    user = User(id="user", org_id="org", email="user@example.com", display_name="User")
    with sessions() as db:
        db.add(Org(id="org", name="Org"))
        db.add(user)
        db.commit()
    monkeypatch.setattr(db_session, "SessionLocal", sessions)
    token = _issue_token(user)
    claims = db_session._decode_token(f"Bearer {token}")
    assert claims is not None and claims["jti"]
    with sessions() as db:
        db.add(RevokedToken(jti=claims["jti"], expires_at=user.created_at))
        db.commit()
    assert db_session._decode_token(f"Bearer {token}") is None
