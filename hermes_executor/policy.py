"""Permission policy and command blocking for sandboxed execution."""

from __future__ import annotations

from .models import PermissionTier


# Commands that are always blocked at the run-commands tier or below.
DESTRUCTIVE_PATTERNS: tuple[str, ...] = (
    "rm -rf",
    "rm -r /",
    "mkfs",
    "dd if=",
    ":(){ :|:& };:",
    "shutdown",
    "reboot",
    "halt",
    "poweroff",
    "iptables",
    "mkfs.ext",
    "mkfs.xfs",
    "mkfs.btrfs",
    "deluser",
    "delgroup",
)


def tier_rank(tier: PermissionTier) -> int:
    return {
        PermissionTier.READ_ONLY: 1,
        PermissionTier.WRITE_CODE: 2,
        PermissionTier.RUN_COMMANDS: 3,
        PermissionTier.DEPLOY_PROVISION: 4,
        PermissionTier.MONEY_LEGAL: 5,
    }[tier]


def is_destructive(command: list[str]) -> tuple[bool, str | None]:
    """Check if a shell command is destructive and should be blocked."""
    cmd_str = " ".join(command)
    for pattern in DESTRUCTIVE_PATTERNS:
        if pattern in cmd_str:
            return True, f"Destructive pattern '{pattern}' is blocked"
    return False, None


def can_exec(tier: PermissionTier, command: list[str]) -> tuple[bool, str | None]:
    if tier_rank(tier) < tier_rank(PermissionTier.RUN_COMMANDS):
        return False, f"Tier '{tier}' cannot execute shell commands"
    destructive, reason = is_destructive(command)
    if destructive:
        return False, reason
    return True, None


def can_write(tier: PermissionTier) -> tuple[bool, str | None]:
    if tier_rank(tier) < tier_rank(PermissionTier.WRITE_CODE):
        return False, f"Tier '{tier}' cannot write files"
    return True, None


def can_deploy(tier: PermissionTier) -> tuple[bool, str | None]:
    if tier_rank(tier) < tier_rank(PermissionTier.DEPLOY_PROVISION):
        return False, f"Tier '{tier}' cannot deploy or provision infrastructure"
    return True, None


def requires_human_approval(tier: PermissionTier) -> bool:
    return tier in (PermissionTier.DEPLOY_PROVISION, PermissionTier.MONEY_LEGAL)
