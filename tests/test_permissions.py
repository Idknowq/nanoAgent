import pytest

from nano_agent.config import AgentConfig
from nano_agent.hooks.audit import AuditHook
from nano_agent.hooks.console import ConsoleProgressHook
from nano_agent.hooks.llm_metrics import LLMMetricsHook
from nano_agent.hooks.permission import PermissionHook, PermissionPolicy
from nano_agent.hooks.registry import build_default_hooks
from nano_agent.models import ApprovalLevel


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


def test_allow_command_only_adds_risky_execution() -> None:
    hook = build_default_hooks(AgentConfig(allow_command=True))[0]

    assert isinstance(hook, PermissionHook)
    assert not hook.policy.requires_approval(ApprovalLevel.EXECUTE_RISKY)
    assert hook.policy.requires_approval(ApprovalLevel.WRITE)
    assert hook.policy.requires_approval(ApprovalLevel.PUBLISH)


def test_allow_write_only_adds_write_permission() -> None:
    hook = build_default_hooks(AgentConfig(allow_write=True))[0]

    assert isinstance(hook, PermissionHook)
    assert not hook.policy.requires_approval(ApprovalLevel.WRITE)
    assert hook.policy.requires_approval(ApprovalLevel.EXECUTE_RISKY)
    assert hook.policy.requires_approval(ApprovalLevel.PUBLISH)


def test_allow_flags_can_be_combined() -> None:
    hook = build_default_hooks(AgentConfig(allow_command=True, allow_write=True))[0]

    assert isinstance(hook, PermissionHook)
    assert not hook.policy.requires_approval(ApprovalLevel.EXECUTE_RISKY)
    assert not hook.policy.requires_approval(ApprovalLevel.WRITE)
    assert hook.policy.requires_approval(ApprovalLevel.PUBLISH)


def test_default_hook_allows_clone_and_safe_execution() -> None:
    hook = build_default_hooks(AgentConfig())[0]

    assert isinstance(hook, PermissionHook)
    assert not hook.policy.requires_approval(ApprovalLevel.NETWORK)
    assert not hook.policy.requires_approval(ApprovalLevel.EXECUTE_SAFE)
    assert hook.policy.requires_approval(ApprovalLevel.EXECUTE_RISKY)


def test_default_hooks_include_observability_hooks() -> None:
    hooks = build_default_hooks(AgentConfig())

    assert isinstance(hooks[0], PermissionHook)
    assert isinstance(hooks[1], ConsoleProgressHook)
    assert isinstance(hooks[2], LLMMetricsHook)
    assert isinstance(hooks[3], AuditHook)


def test_audit_hook_can_be_disabled() -> None:
    hooks = build_default_hooks(AgentConfig(audit_enabled=False))

    assert not any(isinstance(hook, AuditHook) for hook in hooks)


def test_llm_metrics_hook_can_be_disabled() -> None:
    hooks = build_default_hooks(AgentConfig(llm_calls_enabled=False))

    assert not any(isinstance(hook, LLMMetricsHook) for hook in hooks)


def test_console_progress_hook_can_be_disabled() -> None:
    hooks = build_default_hooks(AgentConfig(console_progress_enabled=False))

    assert not any(isinstance(hook, ConsoleProgressHook) for hook in hooks)
    assert isinstance(hooks[0], PermissionHook)
    assert isinstance(hooks[1], LLMMetricsHook)
    assert isinstance(hooks[2], AuditHook)
