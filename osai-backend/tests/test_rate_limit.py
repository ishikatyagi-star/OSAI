from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from redis.asyncio import Redis
from starlette.requests import Request

import api.ratelimit as limiter
from config import Settings, settings


def _request(
    *,
    path: str = "/limited",
    client: str = "198.51.100.10",
    headers: dict[str, str] | None = None,
    header_pairs: list[tuple[str, str]] | None = None,
) -> Request:
    raw_headers = [
        (name.lower().encode("latin-1"), value.encode("latin-1"))
        for name, value in [*(headers or {}).items(), *(header_pairs or [])]
    ]
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": raw_headers,
            "client": (client, 12345),
            "server": ("testserver", 80),
        }
    )


def _token(org_id: str) -> str:
    return jwt.encode(
        {"sub": f"user-{org_id}", "org_id": org_id, "role": "admin"},
        settings.jwt_secret,
        algorithm="HS256",
    )


async def _status(dependency, request: Request) -> tuple[int, str | None]:
    try:
        await dependency(request)
    except HTTPException as exc:
        return exc.status_code, str(exc.detail)
    return 200, None


async def test_limits_are_isolated_by_signed_tenant_client_and_route(monkeypatch):
    monkeypatch.setattr(settings, "env", "local")
    dependency = limiter.rate_limit(max_calls=1, window_seconds=60)
    org_a = {"Authorization": f"Bearer {_token('org-a')}"}
    org_b = {"Authorization": f"Bearer {_token('org-b')}"}

    assert await _status(dependency, _request(headers=org_a)) == (200, None)
    assert (await _status(dependency, _request(headers=org_a)))[0] == 429
    assert await _status(dependency, _request(headers=org_b)) == (200, None)
    assert await _status(dependency, _request(client="198.51.100.11", headers=org_a)) == (200, None)
    assert await _status(dependency, _request(path="/another-route", headers=org_a)) == (200, None)


async def test_unsigned_tenant_header_cannot_rotate_the_bucket(monkeypatch):
    monkeypatch.setattr(settings, "env", "local")
    dependency = limiter.rate_limit(max_calls=1, window_seconds=60)

    first = _request(headers={"X-Org-Id": "org-a"})
    spoofed = _request(headers={"X-Org-Id": "org-b"})
    assert await _status(dependency, first) == (200, None)
    status_code, _ = await _status(dependency, spoofed)
    assert status_code == 429


async def test_memory_window_expires_and_reopens(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(settings, "env", "local")
    monkeypatch.setattr(limiter.time, "monotonic", lambda: clock[0])
    dependency = limiter.rate_limit(max_calls=2, window_seconds=10)
    request = _request()

    assert await _status(dependency, request) == (200, None)
    assert await _status(dependency, request) == (200, None)
    assert (await _status(dependency, request))[0] == 429

    clock[0] = 110.0
    assert await _status(dependency, request) == (200, None)


async def test_memory_fallback_has_a_hard_key_bound(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(settings, "env", "local")
    monkeypatch.setattr(settings, "rate_limit_memory_max_keys", 2)
    monkeypatch.setattr(limiter.time, "monotonic", lambda: clock[0])
    dependency = limiter.rate_limit(max_calls=1, window_seconds=10)

    assert await _status(dependency, _request(client="198.51.100.1")) == (200, None)
    assert await _status(dependency, _request(client="198.51.100.2")) == (200, None)
    assert (await _status(dependency, _request(client="198.51.100.3")))[0] == 429
    assert len(limiter._HITS) == 2

    clock[0] = 110.0
    assert await _status(dependency, _request(client="198.51.100.3")) == (200, None)
    assert len(limiter._HITS) <= 2


def test_memory_counter_is_thread_safe(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_memory_max_keys", 10)

    def attempt(_index: int) -> bool:
        return limiter._memory_allow(
            "shared-test-key",
            max_calls=5,
            window_seconds=60,
        )

    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(attempt, range(50)))
    assert sum(results) == 5
    assert len(limiter._HITS["shared-test-key"].hits) == 5


async def test_forwarded_addresses_require_a_trusted_direct_proxy(monkeypatch):
    monkeypatch.setattr(settings, "env", "local")
    monkeypatch.setattr(settings, "rate_limit_forwarded_for_mode", "direct")
    monkeypatch.setattr(settings, "rate_limit_trusted_proxy_cidrs", "")
    dependency = limiter.rate_limit(max_calls=1, window_seconds=60)

    first = _request(headers={"X-Forwarded-For": "198.51.100.1"})
    spoofed = _request(headers={"X-Forwarded-For": "198.51.100.2"})
    assert await _status(dependency, first) == (200, None)
    assert (await _status(dependency, spoofed))[0] == 429

    limiter._HITS.clear()
    monkeypatch.setattr(settings, "rate_limit_forwarded_for_mode", "trusted_chain")
    monkeypatch.setattr(settings, "rate_limit_trusted_proxy_cidrs", "10.0.0.0/8")
    through_proxy_a = _request(client="10.1.2.3", headers={"X-Forwarded-For": "198.51.100.1"})
    through_proxy_b = _request(client="10.1.2.3", headers={"X-Forwarded-For": "198.51.100.2"})
    assert await _status(dependency, through_proxy_a) == (200, None)
    assert await _status(dependency, through_proxy_b) == (200, None)
    assert (await _status(dependency, through_proxy_a))[0] == 429

    limiter._HITS.clear()
    # A compliant proxy appends the real client nearest to its own hop. Changing
    # an attacker-controlled value on the far left must not rotate the bucket.
    chain_a = _request(
        client="10.1.2.3",
        header_pairs=[
            ("X-Forwarded-For", "203.0.113.1, 198.51.100.20"),
            ("X-Forwarded-For", "10.2.3.4"),
        ],
    )
    chain_b = _request(
        client="10.1.2.3",
        header_pairs=[
            ("X-Forwarded-For", "203.0.113.2, 198.51.100.20"),
            ("X-Forwarded-For", "10.2.3.4"),
        ],
    )
    assert await _status(dependency, chain_a) == (200, None)
    assert (await _status(dependency, chain_b))[0] == 429


async def test_render_first_combines_duplicate_fields_in_wire_order(monkeypatch):
    monkeypatch.setattr(settings, "env", "local")
    monkeypatch.setattr(settings, "rate_limit_forwarded_for_mode", "render_first")
    dependency = limiter.rate_limit(max_calls=1, window_seconds=60)
    duplicate_fields = _request(
        client="10.1.2.3",
        header_pairs=[
            ("X-Forwarded-For", "invalid, 198.51.100.7"),
            ("X-Forwarded-For", "198.51.100.8"),
        ],
    )

    combined = limiter._combined_forwarded_addresses(duplicate_fields)
    assert [str(address) if address else None for address in combined] == [
        None,
        "198.51.100.7",
        "198.51.100.8",
    ]
    assert limiter._client_identity(duplicate_fields) == "198.51.100.7"
    assert await _status(dependency, duplicate_fields) == (200, None)
    same_client = _request(headers={"X-Forwarded-For": "198.51.100.7"})
    assert (await _status(dependency, same_client))[0] == 429


async def test_trusted_chain_rejects_a_malformed_duplicate_field(monkeypatch):
    monkeypatch.setattr(settings, "env", "local")
    monkeypatch.setattr(settings, "rate_limit_forwarded_for_mode", "trusted_chain")
    monkeypatch.setattr(settings, "rate_limit_trusted_proxy_cidrs", "10.0.0.0/8")
    dependency = limiter.rate_limit(max_calls=1, window_seconds=60)
    malformed = _request(
        client="10.1.2.3",
        header_pairs=[
            ("X-Forwarded-For", "198.51.100.7"),
            ("X-Forwarded-For", "invalid"),
        ],
    )

    assert limiter._client_identity(malformed) == "10.1.2.3"
    assert await _status(dependency, malformed) == (200, None)
    assert (await _status(dependency, _request(client="10.1.2.3")))[0] == 429


async def test_ipv6_clients_share_the_configured_prefix_bucket(monkeypatch):
    monkeypatch.setattr(settings, "env", "local")
    monkeypatch.setattr(settings, "rate_limit_forwarded_for_mode", "direct")
    monkeypatch.setattr(settings, "rate_limit_ipv6_prefix_length", 64)
    dependency = limiter.rate_limit(max_calls=1, window_seconds=60)

    assert await _status(dependency, _request(client="2001:db8:1::1")) == (200, None)
    assert (await _status(dependency, _request(client="2001:db8:1::abcd")))[0] == 429
    assert await _status(dependency, _request(client="2001:db8:2::1")) == (200, None)


async def test_redis_backend_is_shared_and_preserves_stable_429(monkeypatch):
    calls: list[tuple] = []

    class _FakeRedis:
        results = iter((1, 0))

        async def eval(self, *args):
            calls.append(args)
            return next(self.results)

    monkeypatch.setattr(settings, "env", "production")
    monkeypatch.setattr(limiter, "_get_redis_client", lambda: _FakeRedis())
    dependency = limiter.rate_limit(max_calls=1, window_seconds=60)
    request = _request(headers={"Authorization": f"Bearer {_token('org-a')}"})

    assert await _status(dependency, request) == (200, None)
    status_code, detail = await _status(dependency, request)
    assert status_code == 429
    assert detail == limiter._LIMIT_DETAIL
    assert calls[0][1] == 2
    assert calls[0][2] == calls[1][2]
    assert calls[0][3] == limiter._REDIS_REGISTRY_KEY
    assert calls[0][2].startswith(f"{limiter._REDIS_KEY_PREFIX}:")
    assert "org-a" not in calls[0][2]
    assert "198.51.100.10" not in calls[0][2]


async def test_redis_failure_fails_closed_without_using_local_memory(monkeypatch):
    class _BrokenRedis:
        async def eval(self, *_args):
            raise ConnectionError("redis unavailable")

    monkeypatch.setattr(settings, "env", "production")
    monkeypatch.setattr(limiter, "_get_redis_client", lambda: _BrokenRedis())
    dependency = limiter.rate_limit(max_calls=10, window_seconds=60)

    status_code, detail = await _status(dependency, _request())
    assert status_code == 503
    assert detail == limiter._UNAVAILABLE_DETAIL
    assert not limiter._HITS


async def test_local_fallback_never_requires_redis(monkeypatch):
    async def should_not_run(*_args, **_kwargs):
        raise AssertionError("local limiter attempted Redis")

    monkeypatch.setattr(settings, "env", "local")
    monkeypatch.setattr(limiter, "_redis_allow", should_not_run)
    dependency = limiter.rate_limit(max_calls=1, window_seconds=60)
    assert await _status(dependency, _request()) == (200, None)


def test_rate_limit_configuration_is_validated(monkeypatch):
    monkeypatch.delenv("RENDER", raising=False)
    configured = Settings(
        rate_limit_forwarded_for_mode="trusted_chain",
        rate_limit_trusted_proxy_cidrs="10.0.0.1, 2001:db8::1",
    )
    assert configured.rate_limit_trusted_proxy_cidrs == "10.0.0.1/32,2001:db8::1/128"

    with pytest.raises(ValidationError):
        Settings(
            rate_limit_forwarded_for_mode="trusted_chain",
            rate_limit_trusted_proxy_cidrs="not-a-network",
        )
    with pytest.raises(ValidationError):
        Settings(rate_limit_forwarded_for_mode="trusted_chain")
    with pytest.raises(ValidationError):
        Settings(rate_limit_trusted_proxy_cidrs="10.0.0.0/8")
    with pytest.raises(ValidationError):
        Settings(
            rate_limit_forwarded_for_mode="trusted_chain",
            rate_limit_trusted_proxy_cidrs="0.0.0.0/0",
        )
    with pytest.raises(ValidationError):
        Settings(rate_limit_forwarded_for_mode="render_first")
    monkeypatch.setenv("RENDER", "true")
    assert Settings(rate_limit_forwarded_for_mode="render_first")
    with pytest.raises(ValidationError):
        Settings(rate_limit_memory_max_keys=0)
    with pytest.raises(ValidationError):
        Settings(rate_limit_redis_max_keys=100_001)
    with pytest.raises(ValidationError):
        Settings(rate_limit_ipv6_prefix_length=31)
    with pytest.raises(ValidationError):
        Settings(rate_limit_ipv6_prefix_length=129)


async def _real_redis_or_skip() -> Redis:
    """Use only an explicitly local Redis; CI must provide it."""
    url = os.getenv("OSAI_TEST_REDIS_URL", settings.redis_url)
    if urlsplit(url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        pytest.skip("real rate-limit tests require an isolated local Redis")
    client = Redis.from_url(
        url,
        decode_responses=False,
        socket_connect_timeout=1.0,
        socket_timeout=1.0,
    )
    try:
        await client.ping()
    except Exception as exc:  # noqa: BLE001 - availability controls skip/fail
        await client.aclose()
        if os.getenv("CI"):
            pytest.fail(f"CI Redis service is unavailable: {type(exc).__name__}")
        pytest.skip("local Redis is unavailable")
    return client


async def test_real_redis_lua_is_atomic_and_reopens_after_expiry(monkeypatch):
    client = await _real_redis_or_skip()
    suffix = uuid4().hex
    key = f"{limiter._REDIS_KEY_PREFIX}:concurrency:{suffix}"
    registry = f"{limiter._REDIS_KEY_PREFIX}:active:{suffix}"
    monkeypatch.setattr(limiter, "_get_redis_client", lambda: client)
    monkeypatch.setattr(limiter, "_REDIS_REGISTRY_KEY", registry)
    monkeypatch.setattr(settings, "rate_limit_redis_max_keys", 10)

    try:
        results = await asyncio.gather(
            *(limiter._redis_allow(key, max_calls=5, window_seconds=1) for _ in range(30))
        )
        assert sum(results) == 5
        assert await client.zcard(key) == 5
        assert await client.zcard(registry) == 1
        assert 0 <= await client.ttl(key) <= 1
        assert 0 <= await client.ttl(registry) <= 1

        await asyncio.sleep(1.2)
        assert not await client.exists(registry)
        assert await limiter._redis_allow(key, max_calls=5, window_seconds=1)
        assert await client.zcard(key) == 1
        assert await client.zcard(registry) == 1
    finally:
        await client.delete(key, registry)
        await client.aclose()


async def test_real_redis_registry_bounds_and_prunes_active_keys(monkeypatch):
    client = await _real_redis_or_skip()
    suffix = uuid4().hex
    keys = [f"{limiter._REDIS_KEY_PREFIX}:capacity:{suffix}:{index}" for index in range(3)]
    registry = f"{limiter._REDIS_KEY_PREFIX}:active:{suffix}"
    monkeypatch.setattr(limiter, "_get_redis_client", lambda: client)
    monkeypatch.setattr(limiter, "_REDIS_REGISTRY_KEY", registry)
    monkeypatch.setattr(settings, "rate_limit_redis_max_keys", 2)

    try:
        assert await limiter._redis_allow(keys[0], max_calls=2, window_seconds=1)
        assert await limiter._redis_allow(keys[1], max_calls=2, window_seconds=1)
        assert not await limiter._redis_allow(keys[2], max_calls=2, window_seconds=1)
        assert not await client.exists(keys[2])
        # Capacity never evicts or blocks a live, already-registered identity.
        assert await limiter._redis_allow(keys[0], max_calls=2, window_seconds=1)
        assert await client.zcard(registry) == 2

        await asyncio.sleep(1.2)
        assert await limiter._redis_allow(keys[2], max_calls=2, window_seconds=1)
        assert await client.zcard(registry) == 1
    finally:
        await client.delete(*keys, registry)
        await client.aclose()


def test_invalid_limit_factory_arguments_are_rejected():
    with pytest.raises(ValueError):
        limiter.rate_limit(max_calls=0, window_seconds=60)
    with pytest.raises(ValueError):
        limiter.rate_limit(max_calls=1, window_seconds=0)
