"""Structured-data answers: visible, editable, read-only SQL over org sources.

The LLM writes a plan (SQL + explanation) from the source's introspected
schema; nothing executes until the user runs it — and execution enforces
SELECT-only, single-statement, capped rows. Data stays where it lives.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import re
import socket
import time
from typing import Annotated, cast

import anyio
import anyio.to_process
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from api.ratelimit import (
    PROVIDER_ACTION_BUDGET,
    SQL_EXECUTE_BUDGET,
    SQL_PLAN_BUDGET,
    SQL_SCHEMA_BUDGET,
    rate_limit,
)
from config import settings
from db.models import SqlSource
from db.session import get_db, get_org_id, require_admin, require_writable_org
from db.sql_secrets import SqlDsnSecretError, decrypt_sql_dsn, encrypt_sql_dsn

logger = logging.getLogger("osai.sql")

router = APIRouter(prefix="/sql", tags=["sql"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]
# Adding a source stores a DSN; plan/execute run SQL against a live external DB.
# None of that is reachable from the anonymous demo workspace (SEC-003).
WriteOrgId = Annotated[str, Depends(require_writable_org)]
# SQL bypasses the per-document ACL/tier model entirely: a query reads whatever
# the connected database role can see, unfiltered by the permissions that gate
# every other answer. So the whole surface is admin-only — managing a source
# handles live DB credentials, and running a query is unmediated data access
# (SHE-6 P0 "enforce admin authorization"). Grant it per-source to members only
# once row-level scoping exists.
AdminClaims = Annotated[dict, Depends(require_admin)]

_MAX_ROWS = 500
_SCHEMA_TIMEOUT_SECONDS = 15
_SCHEMA_PROCESS_LIMITER = anyio.CapacityLimiter(2)
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|grant|revoke|truncate|copy|vacuum|"
    r"call|do|merge|comment|reindex|refresh|lock|listen|notify|set|reset)\b",
    re.IGNORECASE,
)

_POSTGRES_DRIVERS = frozenset({"postgresql", "postgresql+psycopg"})
_ROUTING_QUERY_KEYS = frozenset(
    {"host", "hostaddr", "port", "service", "servicefile", "dbname", "database"}
)
_ALLOWED_DSN_QUERY_KEYS = frozenset(
    {
        "application_name",
        "channel_binding",
        "connect_timeout",
        "keepalives",
        "keepalives_count",
        "keepalives_idle",
        "keepalives_interval",
        "sslmode",
        "target_session_attrs",
        "tcp_user_timeout",
    }
)
_SENSITIVE_DSN_QUERY_KEYS = frozenset(
    {
        "password",
        "sslpassword",
        "passfile",
        "sslcert",
        "sslcrl",
        "sslkey",
        "sslrootcert",
    }
)
_INTERNAL_HOST_SUFFIXES = (
    ".internal",
    ".local",
    ".localhost",
    ".lan",
    ".home.arpa",
    ".svc",
)
_METADATA_HOSTS = frozenset(
    {
        "metadata",
        "metadata.google.internal",
        "instance-data",
    }
)
_METADATA_ADDRESSES = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),
        ipaddress.ip_address("100.100.100.200"),
    }
)


def _dsn_error(detail: str) -> HTTPException:
    return HTTPException(status_code=422, detail=detail)


def _normalise_host(host: str) -> str:
    host = host.strip().lower().rstrip(".")
    if not host or "%" in host or "," in host:
        raise _dsn_error("Database DSN must contain one explicit host.")
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise _dsn_error("Database DSN contains an invalid host.") from exc


def _host_is_allowlisted(host: str) -> bool:
    return host in settings.sql_source_host_allowlist_entries


def _is_internal_hostname(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return "." not in host or host.endswith(_INTERNAL_HOST_SUFFIXES)


def _is_metadata_hostname(host: str) -> bool:
    return host in _METADATA_HOSTS or host.startswith("metadata.")


def _resolve_addresses(
    host: str, port: int
) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
    try:
        answers = socket.getaddrinfo(
            host,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except OSError as exc:
        raise _dsn_error("Database host could not be resolved.") from exc
    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for answer in answers:
        try:
            addresses.add(ipaddress.ip_address(answer[4][0]))
        except ValueError:
            continue
    if not addresses:
        raise _dsn_error("Database host did not resolve to an IP address.")
    return tuple(sorted(addresses, key=lambda address: (address.version, int(address))))


def _reject_unsafe_addresses(
    addresses: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...],
    *,
    allowlisted: bool,
) -> None:
    for address in addresses:
        if address in _METADATA_ADDRESSES:
            raise _dsn_error("Cloud metadata destinations are not allowed.")
        if (
            address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_unspecified
            or address.is_reserved
        ):
            raise _dsn_error("Loopback, link-local, and special-use destinations are not allowed.")
        if not address.is_global and not allowlisted:
            raise _dsn_error(
                "Private database hosts require an exact OSAI_SQL_SOURCE_HOST_ALLOWLIST entry."
            )


def _is_app_control_database(
    candidate: URL,
    candidate_addresses: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...],
) -> bool:
    try:
        control = make_url(settings.database_url)
        if control.drivername not in _POSTGRES_DRIVERS or not control.host:
            return False
        candidate_host = _normalise_host(candidate.host or "")
        control_host = _normalise_host(control.host)
        candidate_port = candidate.port or 5432
        control_port = control.port or 5432
    except (ValueError, HTTPException):
        return False
    if candidate_port != control_port or candidate.database != control.database:
        return False
    if candidate_host == control_host:
        return True
    try:
        control_addresses = _resolve_addresses(control_host, control_port)
    except HTTPException as exc:
        # When the database name and port match, failing open here could admit
        # an alias of the control database merely because its canonical hostname
        # had a transient DNS failure.
        raise _dsn_error(
            "Could not verify that this source is separate from the control database."
        ) from exc
    return bool(set(candidate_addresses).intersection(control_addresses))


def _validated_external_dsn(dsn: str) -> URL:
    """Validate and DNS-pin an external Postgres DSN before any connection.

    Every resolved address is checked, not only the first, and ``hostaddr`` pins
    psycopg to the checked address so a second DNS lookup cannot redirect the
    connection to an internal service after validation.
    """
    try:
        url = make_url(dsn)
        port = url.port or 5432
    except (ValueError, TypeError) as exc:
        raise _dsn_error("Malformed PostgreSQL DSN.") from exc
    if url.drivername not in _POSTGRES_DRIVERS:
        raise _dsn_error("Only PostgreSQL sources are supported (postgresql://...).")
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    if not url.host or not url.database:
        raise _dsn_error("Database DSN must include a host and database name.")
    query_keys = {str(key).lower() for key in url.query}
    if query_keys.intersection(_ROUTING_QUERY_KEYS):
        raise _dsn_error("Database DSN may not override host routing in query parameters.")
    unsupported_query_keys = sorted(query_keys - _ALLOWED_DSN_QUERY_KEYS)
    if unsupported_query_keys:
        raise _dsn_error(
            "Database DSN contains unsupported query parameter(s): "
            + ", ".join(unsupported_query_keys)
            + "."
        )

    host = _normalise_host(url.host)
    allowlisted = _host_is_allowlisted(host)
    if _is_metadata_hostname(host):
        raise _dsn_error("Cloud metadata destinations are not allowed.")
    if _is_internal_hostname(host) and not allowlisted:
        raise _dsn_error(
            "Internal database hosts require an exact OSAI_SQL_SOURCE_HOST_ALLOWLIST entry."
        )

    addresses = _resolve_addresses(host, port)
    _reject_unsafe_addresses(addresses, allowlisted=allowlisted)
    if _is_app_control_database(url, addresses):
        raise _dsn_error("The application's control database cannot be added as a SQL source.")

    # Keep the hostname for TLS verification while pinning the already-validated
    # network address for libpq/psycopg's actual connection.
    return url.update_query_dict({"hostaddr": str(addresses[0])})


def ensure_readonly_select(sql: str) -> str:
    """Reject anything that isn't a single read-only SELECT/WITH statement.
    Returns the statement with a LIMIT cap appended when none is present."""
    stripped = re.sub(r"--[^\n]*", " ", sql)  # line comments
    stripped = re.sub(r"/\*.*?\*/", " ", stripped, flags=re.DOTALL)  # block comments
    stripped = stripped.strip().rstrip(";").strip()
    if not stripped:
        raise HTTPException(status_code=422, detail="Empty SQL.")
    if ";" in stripped:
        raise HTTPException(status_code=422, detail="Only a single statement is allowed.")
    if not re.match(r"^(select|with)\b", stripped, re.IGNORECASE):
        raise HTTPException(status_code=422, detail="Only SELECT queries are allowed.")
    if _FORBIDDEN.search(stripped):
        raise HTTPException(
            status_code=422, detail="Query contains a write/DDL keyword — read-only only."
        )
    if not re.search(r"\blimit\s+\d+\b", stripped, re.IGNORECASE):
        stripped = f"{stripped} LIMIT {_MAX_ROWS}"
    return stripped


def _fingerprint(sql: str) -> str:
    """Stable id for a query's shape. Logged instead of the SQL text so an audit
    trail never leaks the values (or PII) embedded in a literal."""
    normalised = re.sub(r"\s+", " ", sql.strip().lower())
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]


def _audit(
    *,
    actor: str | None,
    org_id: str,
    source_id: str,
    sql: str,
    duration_ms: int,
    outcome: str,
    rows: int | None = None,
    error: str | None = None,
) -> None:
    """Record who ran what, against which source, and how it went (SHE-6 P0).
    Queries touch customer databases, so the trail must exist even when the
    query fails."""
    logger.info(
        "sql_query actor=%s org=%s source=%s fingerprint=%s duration_ms=%d "
        "outcome=%s rows=%s error=%s",
        actor,
        org_id,
        source_id,
        _fingerprint(sql),
        duration_ms,
        outcome,
        rows if rows is not None else "-",
        error or "-",
    )


def _get_source(db: Session, org_id: str, source_id: str) -> SqlSource:
    s = db.get(SqlSource, source_id)
    if s is None or s.org_id != org_id:
        raise HTTPException(status_code=404, detail="Data source not found.")
    return s


def _source_dsn(source: SqlSource) -> str:
    """Return a usable DSN without ever accepting legacy plaintext storage."""
    try:
        return decrypt_sql_dsn(source.dsn_encrypted)
    except SqlDsnSecretError as exc:
        logger.error(
            "sql_source_credentials_unavailable org=%s source=%s reason=%s",
            source.org_id,
            source.id,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail="SQL source credentials are unavailable.",
        ) from exc


def _engine(dsn: str):
    url = _validated_external_dsn(dsn)
    # Short timeouts: an analytics query should answer fast or be narrowed.
    connect_args: dict[str, object] = {"connect_timeout": 5}
    # Defense in depth for Postgres: make the whole session read-only at the
    # server (so even a query that slips past ensure_readonly_select can't write)
    # and cap runtime with a real statement_timeout, not just connect_timeout.
    # These are libpq (psycopg) options; only apply them to Postgres DSNs.
    if url.drivername in _POSTGRES_DRIVERS:
        connect_args["options"] = "-c default_transaction_read_only=on -c statement_timeout=10000"
    return create_engine(url, connect_args=connect_args, pool_pre_ping=True)


def _mask(dsn: str) -> str:
    try:
        url = make_url(dsn)
    except (TypeError, ValueError):
        return "<redacted invalid DSN>"
    if url.password is not None:
        url = url.set(password="***")
    query = {
        key: ("***" if str(key).lower() in _SENSITIVE_DSN_QUERY_KEYS else value)
        for key, value in url.query.items()
    }
    # SQLAlchemy percent-decodes query keys before this comparison, so encoded
    # spellings such as pass%77ord cannot bypass redaction.
    url = url.set(query=query)
    return url.render_as_string(hide_password=False)


def _schema_summary(dsn: str, max_tables: int = 50) -> list[dict]:
    engine = _engine(dsn)
    try:
        insp = inspect(engine)
        tables = []
        for name in sorted(insp.get_table_names())[:max_tables]:
            cols = [{"name": c["name"], "type": str(c["type"])} for c in insp.get_columns(name)]
            tables.append({"table": name, "columns": cols})
        return tables
    finally:
        engine.dispose()


def _schema_summary_worker(dsn: str, max_tables: int) -> tuple[str, object]:
    """Return only pickle-safe values across the process boundary."""
    try:
        return "ok", _schema_summary(dsn, max_tables)
    except HTTPException as exc:
        return "http_error", (exc.status_code, str(exc.detail))
    except Exception as exc:  # noqa: BLE001 - serialize only the safe error class
        return "error", type(exc).__name__


async def _bounded_schema_summary(dsn: str, max_tables: int = 50) -> list[dict]:
    """Introspect without consuming the API's shared worker-thread pool."""
    with anyio.fail_after(_SCHEMA_TIMEOUT_SECONDS):
        outcome, payload = await anyio.to_process.run_sync(
            _schema_summary_worker,
            dsn,
            max_tables,
            cancellable=True,
            limiter=_SCHEMA_PROCESS_LIMITER,
        )
    if outcome == "ok":
        return cast(list[dict], payload)
    if outcome == "http_error":
        status_code, detail = cast(tuple[int, str], payload)
        raise HTTPException(status_code=status_code, detail=detail)
    logger.warning("sql_schema_worker_failed error=%s", payload)
    raise RuntimeError("SQL schema inspection failed.")


def _execute_readonly(dsn: str, safe_sql: str) -> tuple[list[str], list[list[object]]]:
    """Run blocking SQLAlchemy/psycopg work outside the request event loop."""
    engine = _engine(dsn)
    try:
        with engine.connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            result = conn.execute(text(safe_sql))
            columns = list(result.keys())
            rows = [[_cell(value) for value in row] for row in result.fetchmany(_MAX_ROWS)]
        return columns, rows
    finally:
        engine.dispose()


class SourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    dsn: str = Field(min_length=1, max_length=2000)


@router.post(
    "/sources",
    dependencies=[Depends(rate_limit(*PROVIDER_ACTION_BUDGET))],
)
async def add_source(
    body: SourceCreate, db: DbSession, org_id: WriteOrgId, _admin: AdminClaims
) -> dict:
    if not body.dsn.startswith(("postgresql://", "postgresql+psycopg://")):
        raise HTTPException(
            status_code=422, detail="Only PostgreSQL sources are supported (postgresql://…)."
        )
    try:
        encrypted_dsn = encrypt_sql_dsn(body.dsn)
    except SqlDsnSecretError as exc:
        raise HTTPException(
            status_code=503,
            detail="SQL source credential encryption is not configured.",
        ) from exc
    # Fail fast on unreachable/miscredentialed sources.
    try:
        await _bounded_schema_summary(body.dsn, max_tables=1)
    except TimeoutError as exc:
        logger.warning("sql_source_probe_timed_out org=%s", org_id)
        raise HTTPException(status_code=422, detail="Could not connect to SQL source.") from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — connection errors are a client problem here
        logger.warning("sql_source_probe_failed org=%s error=%s", org_id, type(exc).__name__)
        raise HTTPException(status_code=422, detail="Could not connect to SQL source.") from exc
    s = SqlSource(org_id=org_id, name=body.name.strip(), dsn_encrypted=encrypted_dsn)
    db.add(s)
    db.commit()
    return {"id": s.id, "name": s.name, "dsn": _mask(body.dsn)}


@router.get("/sources")
async def list_sources(db: DbSession, org_id: OrgId, _admin: AdminClaims) -> list[dict]:
    rows = db.query(SqlSource).filter(SqlSource.org_id == org_id).all()
    return [{"id": s.id, "name": s.name, "dsn": _mask(_source_dsn(s))} for s in rows]


@router.delete("/sources/{source_id}")
async def delete_source(
    db: DbSession, org_id: WriteOrgId, source_id: str, _admin: AdminClaims
) -> dict:
    s = _get_source(db, org_id, source_id)
    db.delete(s)
    db.commit()
    return {"deleted": True}


@router.get(
    "/sources/{source_id}/schema",
    dependencies=[Depends(rate_limit(*SQL_SCHEMA_BUDGET))],
)
async def get_schema(
    db: DbSession, org_id: OrgId, source_id: str, _admin: AdminClaims
) -> list[dict]:
    s = _get_source(db, org_id, source_id)
    dsn = _source_dsn(s)
    try:
        return await _bounded_schema_summary(dsn)
    except TimeoutError as exc:
        logger.warning(
            "sql_source_schema_timed_out org=%s source=%s",
            org_id,
            source_id,
        )
        raise HTTPException(status_code=504, detail="SQL schema inspection timed out.") from exc
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "sql_source_schema_failed org=%s source=%s error=%s",
            org_id,
            source_id,
            type(exc).__name__,
        )
        raise HTTPException(status_code=502, detail="SQL source is unreachable.") from exc


class PlanRequest(BaseModel):
    source_id: str
    question: str = Field(min_length=1, max_length=2000)


@router.post(
    "/plan",
    dependencies=[Depends(rate_limit(*SQL_PLAN_BUDGET))],
)
async def plan_query(
    body: PlanRequest, db: DbSession, org_id: WriteOrgId, _admin: AdminClaims
) -> dict:
    """LLM writes the SQL from the schema. The plan is returned for the user
    to inspect/edit — nothing executes here."""
    s = _get_source(db, org_id, body.source_id)
    dsn = _source_dsn(s)
    try:
        schema = await _bounded_schema_summary(dsn)
    except TimeoutError as exc:
        logger.warning(
            "sql_source_plan_schema_timed_out org=%s source=%s",
            org_id,
            body.source_id,
        )
        raise HTTPException(status_code=504, detail="SQL schema inspection timed out.") from exc
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "sql_source_plan_schema_failed org=%s source=%s error=%s",
            org_id,
            body.source_id,
            type(exc).__name__,
        )
        raise HTTPException(status_code=502, detail="SQL source is unreachable.") from exc

    schema_text = "\n".join(
        f"{t['table']}({', '.join(c['name'] + ' ' + c['type'] for c in t['columns'])})"
        for t in schema
    )
    prompt = (
        "You write a single read-only PostgreSQL SELECT statement.\n"
        f"Schema:\n{schema_text}\n\n"
        f"Question: {body.question}\n\n"
        "Reply with exactly two sections:\n"
        "SQL:\n<the query>\n"
        "EXPLANATION:\n<one plain-language sentence describing what it computes>"
    )
    from llm.gemini import generate

    try:
        raw = await generate(prompt)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "sql_plan_generation_failed org=%s source=%s error=%s",
            org_id,
            body.source_id,
            type(exc).__name__,
        )
        raise HTTPException(status_code=502, detail="Could not generate SQL plan.") from exc

    m = re.search(r"SQL:\s*(.+?)\s*EXPLANATION:\s*(.+)", raw, re.DOTALL | re.IGNORECASE)
    sql_raw = (m.group(1) if m else raw).strip().strip("`")
    sql_raw = re.sub(r"^sql\s*\n", "", sql_raw, flags=re.IGNORECASE)
    explanation = (m.group(2).strip() if m else "").strip()
    safe_sql = ensure_readonly_select(sql_raw)
    return {"sql": safe_sql, "explanation": explanation}


class ExecuteRequest(BaseModel):
    source_id: str
    sql: str = Field(min_length=1, max_length=20_000)


@router.post(
    "/execute",
    # A query hits a customer's live database; cap the blast radius of a runaway
    # UI loop or a scripted caller (SHE-6 P0 "rate limits").
    dependencies=[Depends(rate_limit(*SQL_EXECUTE_BUDGET))],
)
async def execute_query(
    body: ExecuteRequest, db: DbSession, org_id: WriteOrgId, admin: AdminClaims
) -> dict:
    """Run a user-approved SELECT deterministically. Same SQL, same answer —
    the LLM is not in this path. Every attempt is audited, including failures."""
    s = _get_source(db, org_id, body.source_id)
    actor = admin.get("email") or admin.get("sub")
    safe_sql = ensure_readonly_select(body.sql)
    dsn = _source_dsn(s)
    started = time.monotonic()
    try:
        columns, rows = await run_in_threadpool(_execute_readonly, dsn, safe_sql)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — SQL errors are the caller's to fix
        _audit(
            actor=actor,
            org_id=org_id,
            source_id=s.id,
            sql=safe_sql,
            duration_ms=int((time.monotonic() - started) * 1000),
            outcome="failed",
            error=type(exc).__name__,
        )
        raise HTTPException(status_code=422, detail="SQL query failed.") from exc
    _audit(
        actor=actor,
        org_id=org_id,
        source_id=s.id,
        sql=safe_sql,
        duration_ms=int((time.monotonic() - started) * 1000),
        outcome="succeeded",
        rows=len(rows),
    )
    return {"sql": safe_sql, "columns": columns, "rows": rows, "row_count": len(rows)}


def _cell(v: object) -> object:
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    return str(v)
