"""Unit tests for config-team per-user additive budget policy."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from litellm_bitovi.proxy.config_teams.member_budget_policy import (
    MemberBudgetPolicy,
    apply_policy_update,
    compute_effective_max_budget,
    parse_member_budget_policy,
)


def test_default_only() -> None:
    result = compute_effective_max_budget(
        team_default=100.0,
        policy=MemberBudgetPolicy(),
    )
    assert result.effective_max == 100.0
    assert result.base == 100.0
    assert result.using_team_default_base is True


def test_recurring_additive_follows_team_default_raise() -> None:
    policy = MemberBudgetPolicy(recurring_additive=100.0)
    at_100 = compute_effective_max_budget(team_default=100.0, policy=policy)
    assert at_100.effective_max == 200.0

    at_150 = compute_effective_max_budget(team_default=150.0, policy=policy)
    assert at_150.effective_max == 250.0


def test_temp_additive_clears_after_expiry() -> None:
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    policy = MemberBudgetPolicy(
        recurring_additive=100.0,
        temp_additive=50.0,
        temp_expires_at=now + timedelta(days=1),
    )
    active = compute_effective_max_budget(team_default=100.0, policy=policy, now=now)
    assert active.effective_max == 250.0
    assert active.temp_active is True

    expired = compute_effective_max_budget(
        team_default=100.0,
        policy=policy,
        now=now + timedelta(days=2),
    )
    assert expired.effective_max == 200.0
    assert expired.temp_active is False
    assert expired.temp_additive == 0.0


def test_permanent_base_ignores_team_default() -> None:
    policy = MemberBudgetPolicy(permanent_max_budget=80.0, recurring_additive=100.0)
    result = compute_effective_max_budget(team_default=150.0, policy=policy)
    assert result.base == 80.0
    assert result.effective_max == 180.0
    assert result.using_team_default_base is False


def test_parse_and_apply_policy_update() -> None:
    existing = parse_member_budget_policy(
        {"bitovi_budget_policy": {"recurring_additive": 25}}
    )
    assert existing.recurring_additive == 25.0

    updated = apply_policy_update(
        existing=existing,
        temp_additive=50.0,
        temp_expires_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    assert updated.recurring_additive == 25.0
    assert updated.temp_additive == 50.0

    cleared = apply_policy_update(existing=updated, clear_temp=True, clear_recurring=True)
    assert cleared.temp_additive == 0.0
    assert cleared.recurring_additive == 0.0
    assert cleared.temp_expires_at is None
