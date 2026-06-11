import pytest

from nano_agent.config import AgentConfig
from nano_agent.hooks.registry import build_default_hooks
from nano_agent.models import ApprovalLevel
from nano_agent.permissions.policy import PermissionHook, PermissionPolicy


@pytest.mark.parametrize(
    "level",
    [
        ApprovalLevel.READ,
        ApprovalLevel.NETWORK,
        ApprovalLevel.EXECUTE_SAFE,
    ],
)
def test_default_policy_allows_non_sensitive_levels(level: ApprovalLevel) -> None:
    assert not PermissionPolicy().requires_approval(level)


@pytest.mark.parametrize(
    "level",
    [
        ApprovalLevel.EXECUTE_RISKY,
        ApprovalLevel.WRITE,
        ApprovalLevel.PUBLISH,
    ],
)
def test_default_policy_requires_approval_for_sensitive_levels(level: ApprovalLevel) -> None:
    assert PermissionPolicy().requires_approval(level)


def test_auto_approve_only_adds_risky_execution() -> None:
    hook = build_default_hooks(AgentConfig(auto_approve=True))[0]

    assert isinstance(hook, PermissionHook)
    assert not hook.policy.requires_approval(ApprovalLevel.EXECUTE_RISKY)
    assert hook.policy.requires_approval(ApprovalLevel.WRITE)
    assert hook.policy.requires_approval(ApprovalLevel.PUBLISH)


def test_default_hook_allows_clone_and_safe_execution() -> None:
    hook = build_default_hooks(AgentConfig())[0]

    assert isinstance(hook, PermissionHook)
    assert not hook.policy.requires_approval(ApprovalLevel.NETWORK)
    assert not hook.policy.requires_approval(ApprovalLevel.EXECUTE_SAFE)
    assert hook.policy.requires_approval(ApprovalLevel.EXECUTE_RISKY)
