"""Structured-data answers: visible, editable, read-only SQL over org sources.

The LLM writes a plan (SQL + explanation) from the source's introspected
schema; nothing executes until the user runs it — and execution enforces
SELECT-only, single-statement, capped rows. Data stays where it lives.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from api.ratelimit import rate_limit
from db.models import SqlSource
from db.session import get_db, get_org_id, require_admin, require_writable_org

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
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|grant|revoke|truncate|copy|vacuum|"
    r"call|do|merge|comment|reindex|refresh|lock|listen|notify|set|reset)\b",
    re.IGNORECASE,
)


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


def _engine(dsn: str):
    # Short timeouts: an analytics query should answer fast or be narrowed.
    connect_args: dict[str, object] = {"connect_timeout": 5}
    # Defense in depth for Postgres: make the whole session read-only at the
    # server (so even a query that slips past ensure_readonly_select can't write)
    # and cap runtime with a real statement_timeout, not just connect_timeout.
    # These are libpq (psycopg) options; only apply them to Postgres DSNs.
    if dsn.startswith(("postgresql://", "postgresql+psycopg://", "postgres://")):
        connect_args["options"] = (
            "-c default_transaction_read_only=on -c statement_timeout=10000"
        )
    return create_engine(dsn, connect_args=connect_args, pool_pre_ping=True)


def _mask(dsn: str) -> str:
    return re.sub(r"://([^:/@]+):[^@]+@", r"://\1:***@", dsn)


def _schema_summary(dsn: str, max_tables: int = 50) -> list[dict]:
    engine = _engine(dsn)
    try:
        insp = inspect(engine)
        tables = []
        for name in sorted(insp.get_table_names())[:max_tables]:
            cols = [
                {"name": c["name"], "type": str(c["type"])} for c in insp.get_columns(name)
            ]
            tables.append({"table": name, "columns": cols})
        return tables
    finally:
        engine.dispose()


class SourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    dsn: str = Field(min_length=1, max_length=2000)


@router.post("/sources")
async def add_source(
    body: SourceCreate, db: DbSession, org_id: WriteOrgId, _admin: AdminClaims
) -> dict:
    if not body.dsn.startswith(("postgresql://", "postgresql+psycopg://")):
        raise HTTPException(
            status_code=422, detail="Only PostgreSQL sources are supported (postgresql://…)."
        )
    # Fail fast on unreachable/miscredentialed sources.
    try:
        _schema_summary(body.dsn, max_tables=1)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — connection errors are a client problem here
        raise HTTPException(status_code=422, detail=f"Could not connect: {exc}") from exc
    s = SqlSource(org_id=org_id, name=body.name.strip(), dsn=body.dsn)
    db.add(s)
    db.commit()
    return {"id": s.id, "name": s.name, "dsn": _mask(s.dsn)}


@router.get("/sources")
async def list_sources(db: DbSession, org_id: OrgId, _admin: AdminClaims) -> list[dict]:
    rows = db.query(SqlSource).filter(SqlSource.org_id == org_id).all()
    return [{"id": s.id, "name": s.name, "dsn": _mask(s.dsn)} for s in rows]


@router.delete("/sources/{source_id}")
async def delete_source(
    db: DbSession, org_id: WriteOrgId, source_id: str, _admin: AdminClaims
) -> dict:
    s = _get_source(db, org_id, source_id)
    db.delete(s)
    db.commit()
    return {"deleted": True}


@router.get("/sources/{source_id}/schema")
async def get_schema(
    db: DbSession, org_id: OrgId, source_id: str, _admin: AdminClaims
) -> list[dict]:
    s = _get_source(db, org_id, source_id)
    try:
        return _schema_summary(s.dsn)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Source unreachable: {exc}") from exc


class PlanRequest(BaseModel):
    source_id: str
    question: str = Field(min_length=1, max_length=2000)


@router.post("/plan")
async def plan_query(
    body: PlanRequest, db: DbSession, org_id: WriteOrgId, _admin: AdminClaims
) -> dict:
    """LLM writes the SQL from the schema. The plan is returned for the user
    to inspect/edit — nothing executes here."""
    s = _get_source(db, org_id, body.source_id)
    try:
        schema = _schema_summary(s.dsn)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Source unreachable: {exc}") from exc

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
        raise HTTPException(
            status_code=502, detail=f"Could not generate a plan: {exc}"
        ) from exc

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
    dependencies=[Depends(rate_limit(max_calls=30, window_seconds=60))],
)
async def execute_query(
    body: ExecuteRequest, db: DbSession, org_id: WriteOrgId, admin: AdminClaims
) -> dict:
    """Run a user-approved SELECT deterministically. Same SQL, same answer —
    the LLM is not in this path. Every attempt is audited, including failures."""
    s = _get_source(db, org_id, body.source_id)
    actor = admin.get("email") or admin.get("sub")
    safe_sql = ensure_readonly_select(body.sql)
    engine = _engine(s.dsn)
    started = time.monotonic()
    try:
        with engine.connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            result = conn.execute(text(safe_sql))
            columns = list(result.keys())
            rows = [[_cell(v) for v in row] for row in result.fetchmany(_MAX_ROWS)]
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
        raise HTTPException(status_code=422, detail=f"Query failed: {exc}") from exc
    finally:
        engine.dispose()
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
