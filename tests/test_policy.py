"""Tests for executor permission policy."""

from __future__ import annotations

import pytest

from hermes_executor.models import PermissionTier
from hermes_executor.policy import can_deploy, can_exec, can_write, is_destructive


def test_read_only_cannot_exec():
    allowed, reason = can_exec(PermissionTier.READ_ONLY, ["ls", "-la"])
    assert not allowed
    assert "read-only" in reason.lower()


def test_run_commands_allows_ls():
    allowed, reason = can_exec(PermissionTier.RUN_COMMANDS, ["ls", "-la"])
    assert allowed
    assert reason is None


def test_destructive_rm_blocked():
    destructive, reason = is_destructive(["rm", "-rf", "/"])
    assert destructive
    assert "rm -rf" in reason


def test_deploy_requires_tier():
    allowed, reason = can_deploy(PermissionTier.RUN_COMMANDS)
    assert not allowed
    assert "deploy" in reason.lower()


def test_write_requires_write_code_tier():
    allowed, reason = can_write(PermissionTier.READ_ONLY)
    assert not allowed
    assert "write" in reason.lower()

    allowed, _ = can_write(PermissionTier.WRITE_CODE)
    assert allowed
