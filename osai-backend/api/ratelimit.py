"""Shared rate limiting for abuse-prone and high-cost HTTP endpoints.

Non-local deployments use one atomic Redis sliding window across every API
process. Local/test runs use a bounded in-process fallback so the test suite and
developer server do not require Redis. The application is the sole owner of
forwarded-address trust; Uvicorn proxy-header parsing must remain disabled.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import secrets
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from functools import lru_cache
from threading import Lock

from fastapi import HTTPException, Request, status
from redis.asyncio import Redis

from config import settings
from db.session import SESSION_COOKIE, _claims_from

logger = logging.getLogger("osai.ratelimit")

_LIMIT_DETAIL = "Too many requests. Please wait a moment and try again."
_UNAVAILABLE_DETAIL = "Request rate limiting is temporarily unavailable."
_REDIS_KEY_PREFIX = "osai:{ratelimit-v3}"
_REDIS_REGISTRY_KEY = f"{_REDIS_KEY_PREFIX}:active"

# Stable cost-class budgets. Each bucket is still isolated by signed tenant,
# client, and route, so sharing a budget here does not merge route counters.
INTERACTIVE_AI_BUDGET = (20, 60)
PROVIDER_ACTION_BUDGET = (10, 60)
WORKFLOW_RUN_BUDGET = (10, 3_600)
EVAL_RUN_BUDGET = (3, 3_600)
INGEST_START_BUDGET = (10, 3_600)
OAUTH_START_BUDGET = (10, 3_600)
SQL_PLAN_BUDGET = (20, 3_600)
SQL_SCHEMA_BUDGET = (20, 3_600)
SQL_EXECUTE_BUDGET = (30, 60)

# Redis TIME keeps every API process on the same clock. The random suffix makes
# each sorted-set member unique even when concurrent requests share a timestamp.
_REDIS_SLIDING_WINDOW = """
local now = redis.call('TIME')
local now_us = (tonumber(now[1]) * 1000000) + tonumber(now[2])
local max_calls = tonumber(ARGV[1])
local window_seconds = tonumber(ARGV[2])
local window_us = window_seconds * 1000000
local cutoff = now_us - window_us
local expires_at = now_us + window_us
local max_keys = tonumber(ARGV[4])

redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now_us)
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', cutoff)
if redis.call('ZCARD', KEYS[1]) >= max_calls then
  return 0
end

if not redis.call('ZSCORE', KEYS[2], KEYS[1]) then
  if redis.call('ZCARD', KEYS[2]) >= max_keys then
    return -1
  end
end

redis.call('ZADD', KEYS[1], now_us, tostring(now_us) .. ':' .. ARGV[3])
redis.call('EXPIRE', KEYS[1], window_seconds)
redis.call('ZADD', KEYS[2], expires_at, KEYS[1])
local latest = redis.call('ZRANGE', KEYS[2], -1, -1, 'WITHSCORES')
if #latest == 2 then
  redis.call('PEXPIREAT', KEYS[2], math.ceil(tonumber(latest[2]) / 1000))
end
return 1
"""


@dataclass
class _MemoryBucket:
    hits: deque[float]
    window_seconds: int


_HITS: OrderedDict[str, _MemoryBucket] = OrderedDict()
_MEMORY_LOCK = Lock()
_REDIS_CLIENT: Redis | None = None
_REDIS_CLIENT_URL: str | None = None


@lru_cache(maxsize=32)
def _trusted_proxy_networks(value: str) -> tuple:
    """Parse the validated setting; fail safely if tests mutate it directly."""
    try:
        return tuple(
            ipaddress.ip_network(item.strip(), strict=False)
            for item in value.split(",")
            if item.strip()
        )
    except ValueError:
        logger.error("invalid trusted-proxy CIDR; forwarded addresses disabled")
        return ()


def _normalise_ip(
    value: str | None,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        address = ipaddress.ip_address((value or "").strip())
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


def _combined_forwarded_addresses(
    request: Request,
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address | None]:
    """Combine every XFF field-value in wire order, including duplicates."""
    return [
        _normalise_ip(item)
        for field_value in request.headers.getlist("x-forwarded-for")
        for item in field_value.split(",")
    ]


def _address_identity(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> str:
    """Aggregate IPv6 callers before hashing to prevent address rotation."""
    if isinstance(address, ipaddress.IPv6Address):
        network = ipaddress.ip_network(
            (address, settings.rate_limit_ipv6_prefix_length),
            strict=False,
        )
        return f"{network.network_address}/{network.prefixlen}"
    return str(address)


def _client_identity(request: Request) -> str:
    """Return a stable client address under the configured trust policy."""
    peer_raw = request.client.host if request.client else "unknown"
    peer = _normalise_ip(peer_raw)
    if peer is None:
        return peer_raw.strip().lower() or "unknown"

    mode = settings.rate_limit_forwarded_for_mode
    if mode == "direct":
        return _address_identity(peer)

    forwarded = _combined_forwarded_addresses(request)
    if mode == "render_first":
        # Preserve duplicate field-values in wire order. Render guarantees the
        # first entry is the client; skipping malformed entries is a defensive
        # fallback that chooses the first valid entry and never skips past it.
        for address in forwarded:
            if address is not None:
                return _address_identity(address)
        return _address_identity(peer)

    # trusted_chain: only a configured direct proxy may supply the chain. Walk
    # from the nearest hop and stop at the first untrusted address. Reject the
    # entire chain when any field-value is malformed.
    trusted = _trusted_proxy_networks(settings.rate_limit_trusted_proxy_cidrs)
    if not trusted or not any(peer in network for network in trusted):
        return _address_identity(peer)
    if not forwarded or any(address is None for address in forwarded):
        return _address_identity(peer)

    addresses = [address for address in forwarded if address is not None]
    for address in reversed(addresses):
        if not any(address in network for network in trusted):
            return _address_identity(address)
    return _address_identity(addresses[0])


def _tenant_identity(request: Request) -> str:
    """Use only a signature-verified session tenant; never trust X-Org-Id."""
    claims = _claims_from(
        request.headers.get("authorization"),
        request.cookies.get(SESSION_COOKIE),
    )
    org_id = claims.get("org_id") if claims else None
    return str(org_id) if org_id else "anonymous"


def _route_path(request: Request) -> str:
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    return template if isinstance(template, str) else request.url.path


def _rate_limit_key(
    request: Request,
    *,
    max_calls: int,
    window_seconds: int,
    verified_tenant_id: str | None = None,
) -> str:
    tenant_id = (
        verified_tenant_id.strip() if verified_tenant_id is not None else _tenant_identity(request)
    )
    material = "\0".join(
        (
            _route_path(request),
            tenant_id,
            _client_identity(request),
            str(max_calls),
            str(window_seconds),
        )
    )
    digest = hashlib.sha256(material.encode()).hexdigest()
    return f"{_REDIS_KEY_PREFIX}:{digest}"


def _prune_bucket(bucket: _MemoryBucket, now: float) -> None:
    cutoff = now - bucket.window_seconds
    while bucket.hits and bucket.hits[0] <= cutoff:
        bucket.hits.popleft()


def _prune_expired_memory(now: float) -> None:
    for key, bucket in list(_HITS.items()):
        _prune_bucket(bucket, now)
        if not bucket.hits:
            del _HITS[key]


def _memory_allow(
    key: str,
    *,
    max_calls: int,
    window_seconds: int,
) -> bool:
    now = time.monotonic()
    max_keys = max(1, int(settings.rate_limit_memory_max_keys))
    with _MEMORY_LOCK:
        bucket = _HITS.get(key)
        if bucket is not None:
            _prune_bucket(bucket, now)
            if not bucket.hits:
                del _HITS[key]
                bucket = None

        if bucket is None:
            if len(_HITS) >= max_keys:
                _prune_expired_memory(now)
            # Never evict a live counter: that would let rotating client IDs
            # erase another caller's rate-limit history. The bounded fallback
            # fails closed for a new bucket while it is at capacity.
            if len(_HITS) >= max_keys:
                return False
            bucket = _MemoryBucket(hits=deque(), window_seconds=window_seconds)
            _HITS[key] = bucket
        else:
            _HITS.move_to_end(key)

        if len(bucket.hits) >= max_calls:
            return False
        bucket.hits.append(now)
        return True


def _get_redis_client() -> Redis:
    global _REDIS_CLIENT, _REDIS_CLIENT_URL
    if _REDIS_CLIENT is None or _REDIS_CLIENT_URL != settings.redis_url:
        _REDIS_CLIENT = Redis.from_url(
            settings.redis_url,
            decode_responses=False,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        )
        _REDIS_CLIENT_URL = settings.redis_url
    return _REDIS_CLIENT


async def _redis_allow(
    key: str,
    *,
    max_calls: int,
    window_seconds: int,
) -> bool:
    result = await _get_redis_client().eval(
        _REDIS_SLIDING_WINDOW,
        2,
        key,
        _REDIS_REGISTRY_KEY,
        str(max_calls),
        str(window_seconds),
        secrets.token_hex(12),
        str(settings.rate_limit_redis_max_keys),
    )
    return int(result) == 1


async def enforce_rate_limit(
    request: Request,
    *,
    max_calls: int,
    window_seconds: int,
    verified_tenant_id: str | None = None,
) -> None:
    """Enforce a limit, optionally using a tenant verified by the caller.

    ``verified_tenant_id`` is for signed webhook/OAuth routes whose tenant is
    authenticated by a route token rather than an OSAI session. Never pass a
    raw path, query, or body value here.
    """
    if max_calls < 1 or window_seconds < 1:
        raise ValueError("rate limits require positive max_calls and window_seconds")
    if verified_tenant_id is not None and not verified_tenant_id.strip():
        raise ValueError("verified_tenant_id must be non-empty")

    key = _rate_limit_key(
        request,
        max_calls=max_calls,
        window_seconds=window_seconds,
        verified_tenant_id=verified_tenant_id,
    )
    if settings.env.casefold() in {"local", "test"}:
        allowed = _memory_allow(
            key,
            max_calls=max_calls,
            window_seconds=window_seconds,
        )
    else:
        try:
            allowed = await _redis_allow(
                key,
                max_calls=max_calls,
                window_seconds=window_seconds,
            )
        except Exception as exc:  # noqa: BLE001 - shared limiter must fail closed
            logger.error("shared Redis rate limiter is unavailable", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=_UNAVAILABLE_DETAIL,
            ) from exc

    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=_LIMIT_DETAIL,
        )


def rate_limit(max_calls: int, window_seconds: int):
    """FastAPI dependency for a signed-tenant, client, and route budget."""
    if max_calls < 1 or window_seconds < 1:
        raise ValueError("rate limits require positive max_calls and window_seconds")

    async def _dependency(request: Request) -> None:
        await enforce_rate_limit(
            request,
            max_calls=max_calls,
            window_seconds=window_seconds,
        )

    _dependency.rate_limit_budget = (max_calls, window_seconds)  # type: ignore[attr-defined]

    return _dependency
