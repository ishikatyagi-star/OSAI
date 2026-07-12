"""Supermemory client: gating, sovereignty rule, fallback behaviour."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from memory import supermemory_client as sm


def test_disabled_without_key():
    with patch.object(sm.settings, "supermemory_api_key", None):
        assert not sm.enabled()
        assert sm.add_memory("org1", "fact") is False
        assert sm.search_memories("org1", "q") == []


def test_add_and_search_when_enabled():
    ok = MagicMock()
    ok.raise_for_status.return_value = None
    ok.json.return_value = {
        "results": [
            {"memory": "Deploys happen Fridays", "score": 0.9, "metadata": {"kind": "playbook"}}
        ]
    }
    with (
        patch.object(sm.settings, "supermemory_api_key", "sk-test", create=True),
        patch.object(sm.httpx, "post", return_value=ok) as post,
    ):
        assert sm.add_memory("org1", "Deploys happen Fridays", kind="playbook") is True
        body = post.call_args.kwargs["json"]
        assert body["containerTag"] == "org:org1"
        assert body["metadata"]["kind"] == "playbook"

        results = sm.search_memories("org1", "when do we deploy", requester_user_id="u1")
        assert results and results[0]["source"] == "supermemory"
        # Org pool + personal pool are both queried.
        tags = [c.kwargs["json"]["containerTag"] for c in post.call_args_list[1:]]
        assert tags == ["org:org1", "user:u1"]


def test_personal_memory_uses_user_container():
    ok = MagicMock()
    ok.raise_for_status.return_value = None
    with (
        patch.object(sm.settings, "supermemory_api_key", "sk-test", create=True),
        patch.object(sm.httpx, "post", return_value=ok) as post,
    ):
        sm.add_memory("org1", "I prefer terse answers", user_id="u1")
        assert post.call_args.kwargs["json"]["containerTag"] == "user:u1"


def test_cloud_refuses_non_normal_tier():
    with (
        patch.object(sm.settings, "supermemory_api_key", "sk-test", create=True),
        patch.object(sm.settings, "supermemory_url", None, create=True),
        patch.object(sm.httpx, "post") as post,
    ):
        assert sm.add_memory("org1", "salary bands", data_tier="red") is False
        post.assert_not_called()


def test_self_host_allows_higher_tiers():
    ok = MagicMock()
    ok.raise_for_status.return_value = None
    with (
        patch.object(sm.settings, "supermemory_api_key", "sk-test", create=True),
        patch.object(sm.settings, "supermemory_url", "http://sm.internal:8080", create=True),
        patch.object(sm.httpx, "post", return_value=ok),
    ):
        assert sm.add_memory("org1", "salary bands", data_tier="red") is True


def test_network_failure_returns_fallback_values():
    with (
        patch.object(sm.settings, "supermemory_api_key", "sk-test", create=True),
        patch.object(sm.httpx, "post", side_effect=OSError("boom")),
    ):
        assert sm.add_memory("org1", "fact") is False
        assert sm.search_memories("org1", "q") == []


def test_fetch_relevant_prefers_supermemory():
    from memory import org_memory

    with patch.object(
        sm,
        "search_memories",
        return_value=[{"kind": "fact", "content": "x", "score": 1.0, "source": "supermemory"}],
    ):
        out = org_memory.fetch_relevant("org1", "anything at all")
    assert out and out[0]["source"] == "supermemory"
