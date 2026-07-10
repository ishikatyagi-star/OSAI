from policy import allowed_tiers, can_access


def test_policy_gate_combines_permission_and_tier_checks():
    assert allowed_tiers("amber") == ["normal", "amber"]
    assert can_access(["department:engineering"], "amber", ["department:engineering"], "amber")
    assert not can_access(["department:engineering"], "red", ["department:engineering"], "amber")
    assert not can_access(["department:engineering"], "normal", ["department:sales"], "red")
