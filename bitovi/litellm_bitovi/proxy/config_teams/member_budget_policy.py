"""Per-user budget policy for config teams (permanent / recurring / temp additive)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

POLICY_METADATA_KEY = "bitovi_budget_policy"
INHERITS_TEAM_MEMBER_BUDGET_KEY = "inherits_team_member_budget"


@dataclass(frozen=True, slots=True)
class MemberBudgetPolicy:
    permanent_max_budget: Optional[float] = None
    recurring_additive: float = 0.0
    temp_additive: float = 0.0
    temp_expires_at: Optional[datetime] = None


@dataclass(frozen=True, slots=True)
class EffectiveMemberBudget:
    team_default: Optional[float]
    base: Optional[float]
    recurring_additive: float
    temp_additive: float
    effective_max: Optional[float]
    using_team_default_base: bool
    temp_active: bool


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def _as_non_negative_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0 or number != number:  # NaN
        return None
    return number


def parse_member_budget_policy(metadata: Mapping[str, Any] | None) -> MemberBudgetPolicy:
    if not metadata:
        return MemberBudgetPolicy()
    raw = metadata.get(POLICY_METADATA_KEY)
    if not isinstance(raw, Mapping):
        return MemberBudgetPolicy()

    permanent = _as_non_negative_float(raw.get("permanent_max_budget"))
    recurring = _as_non_negative_float(raw.get("recurring_additive")) or 0.0
    temp = _as_non_negative_float(raw.get("temp_additive")) or 0.0
    expires = _parse_datetime(raw.get("temp_expires_at"))
    return MemberBudgetPolicy(
        permanent_max_budget=permanent,
        recurring_additive=recurring,
        temp_additive=temp,
        temp_expires_at=expires,
    )


def policy_to_metadata_dict(policy: MemberBudgetPolicy) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if policy.permanent_max_budget is not None:
        payload["permanent_max_budget"] = policy.permanent_max_budget
    if policy.recurring_additive:
        payload["recurring_additive"] = policy.recurring_additive
    if policy.temp_additive:
        payload["temp_additive"] = policy.temp_additive
    if policy.temp_expires_at is not None:
        payload["temp_expires_at"] = policy.temp_expires_at.astimezone(timezone.utc).isoformat()
    return payload


def merge_policy_into_membership_metadata(
    existing_metadata: Mapping[str, Any] | None,
    policy: MemberBudgetPolicy,
) -> dict[str, Any]:
    merged = dict(existing_metadata or {})
    policy_dict = policy_to_metadata_dict(policy)
    if policy_dict:
        merged[POLICY_METADATA_KEY] = policy_dict
    else:
        merged.pop(POLICY_METADATA_KEY, None)
    return merged


def compute_effective_max_budget(
    *,
    team_default: Optional[float],
    policy: MemberBudgetPolicy,
    now: Optional[datetime] = None,
) -> EffectiveMemberBudget:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)

    using_team_default_base = policy.permanent_max_budget is None
    base = team_default if using_team_default_base else policy.permanent_max_budget

    temp_active = False
    active_temp = 0.0
    if policy.temp_additive > 0:
        if policy.temp_expires_at is None or policy.temp_expires_at > current:
            temp_active = True
            active_temp = policy.temp_additive

    if base is None:
        return EffectiveMemberBudget(
            team_default=team_default,
            base=None,
            recurring_additive=policy.recurring_additive,
            temp_additive=active_temp,
            effective_max=None,
            using_team_default_base=using_team_default_base,
            temp_active=temp_active,
        )

    effective = base + policy.recurring_additive + active_temp
    return EffectiveMemberBudget(
        team_default=team_default,
        base=base,
        recurring_additive=policy.recurring_additive,
        temp_additive=active_temp,
        effective_max=effective,
        using_team_default_base=using_team_default_base,
        temp_active=temp_active,
    )


def effective_to_breakdown_dict(effective: EffectiveMemberBudget) -> dict[str, Any]:
    return {
        "team_default": effective.team_default,
        "base": effective.base,
        "recurring_additive": effective.recurring_additive,
        "temp_additive": effective.temp_additive,
        "effective_max": effective.effective_max,
        "using_team_default_base": effective.using_team_default_base,
        "temp_active": effective.temp_active,
    }


def apply_policy_update(
    *,
    existing: MemberBudgetPolicy,
    permanent_max_budget: Optional[float] = None,
    recurring_additive: Optional[float] = None,
    temp_additive: Optional[float] = None,
    temp_expires_at: Optional[datetime] = None,
    clear_temp: bool = False,
    clear_permanent: bool = False,
    clear_recurring: bool = False,
) -> MemberBudgetPolicy:
    permanent = existing.permanent_max_budget
    recurring = existing.recurring_additive
    temp = existing.temp_additive
    expires = existing.temp_expires_at

    if clear_permanent:
        permanent = None
    elif permanent_max_budget is not None:
        parsed = _as_non_negative_float(permanent_max_budget)
        if parsed is None:
            raise ValueError("permanent_max_budget must be a non-negative number")
        permanent = parsed

    if clear_recurring:
        recurring = 0.0
    elif recurring_additive is not None:
        parsed = _as_non_negative_float(recurring_additive)
        if parsed is None:
            raise ValueError("recurring_additive must be a non-negative number")
        recurring = parsed

    if clear_temp:
        temp = 0.0
        expires = None
    elif temp_additive is not None:
        parsed = _as_non_negative_float(temp_additive)
        if parsed is None:
            raise ValueError("temp_additive must be a non-negative number")
        temp = parsed
        expires = temp_expires_at

    return MemberBudgetPolicy(
        permanent_max_budget=permanent,
        recurring_additive=recurring,
        temp_additive=temp,
        temp_expires_at=expires,
    )
