"""Config teams inherit team_member_budget; per-user additive policy on top."""

from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple

from litellm._logging import verbose_proxy_logger
from litellm_bitovi.proxy.config_teams.member_budget_policy import (
    INHERITS_TEAM_MEMBER_BUDGET_KEY,
    compute_effective_max_budget,
    effective_to_breakdown_dict,
    parse_member_budget_policy,
)
from litellm_bitovi.proxy.config_teams.membership_metadata import (
    coerce_membership_metadata,
)
from litellm_bitovi.proxy.config_teams.sync import team_is_from_config


def config_team_forces_member_budget_inheritance(metadata: Mapping[str, Any] | None) -> bool:
    return team_is_from_config(metadata)


def _team_member_budget_id(metadata: Mapping[str, Any] | None) -> Optional[str]:
    if not metadata:
        return None
    budget_id = metadata.get("team_member_budget_id")
    return budget_id if isinstance(budget_id, str) else None


def _membership_metadata(membership: Any) -> Mapping[str, Any] | None:
    if membership is None:
        return None
    return coerce_membership_metadata(getattr(membership, "metadata", None))


async def effective_team_member_max_budget_for_auth(
    *,
    team_metadata: Mapping[str, Any] | None,
    membership: Any,
    prisma_client: Any,
    user_api_key_cache: Any = None,
    linked_budget_max: Optional[float] = None,
) -> Optional[float]:
    """
    Max budget for the early team-member check in user_api_key_auth.

    Config teams must not use the shared LiteLLM_BudgetTable.max_budget alone
    (team default); permanent/recurring/temp additives live on membership metadata.
    """
    if config_team_forces_member_budget_inheritance(team_metadata):
        effective_budget, _using_default, _breakdown = await resolve_config_team_member_budget(
            team_metadata=team_metadata,
            prisma_client=prisma_client,
            user_api_key_cache=user_api_key_cache,
            membership=membership,
        )
        if (
            effective_budget is not None
            and effective_budget.max_budget is not None
            and effective_budget.max_budget > 0
        ):
            return effective_budget.max_budget
        return None
    if linked_budget_max is not None and linked_budget_max > 0:
        return linked_budget_max
    return None


async def resolve_config_team_member_budget(
    *,
    team_metadata: Mapping[str, Any] | None,
    prisma_client: Any,
    user_api_key_cache: Any = None,
    membership: Any = None,
) -> Tuple[Any, bool, Optional[dict[str, Any]]]:
    """
    Return shared team_member_budget with per-user policy applied to max_budget.

    Always reads the shared budget row from the DB. Permanent / recurring / temp
    additives come from membership.metadata.bitovi_budget_policy.
    """
    from litellm.proxy._types import LiteLLM_BudgetTable
    from litellm.repositories.budget_repository import BudgetRepository

    budget_id = _team_member_budget_id(team_metadata)
    if budget_id is None or prisma_client is None:
        return None, False, None

    budget_record = await BudgetRepository(prisma_client).table.find_unique(where={"budget_id": budget_id})
    if budget_record is None:
        verbose_proxy_logger.warning(
            "Config team member budget not found: budget_id=%s",
            budget_id,
        )
        return None, False, None

    budget = LiteLLM_BudgetTable(**budget_record.dict())
    if user_api_key_cache is not None:
        cache_key = f"team_member_default_budget:{budget_id}"
        try:
            from litellm.proxy.common_utils.user_api_key_cache import get_management_object_ttl

            await user_api_key_cache.async_set_cache(
                key=cache_key,
                value=budget,
                model_type=LiteLLM_BudgetTable,
                ttl=get_management_object_ttl(user_api_key_cache),
            )
        except Exception:
            verbose_proxy_logger.debug(
                "Failed to refresh team_member_default_budget cache for %s",
                budget_id,
                exc_info=True,
            )

    policy = parse_member_budget_policy(_membership_metadata(membership))
    effective = compute_effective_max_budget(
        team_default=budget.max_budget,
        policy=policy,
    )
    breakdown = effective_to_breakdown_dict(effective)

    if effective.effective_max is None:
        return budget, True, breakdown

    patched = budget.model_copy(update={"max_budget": effective.effective_max})
    using_team_default = effective.using_team_default_base and not (
        effective.recurring_additive or effective.temp_additive
    )
    return patched, using_team_default, breakdown


async def enforce_config_team_member_budget_inheritance(
    *,
    team_id: str,
    prisma_client: Any,
    user_api_key_cache: Any = None,
) -> None:
    """
    Point every membership at the shared team_member_budget_id, refresh inheriting
    keys to the current team default, and drop stale caches.
    """
    from litellm.repositories.table_repositories import TeamMembershipRepository
    from litellm.repositories.team_repository import TeamRepository

    if prisma_client is None:
        return

    team = await TeamRepository(prisma_client).table.find_unique(where={"team_id": team_id})
    if team is None:
        return

    metadata = team.metadata if isinstance(team.metadata, dict) else None
    if not config_team_forces_member_budget_inheritance(metadata):
        return

    budget_id = _team_member_budget_id(metadata)
    if budget_id is None:
        return

    membership_repo = TeamMembershipRepository(prisma_client)
    memberships = await membership_repo.table.find_many(where={"team_id": team_id})
    updated = await membership_repo.table.update_many(
        where={"team_id": team_id},
        data={"budget_id": budget_id},
    )
    if updated:
        verbose_proxy_logger.info(
            "Config team %s: linked %s memberships to team_member_budget_id=%s",
            team_id,
            updated,
            budget_id,
        )

    await refresh_inheriting_keys_for_team(
        team_id=team_id,
        prisma_client=prisma_client,
        user_api_key_cache=user_api_key_cache,
    )

    if user_api_key_cache is None:
        return

    try:
        await user_api_key_cache.async_delete_cache(key=f"team_member_default_budget:{budget_id}")
    except Exception:
        verbose_proxy_logger.debug(
            "Failed to invalidate team_member_default_budget cache for %s",
            budget_id,
            exc_info=True,
        )

    for membership in memberships:
        user_id = getattr(membership, "user_id", None)
        if not isinstance(user_id, str):
            continue
        try:
            await user_api_key_cache.async_delete_cache(key=f"team_membership:{user_id}:{team_id}")
        except Exception:
            verbose_proxy_logger.debug(
                "Failed to invalidate team_membership cache for user=%s team=%s",
                user_id,
                team_id,
                exc_info=True,
            )


async def refresh_inheriting_keys_for_team(
    *,
    team_id: str,
    prisma_client: Any,
    user_api_key_cache: Any = None,
) -> int:
    """Update max_budget on keys marked inherits_team_member_budget for this team."""
    from litellm.proxy._types import LiteLLM_BudgetTable
    from litellm.repositories.budget_repository import BudgetRepository
    from litellm.repositories.team_repository import TeamRepository

    if prisma_client is None:
        return 0

    team = await TeamRepository(prisma_client).table.find_unique(where={"team_id": team_id})
    if team is None:
        return 0
    metadata = team.metadata if isinstance(team.metadata, dict) else None
    budget_id = _team_member_budget_id(metadata)
    if budget_id is None:
        return 0

    budget_record = await BudgetRepository(prisma_client).table.find_unique(where={"budget_id": budget_id})
    if budget_record is None:
        return 0
    budget = LiteLLM_BudgetTable(**budget_record.dict())
    if budget.max_budget is None:
        return 0

    keys = await prisma_client.db.litellm_verificationtoken.find_many(where={"team_id": team_id})
    refreshed = 0
    for key in keys:
        key_metadata = getattr(key, "metadata", None) or {}
        if not isinstance(key_metadata, dict):
            continue
        if key_metadata.get(INHERITS_TEAM_MEMBER_BUDGET_KEY) is not True:
            continue
        token = getattr(key, "token", None)
        if not isinstance(token, str):
            continue
        update_data: dict[str, Any] = {"max_budget": budget.max_budget}
        if budget.budget_duration is not None:
            update_data["budget_duration"] = budget.budget_duration
        await prisma_client.db.litellm_verificationtoken.update(
            where={"token": token},
            data=update_data,
        )
        refreshed += 1
        if user_api_key_cache is not None:
            try:
                await user_api_key_cache.async_delete_cache(key=token)
            except Exception:
                verbose_proxy_logger.debug(
                    "Failed to invalidate key cache for token after budget refresh",
                    exc_info=True,
                )

    if refreshed:
        verbose_proxy_logger.info(
            "Config team %s: refreshed max_budget=%s on %s inheriting keys",
            team_id,
            budget.max_budget,
            refreshed,
        )
    return refreshed


async def resolve_inheriting_key_max_budget(
    *,
    valid_token: Any,
    prisma_client: Any,
    user_api_key_cache: Any = None,
) -> Optional[float]:
    """Live-resolve max_budget for keys that inherit the team member default."""
    metadata = getattr(valid_token, "metadata", None) or {}
    if not isinstance(metadata, Mapping) or metadata.get(INHERITS_TEAM_MEMBER_BUDGET_KEY) is not True:
        return None

    team_id = getattr(valid_token, "team_id", None)
    if not isinstance(team_id, str) or prisma_client is None:
        return None

    from litellm.repositories.team_repository import TeamRepository

    team = await TeamRepository(prisma_client).table.find_unique(where={"team_id": team_id})
    if team is None:
        return None
    team_metadata = team.metadata if isinstance(team.metadata, dict) else None
    if not config_team_forces_member_budget_inheritance(team_metadata):
        # Still allow inheritance marker to follow team_member_budget_id when present
        pass

    user_id = getattr(valid_token, "user_id", None)
    membership = None
    if isinstance(user_id, str):
        from litellm.repositories.table_repositories import TeamMembershipRepository

        membership = await TeamMembershipRepository(prisma_client).table.find_unique(
            where={"user_id_team_id": {"user_id": user_id, "team_id": team_id}},
        )

    budget, _using_default, _breakdown = await resolve_config_team_member_budget(
        team_metadata=team_metadata,
        prisma_client=prisma_client,
        user_api_key_cache=user_api_key_cache,
        membership=membership,
    )
    if budget is None:
        return None
    return budget.max_budget
