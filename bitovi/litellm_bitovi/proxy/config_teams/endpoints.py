"""Admin API for per-user config-team budget policy (permanent / recurring / temp)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from litellm.proxy._types import LitellmUserRoles, UserAPIKeyAuth
from litellm.proxy.auth.user_api_key_auth import user_api_key_auth
from litellm.proxy.management_endpoints.common_utils import _is_user_team_admin
from litellm_bitovi.proxy.config_teams.member_budget_policy import (
    apply_policy_update,
    compute_effective_max_budget,
    effective_to_breakdown_dict,
    merge_policy_into_membership_metadata,
    parse_member_budget_policy,
)
from litellm_bitovi.proxy.config_teams.sync import team_is_from_config

router = APIRouter(prefix="/bitovi/team", tags=["bitovi-team-budget"])


class MemberBudgetPolicyUpdateRequest(BaseModel):
    permanent_max_budget: Optional[float] = Field(
        default=None,
        description="Permanent base override (replaces team default as base)",
    )
    recurring_additive: Optional[float] = Field(
        default=None,
        description="Additive amount applied every cycle on top of base",
    )
    temp_additive: Optional[float] = Field(
        default=None,
        description="One-shot additive until end of current cycle",
    )
    clear_temp: bool = False
    clear_permanent: bool = False
    clear_recurring: bool = False


class MemberBudgetPolicyResponse(BaseModel):
    team_id: str
    user_id: str
    team_default: Optional[float] = None
    policy: dict[str, Any]
    breakdown: dict[str, Any]
    effective_max: Optional[float] = None


def _require_team_admin(*, user_api_key_dict: UserAPIKeyAuth, team_obj: Any) -> None:
    if user_api_key_dict.user_role in {
        LitellmUserRoles.PROXY_ADMIN,
        LitellmUserRoles.PROXY_ADMIN.value,
    }:
        return
    if _is_user_team_admin(user_api_key_dict=user_api_key_dict, team_obj=team_obj):
        return
    raise HTTPException(status_code=403, detail="Proxy admin or team admin required")


async def _load_team_and_membership(*, team_id: str, user_id: str, prisma_client: Any) -> tuple[Any, Any]:
    from litellm.proxy._types import LiteLLM_TeamTable
    from litellm.repositories.table_repositories import TeamMembershipRepository
    from litellm.repositories.team_repository import TeamRepository

    team_row = await TeamRepository(prisma_client).table.find_unique(where={"team_id": team_id})
    if team_row is None:
        raise HTTPException(status_code=404, detail=f"Team not found: {team_id}")
    team_obj = LiteLLM_TeamTable(**team_row.model_dump()) if hasattr(team_row, "model_dump") else team_row
    metadata = team_obj.metadata if isinstance(getattr(team_obj, "metadata", None), dict) else None
    if not team_is_from_config(metadata):
        raise HTTPException(
            status_code=400,
            detail="Budget policy API is only available for config-managed teams (is_from_config)",
        )

    membership = await TeamMembershipRepository(prisma_client).table.find_unique(
        where={"user_id_team_id": {"user_id": user_id, "team_id": team_id}},
    )
    if membership is None:
        raise HTTPException(
            status_code=404,
            detail=f"Team membership not found for user_id={user_id} team_id={team_id}",
        )
    return team_obj, membership


async def _team_default_max_budget(*, team_obj: Any, prisma_client: Any) -> tuple[Optional[float], Optional[datetime]]:
    from litellm.repositories.budget_repository import BudgetRepository

    metadata = team_obj.metadata if isinstance(getattr(team_obj, "metadata", None), dict) else {}
    budget_id = metadata.get("team_member_budget_id")
    if not isinstance(budget_id, str):
        return None, None
    budget_row = await BudgetRepository(prisma_client).table.find_unique(where={"budget_id": budget_id})
    if budget_row is None:
        return None, None
    reset_at = getattr(budget_row, "budget_reset_at", None)
    return getattr(budget_row, "max_budget", None), reset_at


def _build_response(
    *,
    team_id: str,
    user_id: str,
    team_default: Optional[float],
    membership_metadata: Any,
) -> MemberBudgetPolicyResponse:
    from litellm_bitovi.proxy.config_teams.member_budget_policy import policy_to_metadata_dict

    policy = parse_member_budget_policy(membership_metadata if isinstance(membership_metadata, dict) else None)
    breakdown = compute_effective_max_budget(team_default=team_default, policy=policy)
    return MemberBudgetPolicyResponse(
        team_id=team_id,
        user_id=user_id,
        team_default=team_default,
        policy=policy_to_metadata_dict(policy),
        breakdown=effective_to_breakdown_dict(breakdown),
        effective_max=breakdown.effective_max,
    )


@router.get("/{team_id}/members/{user_id}/budget-policy", response_model=MemberBudgetPolicyResponse)
async def get_member_budget_policy(
    team_id: str,
    user_id: str,
    user_api_key_dict: UserAPIKeyAuth = Depends(user_api_key_auth),
) -> MemberBudgetPolicyResponse:
    from litellm.proxy.proxy_server import prisma_client

    if prisma_client is None:
        raise HTTPException(status_code=500, detail="Prisma client not initialized")

    team_obj, membership = await _load_team_and_membership(
        team_id=team_id,
        user_id=user_id,
        prisma_client=prisma_client,
    )
    _require_team_admin(user_api_key_dict=user_api_key_dict, team_obj=team_obj)
    team_default, _reset = await _team_default_max_budget(team_obj=team_obj, prisma_client=prisma_client)
    return _build_response(
        team_id=team_id,
        user_id=user_id,
        team_default=team_default,
        membership_metadata=getattr(membership, "metadata", None),
    )


@router.put("/{team_id}/members/{user_id}/budget-policy", response_model=MemberBudgetPolicyResponse)
async def put_member_budget_policy(
    team_id: str,
    user_id: str,
    data: MemberBudgetPolicyUpdateRequest,
    user_api_key_dict: UserAPIKeyAuth = Depends(user_api_key_auth),
) -> MemberBudgetPolicyResponse:
    from litellm.proxy.proxy_server import prisma_client, user_api_key_cache
    from litellm.repositories.table_repositories import TeamMembershipRepository

    if prisma_client is None:
        raise HTTPException(status_code=500, detail="Prisma client not initialized")

    team_obj, membership = await _load_team_and_membership(
        team_id=team_id,
        user_id=user_id,
        prisma_client=prisma_client,
    )
    _require_team_admin(user_api_key_dict=user_api_key_dict, team_obj=team_obj)
    team_default, budget_reset_at = await _team_default_max_budget(
        team_obj=team_obj,
        prisma_client=prisma_client,
    )

    existing_metadata = getattr(membership, "metadata", None)
    if isinstance(existing_metadata, str):
        try:
            existing_metadata = json.loads(existing_metadata)
        except Exception:
            existing_metadata = {}
    if not isinstance(existing_metadata, dict):
        existing_metadata = {}

    existing_policy = parse_member_budget_policy(existing_metadata)
    temp_expires_at = None
    if data.temp_additive is not None and not data.clear_temp:
        if isinstance(budget_reset_at, datetime):
            temp_expires_at = (
                budget_reset_at
                if budget_reset_at.tzinfo is not None
                else budget_reset_at.replace(tzinfo=timezone.utc)
            )
        else:
            temp_expires_at = datetime.now(timezone.utc)

    try:
        updated_policy = apply_policy_update(
            existing=existing_policy,
            permanent_max_budget=data.permanent_max_budget,
            recurring_additive=data.recurring_additive,
            temp_additive=data.temp_additive,
            temp_expires_at=temp_expires_at,
            clear_temp=data.clear_temp,
            clear_permanent=data.clear_permanent,
            clear_recurring=data.clear_recurring,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    new_metadata = merge_policy_into_membership_metadata(existing_metadata, updated_policy)
    from litellm_bitovi.proxy.config_teams.membership_metadata import (
        invalidate_team_membership_auth_caches,
        metadata_for_prisma_write,
    )

    # Store a JSON object (prisma.Json(dict)), never json.dumps(str), so reads
    # return a dict and LiteLLM_TeamMembership / budget policy keep working.
    updated = await TeamMembershipRepository(prisma_client).table.update(
        where={"user_id_team_id": {"user_id": user_id, "team_id": team_id}},
        data={"metadata": metadata_for_prisma_write(new_metadata)},
    )
    await invalidate_team_membership_auth_caches(
        user_api_key_cache=user_api_key_cache,
        user_id=user_id,
        team_id=team_id,
    )

    updated_metadata = getattr(updated, "metadata", new_metadata)
    if isinstance(updated_metadata, str):
        try:
            updated_metadata = json.loads(updated_metadata)
        except Exception:
            updated_metadata = new_metadata

    return _build_response(
        team_id=team_id,
        user_id=user_id,
        team_default=team_default,
        membership_metadata=updated_metadata,
    )
