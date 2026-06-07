"""Tests for tenant onboarding, provisioning, and login simulation."""

from __future__ import annotations

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.main import app
from db.models import Base, ConnectorAccount
from db.repositories import provision_org
from db.session import get_db

# Setup SQLite in-memory DB for routing tests with StaticPool
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


def test_provision_org_repository() -> None:
    with TestingSessionLocal() as session:
        org, user = provision_org(
            session,
            name="Acme Corp",
            admin_email="admin@acme.com",
            admin_name="Acme Admin",
        )

        assert org.id is not None
        assert org.name == "Acme Corp"
        assert user.id is not None
        assert user.email == "admin@acme.com"
        assert user.display_name == "Acme Admin"
        assert user.role == "admin"

        # Verify default connector accounts are seeded
        connectors = session.query(ConnectorAccount).filter_by(org_id=org.id).all()
        assert len(connectors) == 4
        keys = {c.connector_key for c in connectors}
        assert keys == {"notion", "slack", "freshdesk", "google_drive"}
        for conn in connectors:
            assert conn.auth_state == "not_configured"


def test_provision_org_duplicate_email() -> None:
    with TestingSessionLocal() as session:
        # First creation
        provision_org(
            session,
            name="Org 1",
            admin_email="duplicate@test.com",
            admin_name="User 1",
        )

        # Second creation with same email should raise ValueError
        with pytest.raises(ValueError, match="already exists"):
            provision_org(
                session,
                name="Org 2",
                admin_email="duplicate@test.com",
                admin_name="User 2",
            )


def test_api_orgs_provisioning() -> None:
    payload = {
        "name": "Wayne Enterprises",
        "admin_email": "bruce@wayne.com",
        "admin_display_name": "Bruce Wayne",
    }
    response = client.post("/orgs", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Wayne Enterprises"
    assert data["admin_email"] == "bruce@wayne.com"
    assert data["admin_display_name"] == "Bruce Wayne"
    assert "org_id" in data

    # Attempting to provision with duplicate email should fail
    response_dup = client.post("/orgs", json=payload)
    assert response_dup.status_code == 400
    assert "already exists" in response_dup.json()["detail"]


def test_api_auth_login() -> None:
    # Attempt login before user exists
    response_fail = client.post("/auth/login", json={"email": "nonexistent@test.com"})
    assert response_fail.status_code == status.HTTP_401_UNAUTHORIZED
    assert response_fail.json()["detail"] == "Invalid credentials"

    # Provision user/org first
    payload = {
        "name": "Star Labs",
        "admin_email": "barry@star.local",
        "admin_display_name": "Barry Allen",
    }
    response_org = client.post("/orgs", json=payload)
    assert response_org.status_code == 200

    # Attempt login for provisioned user
    response_login = client.post("/auth/login", json={"email": "barry@star.local"})
    assert response_login.status_code == 200
    data = response_login.json()
    assert "user_id" in data
    assert data["org_id"] == response_org.json()["org_id"]
    assert data["role"] == "admin"
    assert data["token"] == f"mock-jwt-token-{data['user_id']}"
