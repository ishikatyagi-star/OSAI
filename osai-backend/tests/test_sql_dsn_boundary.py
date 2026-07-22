"""SQL source network boundary: reject internal/control targets and pin DNS."""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from api.routes import sql
from config import settings


@pytest.fixture(autouse=True)
def _external_db_settings(monkeypatch):
    monkeypatch.setattr(
        settings,
        "database_url",
        "postgresql+psycopg://app:secret@control.example.com:5432/control",
    )
    monkeypatch.setattr(settings, "sql_source_host_allowlist", "")


def _dns(*addresses: str):
    def resolve(host, port, **kwargs):
        del host, kwargs
        answers = []
        for address in addresses:
            family = socket.AF_INET6 if ":" in address else socket.AF_INET
            sockaddr = (address, port, 0, 0) if family == socket.AF_INET6 else (address, port)
            answers.append((family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr))
        return answers

    return resolve


def test_public_postgres_host_is_dns_pinned_before_create_engine(monkeypatch):
    monkeypatch.setattr(sql.socket, "getaddrinfo", _dns("93.184.216.34"))
    with patch("api.routes.sql.create_engine") as create:
        sql._engine("postgresql://reader:secret@warehouse.example.com:5432/analytics")
    url = create.call_args.args[0]
    assert url.host == "warehouse.example.com"
    assert url.query["hostaddr"] == "93.184.216.34"
    assert create.call_args.kwargs["connect_args"]["options"].startswith(
        "-c default_transaction_read_only=on"
    )


def test_pinned_url_is_accepted_by_the_psycopg_dialect(monkeypatch):
    monkeypatch.setattr(sql.socket, "getaddrinfo", _dns("93.184.216.34"))
    engine = sql._engine(
        "postgresql://reader:secret@warehouse.example.com:5432/analytics"
    )
    try:
        _, connect_kwargs = engine.dialect.create_connect_args(engine.url)
        assert connect_kwargs["host"] == "warehouse.example.com"
        assert connect_kwargs["hostaddr"] == "93.184.216.34"
        assert connect_kwargs["dbname"] == "analytics"
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "host,address",
    [
        ("127.0.0.1", "127.0.0.1"),
        ("[::1]", "::1"),
        ("169.254.169.254", "169.254.169.254"),
        ("private.example.com", "10.2.3.4"),
    ],
)
def test_internal_and_metadata_addresses_are_rejected(monkeypatch, host, address):
    monkeypatch.setattr(sql.socket, "getaddrinfo", _dns(address))
    with pytest.raises(HTTPException) as blocked:
        sql._validated_external_dsn(f"postgresql://u:p@{host}:5432/analytics")
    assert blocked.value.status_code == 422


def test_every_dns_answer_must_be_public(monkeypatch):
    monkeypatch.setattr(
        sql.socket,
        "getaddrinfo",
        _dns("93.184.216.34", "10.0.0.8"),
    )
    with pytest.raises(HTTPException):
        sql._validated_external_dsn(
            "postgresql://u:p@mixed.example.com:5432/analytics"
        )


def test_routing_query_overrides_and_internal_names_are_rejected(monkeypatch):
    monkeypatch.setattr(sql.socket, "getaddrinfo", _dns("93.184.216.34"))
    with pytest.raises(HTTPException):
        sql._validated_external_dsn(
            "postgresql://u:p@safe.example.com/db?host=127.0.0.1"
        )
    with pytest.raises(HTTPException):
        sql._validated_external_dsn(
            "postgresql://u:p@safe.example.com:5432/db?port=80"
        )
    with pytest.raises(HTTPException):
        sql._validated_external_dsn(
            "postgresql://u:p@safe.example.com:5432/analytics?dbname=control"
        )
    with pytest.raises(HTTPException):
        sql._validated_external_dsn("postgresql://u:p@postgres:5432/db")
    with pytest.raises(HTTPException):
        sql._validated_external_dsn(
            "postgresql://u:p@metadata.google.internal:5432/db"
        )


@pytest.mark.parametrize(
    "query",
    [
        "passfile=%2Fetc%2Fpgpass",
        "sslkey=%2Fsecret%2Fclient.key",
        "sslcert=%2Fsecret%2Fclient.crt",
        "sslrootcert=%2Fsecret%2Fca.crt",
        "options=-c%20search_path%3Dprivate",
        "password=query-secret",
    ],
)
def test_libpq_file_and_unapproved_query_options_are_rejected(monkeypatch, query):
    monkeypatch.setattr(sql.socket, "getaddrinfo", _dns("93.184.216.34"))
    with pytest.raises(HTTPException) as blocked:
        sql._validated_external_dsn(
            f"postgresql://u:p@warehouse.example.com:5432/analytics?{query}"
        )
    assert "unsupported query parameter" in blocked.value.detail


def test_small_safe_query_option_allowlist_is_preserved(monkeypatch):
    monkeypatch.setattr(sql.socket, "getaddrinfo", _dns("93.184.216.34"))
    url = sql._validated_external_dsn(
        "postgresql://u:p@warehouse.example.com:5432/analytics"
        "?sslmode=require&connect_timeout=3&application_name=osai"
    )
    assert url.query["sslmode"] == "require"
    assert url.query["connect_timeout"] == "3"
    assert url.query["application_name"] == "osai"
    assert url.query["hostaddr"] == "93.184.216.34"


def test_exact_allowlist_permits_private_db_but_not_special_or_control(monkeypatch):
    monkeypatch.setattr(settings, "sql_source_host_allowlist", "warehouse.internal")
    monkeypatch.setattr(sql.socket, "getaddrinfo", _dns("10.2.3.4"))
    url = sql._validated_external_dsn(
        "postgresql://u:p@warehouse.internal:5432/analytics"
    )
    assert url.query["hostaddr"] == "10.2.3.4"

    monkeypatch.setattr(settings, "sql_source_host_allowlist", "localhost")
    monkeypatch.setattr(sql.socket, "getaddrinfo", _dns("127.0.0.1"))
    with pytest.raises(HTTPException):
        sql._validated_external_dsn("postgresql://u:p@localhost:5432/analytics")

    monkeypatch.setattr(
        settings,
        "database_url",
        "postgresql+psycopg://app:p@control.internal:5432/control",
    )
    monkeypatch.setattr(settings, "sql_source_host_allowlist", "control.internal")
    monkeypatch.setattr(sql.socket, "getaddrinfo", _dns("10.0.0.9"))
    with pytest.raises(HTTPException) as control:
        sql._validated_external_dsn(
            "postgresql://other:p@control.internal:5432/control"
        )
    assert "control database" in control.value.detail


def test_control_database_alias_and_dns_failures_are_rejected(monkeypatch):
    def resolve(host, port, **kwargs):
        del port, kwargs
        address = "93.184.216.40" if host in {
            "control.example.com",
            "control-alias.example.com",
        } else "93.184.216.34"
        return _dns(address)(host, 5432)

    monkeypatch.setattr(sql.socket, "getaddrinfo", resolve)
    with pytest.raises(HTTPException) as control:
        sql._validated_external_dsn(
            "postgresql://other:p@control-alias.example.com:5432/control"
        )
    assert "control database" in control.value.detail

    def no_dns(*args, **kwargs):
        del args, kwargs
        raise socket.gaierror("not found")

    monkeypatch.setattr(sql.socket, "getaddrinfo", no_dns)
    with pytest.raises(HTTPException) as unresolved:
        sql._validated_external_dsn(
            "postgresql://u:p@missing.example.com:5432/analytics"
        )
    assert unresolved.value.status_code == 422


def test_mask_redacts_authority_and_query_credentials():
    masked = sql._mask(
        "postgresql://alice:authority-secret@db.example/warehouse"
        "?password=query-secret&sslkey=%2Fsecret%2Fclient.key&sslmode=require"
    )
    assert "authority-secret" not in masked
    assert "query-secret" not in masked
    assert "%2Fsecret%2Fclient.key" not in masked
    parsed = sql.make_url(masked)
    assert parsed.query["password"] == "***"
    assert parsed.query["sslkey"] == "***"
    assert "sslmode=require" in masked
    encoded = sql._mask(
        "postgresql://:empty-user-secret@db.example/warehouse"
        "?pass%77ord=encoded-secret"
    )
    assert "empty-user-secret" not in encoded
    assert "encoded-secret" not in encoded


def test_control_database_check_fails_closed_when_control_dns_is_unavailable(monkeypatch):
    def resolve(host, port, **kwargs):
        del kwargs
        if host == "control.example.com":
            raise socket.gaierror("control DNS unavailable")
        return _dns("93.184.216.34")(host, port)

    monkeypatch.setattr(sql.socket, "getaddrinfo", resolve)
    with pytest.raises(HTTPException) as blocked:
        sql._validated_external_dsn(
            "postgresql://u:p@candidate.example.com:5432/control"
        )
    assert "separate from the control database" in blocked.value.detail
