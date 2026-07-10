from __future__ import annotations

APPROVER_ROLES = {"admin", "member"}


def approval_policy(data_routing: dict | None) -> dict[str, object]:
    stored = (data_routing or {}).get("approval_policy") or {}
    role = stored.get("approver_role")
    return {
        "approver_role": role if role in APPROVER_ROLES else "admin",
        "require_separate_approver": bool(stored.get("require_separate_approver", False)),
    }


def may_approve(user_role: str, policy: dict[str, object]) -> bool:
    return user_role == "admin" or user_role == policy["approver_role"]
