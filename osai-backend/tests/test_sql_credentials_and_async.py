"""SQL credential-at-rest and event-loop regression coverage."""

from __future__ import annotations

import asyncio
import pickle
import threading
from importlib import import_module
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.routes import sql
from config import Settings, settings
from db.models import Org, SqlSource
from db.sql_secrets import (
    SQL_DSN_CIPHERTEXT_PREFIX,
    SqlDsnSecretError,
    decrypt_sql_dsn,
    encrypt_sql_dsn,
)

_PRIMARY_KEY = Fernet.generate_key().decode("ascii")
_SECONDARY_KEY = Fernet.generate_key().decode("ascii")
_PLAINTEXT_DSN = "postgresql://reader:plain-secret@db.example/warehouse"


@pytest.fixture(autouse=True)
def _configured_keyring(monkeypatch):
    monkeypatch.setattr(settings, "sql_dsn_encryption_keys", _PRIMARY_KEY)


def test_sql_dsn_keyring_configuration_is_strict_and_ordered():
    configured = Settings(sql_dsn_encryption_keys=f" {_PRIMARY_KEY}, {_SECONDARY_KEY} ")
    assert configured.sql_dsn_encryption_key_list == (_PRIMARY_KEY, _SECONDARY_KEY)

    with pytest.raises(ValidationError, match="Fernet key"):
        Settings(sql_dsn_encryption_keys="not-a-key")
    with pytest.raises(ValidationError, match="unique"):
        Settings(sql_dsn_encryption_keys=f"{_PRIMARY_KEY},{_PRIMARY_KEY}")


def test_sql_dsn_encryption_rejects_plaintext_and_supports_staged_rotation(monkeypatch):
    encrypted = encrypt_sql_dsn(_PLAINTEXT_DSN)
    assert encrypted.startswith(SQL_DSN_CIPHERTEXT_PREFIX)
    assert "plain-secret" not in encrypted
    assert decrypt_sql_dsn(encrypted) == _PLAINTEXT_DSN

    with pytest.raises(SqlDsnSecretError, match="not encrypted"):
        decrypt_sql_dsn(_PLAINTEXT_DSN)

    monkeypatch.setattr(settings, "sql_dsn_encryption_keys", _SECONDARY_KEY)
    old_ciphertext = encrypt_sql_dsn(_PLAINTEXT_DSN)
    monkeypatch.setattr(
        settings,
        "sql_dsn_encryption_keys",
        f"{_PRIMARY_KEY},{_SECONDARY_KEY}",
    )
    assert decrypt_sql_dsn(old_ciphertext) == _PLAINTEXT_DSN

    new_ciphertext = encrypt_sql_dsn(_PLAINTEXT_DSN)
    token = new_ciphertext.removeprefix(SQL_DSN_CIPHERTEXT_PREFIX).encode("ascii")
    assert Fernet(_PRIMARY_KEY.encode("ascii")).decrypt(token).decode() == _PLAINTEXT_DSN


def test_missing_key_and_wrong_key_fail_closed(monkeypatch):
    encrypted = encrypt_sql_dsn(_PLAINTEXT_DSN)
    monkeypatch.setattr(settings, "sql_dsn_encryption_keys", "")
    with pytest.raises(SqlDsnSecretError, match="not configured"):
        encrypt_sql_dsn(_PLAINTEXT_DSN)
    with pytest.raises(SqlDsnSecretError, match="not configured"):
        decrypt_sql_dsn(encrypted)

    monkeypatch.setattr(settings, "sql_dsn_encryption_keys", _SECONDARY_KEY)
    with pytest.raises(SqlDsnSecretError, match="cannot be decrypted"):
        decrypt_sql_dsn(encrypted)


def test_sql_source_model_persists_only_ciphertext():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Org.__table__.create(engine)
    SqlSource.__table__.create(engine)
    encrypted = encrypt_sql_dsn(_PLAINTEXT_DSN)

    with Session(engine) as session:
        session.add(Org(id="org-1", name="Org"))
        session.add(
            SqlSource(
                id="source-1",
                org_id="org-1",
                name="Warehouse",
                dsn_encrypted=encrypted,
            )
        )
        session.commit()

    with engine.connect() as connection:
        stored = connection.execute(
            text("SELECT dsn FROM sql_sources WHERE id = 'source-1'")
        ).scalar_one()
    assert stored == encrypted
    assert "plain-secret" not in stored

    with Session(engine) as session:
        session.add(
            SqlSource(
                id="source-plain",
                org_id="org-1",
                name="Unsafe",
                dsn_encrypted=_PLAINTEXT_DSN,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_migration_encrypts_legacy_rows_and_refuses_missing_key():
    migration = import_module("db.migrations.versions.20260722_0032_sql_dsn_encryption")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE sql_sources (id TEXT PRIMARY KEY, dsn TEXT NOT NULL)")
        )
        connection.execute(
            text("INSERT INTO sql_sources (id, dsn) VALUES ('source-1', :dsn)"),
            {"dsn": _PLAINTEXT_DSN},
        )
        with pytest.raises(RuntimeError, match="required"):
            migration._encrypt_existing_dsns(connection, ())
        assert connection.execute(text("SELECT dsn FROM sql_sources")).scalar_one() == (
            _PLAINTEXT_DSN
        )

        migration._encrypt_existing_dsns(connection, (_PRIMARY_KEY,))
        encrypted = connection.execute(text("SELECT dsn FROM sql_sources")).scalar_one()
        assert encrypted.startswith(SQL_DSN_CIPHERTEXT_PREFIX)
        assert "plain-secret" not in encrypted

        migration._decrypt_existing_dsns(connection, (_PRIMARY_KEY,))
        assert connection.execute(text("SELECT dsn FROM sql_sources")).scalar_one() == (
            _PLAINTEXT_DSN
        )


class _FakeDb:
    def __init__(self, source):
        self.source = source

    def get(self, _model, _source_id):
        return self.source


async def _assert_worker_offload(coroutine, entered: threading.Event, release: threading.Event):
    task = asyncio.create_task(coroutine)
    try:
        for _ in range(200):
            if entered.is_set():
                break
            await asyncio.sleep(0.001)
        assert entered.is_set(), "blocking SQL work never started"
        assert not task.done(), "blocking SQL work ran on and stalled the event loop"
    finally:
        release.set()
    return await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_schema_introspection_does_not_block_the_event_loop(monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    def blocking_schema(dsn: str, max_tables: int = 50):
        del max_tables
        assert dsn == _PLAINTEXT_DSN
        entered.set()
        release.wait(timeout=0.5)
        return []

    async def process_run_sync(func, *args, cancellable, limiter):
        assert cancellable is True
        assert limiter is sql._SCHEMA_PROCESS_LIMITER
        return await asyncio.to_thread(func, *args)

    monkeypatch.setattr(sql, "_schema_summary", blocking_schema)
    monkeypatch.setattr(sql.anyio.to_process, "run_sync", process_run_sync)
    source = SimpleNamespace(
        id="source-1",
        org_id="org-1",
        dsn_encrypted=encrypt_sql_dsn(_PLAINTEXT_DSN),
    )
    result = await _assert_worker_offload(
        sql.get_schema(_FakeDb(source), "org-1", "source-1", {}),
        entered,
        release,
    )
    assert result == []


def test_schema_worker_returns_pickle_safe_errors(monkeypatch):
    def rejected_schema(*_args, **_kwargs):
        raise HTTPException(status_code=422, detail="Safe validation error.")

    monkeypatch.setattr(sql, "_schema_summary", rejected_schema)
    outcome = sql._schema_summary_worker(_PLAINTEXT_DSN, 1)

    assert pickle.loads(pickle.dumps(outcome)) == (
        "http_error",
        (422, "Safe validation error."),
    )


@pytest.mark.asyncio
async def test_schema_introspection_has_a_killable_deadline(monkeypatch):
    cancelled = asyncio.Event()

    async def stalled_process(*_args, cancellable, limiter):
        assert cancellable is True
        assert limiter is sql._SCHEMA_PROCESS_LIMITER
        assert limiter.total_tokens == 2
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(sql, "_SCHEMA_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(sql.anyio.to_process, "run_sync", stalled_process)
    source = SimpleNamespace(
        id="source-1",
        org_id="org-1",
        dsn_encrypted=encrypt_sql_dsn(_PLAINTEXT_DSN),
    )

    with pytest.raises(HTTPException) as timed_out:
        await sql.get_schema(_FakeDb(source), "org-1", "source-1", {})

    assert timed_out.value.status_code == 504
    assert timed_out.value.detail == "SQL schema inspection timed out."
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_source_probe_and_plan_map_schema_deadlines(monkeypatch):
    async def timed_out(*_args, **_kwargs):
        raise TimeoutError

    monkeypatch.setattr(sql, "_bounded_schema_summary", timed_out)
    source = SimpleNamespace(
        id="source-1",
        org_id="org-1",
        dsn_encrypted=encrypt_sql_dsn(_PLAINTEXT_DSN),
    )

    with pytest.raises(HTTPException) as probe_timeout:
        await sql.add_source(
            sql.SourceCreate(name="Warehouse", dsn=_PLAINTEXT_DSN),
            _FakeDb(None),
            "org-1",
            {},
        )
    assert probe_timeout.value.status_code == 422
    assert probe_timeout.value.detail == "Could not connect to SQL source."

    with pytest.raises(HTTPException) as plan_timeout:
        await sql.plan_query(
            sql.PlanRequest(source_id="source-1", question="Count rows"),
            _FakeDb(source),
            "org-1",
            {"sub": "admin-1"},
        )
    assert plan_timeout.value.status_code == 504
    assert plan_timeout.value.detail == "SQL schema inspection timed out."


@pytest.mark.asyncio
async def test_query_execution_does_not_block_the_event_loop(monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    def blocking_query(dsn: str, safe_sql: str):
        assert dsn == _PLAINTEXT_DSN
        assert safe_sql == "SELECT 1 LIMIT 500"
        entered.set()
        release.wait(timeout=0.5)
        return ["n"], [[1]]

    monkeypatch.setattr(sql, "_execute_readonly", blocking_query)
    source = SimpleNamespace(
        id="source-1",
        org_id="org-1",
        dsn_encrypted=encrypt_sql_dsn(_PLAINTEXT_DSN),
    )
    result = await _assert_worker_offload(
        sql.execute_query(
            sql.ExecuteRequest(source_id="source-1", sql="SELECT 1"),
            _FakeDb(source),
            "org-1",
            {"sub": "admin-1"},
        ),
        entered,
        release,
    )
    assert result["columns"] == ["n"]
    assert result["rows"] == [[1]]


def test_plaintext_source_rows_fail_closed_at_the_route_boundary():
    source = SimpleNamespace(
        id="source-plain",
        org_id="org-1",
        dsn_encrypted=_PLAINTEXT_DSN,
    )
    with pytest.raises(HTTPException) as blocked:
        sql._source_dsn(source)
    assert blocked.value.status_code == 503
    assert "plain-secret" not in blocked.value.detail


@pytest.mark.asyncio
async def test_source_probe_errors_do_not_echo_credentials(monkeypatch):
    async def failed_probe(_dsn, max_tables=50):
        assert max_tables == 1
        raise RuntimeError(_PLAINTEXT_DSN)

    monkeypatch.setattr(sql, "_bounded_schema_summary", failed_probe)
    with pytest.raises(HTTPException) as blocked:
        await sql.add_source(
            sql.SourceCreate(name="Warehouse", dsn=_PLAINTEXT_DSN),
            _FakeDb(None),
            "org-1",
            {},
        )

    assert blocked.value.status_code == 422
    assert blocked.value.detail == "Could not connect to SQL source."
    assert "plain-secret" not in blocked.value.detail


@pytest.mark.asyncio
async def test_query_execution_errors_do_not_echo_credentials(monkeypatch):
    def failed_query(*_args, **_kwargs):
        raise RuntimeError(_PLAINTEXT_DSN)

    monkeypatch.setattr(sql, "_execute_readonly", failed_query)
    source = SimpleNamespace(
        id="source-1",
        org_id="org-1",
        dsn_encrypted=encrypt_sql_dsn(_PLAINTEXT_DSN),
    )

    with pytest.raises(HTTPException) as blocked:
        await sql.execute_query(
            sql.ExecuteRequest(source_id="source-1", sql="SELECT 1"),
            _FakeDb(source),
            "org-1",
            {"sub": "admin-1"},
        )

    assert blocked.value.status_code == 422
    assert blocked.value.detail == "SQL query failed."
    assert "plain-secret" not in blocked.value.detail


@pytest.mark.asyncio
async def test_plan_generation_errors_do_not_echo_provider_details(monkeypatch):
    async def failed_generate(_prompt):
        raise RuntimeError("provider-internal-secret")

    async def empty_schema(*_args, **_kwargs):
        return []

    gemini = import_module("llm.gemini")
    monkeypatch.setattr(sql, "_bounded_schema_summary", empty_schema)
    monkeypatch.setattr(gemini, "generate", failed_generate)
    source = SimpleNamespace(
        id="source-1",
        org_id="org-1",
        dsn_encrypted=encrypt_sql_dsn(_PLAINTEXT_DSN),
    )

    with pytest.raises(HTTPException) as blocked:
        await sql.plan_query(
            sql.PlanRequest(source_id="source-1", question="Count rows"),
            _FakeDb(source),
            "org-1",
            {"sub": "admin-1"},
        )

    assert blocked.value.status_code == 502
    assert blocked.value.detail == "Could not generate SQL plan."
    assert "provider-internal-secret" not in blocked.value.detail
