from db.approval_policy import approval_policy, may_approve


def test_approval_policy_defaults_and_separation_setting():
    assert approval_policy({}) == {"approver_role": "admin", "require_separate_approver": False}
    policy = approval_policy({"approval_policy": {"approver_role": "member", "require_separate_approver": True}})
    assert may_approve("member", policy)
    assert may_approve("admin", policy)
