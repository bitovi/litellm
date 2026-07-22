"""Config teams always inherit team_member_budget; no per-member overrides."""

from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple

from litellm._logging import verbose_proxy_logger
from litellm_bitovi.proxy.config_teams.sync import team_is_from_config


def config_team_forces_member_budget_inheritance(metadata: Mapping[str, Any] | None) -> bool:
    return team_is_from_config(metadata)


def _team_member_budget_id(metadata: Mapping[str, Any] | None) -> Optional[str]:
    if not metadata:
        return None
    budget_id = metadata.get("team_member_budget_id")
    return budget_id if isinstance(budget_id, str) else None


async def resolve_config_team_member_budget(
    *,
    team_metadata: Mapping[str, Any] | None,
    prisma_client: Any,
    user_api_key_cache: Any = None,
) -> Tuple[Any, bool]:
    """
    Return the shared team_member_budget for a config team.

    Always reads the budget row from the DB so My Budgets cannot stick on a
    stale membership-cache nested max_budget after config raises the default.
    """
    from litellm.proxy._types import LiteLLM_BudgetTable
    from litellm.repositories.budget_repository import BudgetRepository

    budget_id = _team_member_budget_id(team_metadata)
    if budget_id is None or prisma_client is None:
        return None, False

    budget_record = await BudgetRepository(prisma_client).table.find_unique(where={"budget_id": budget_id})
    if budget_record is None:
        verbose_proxy_logger.warning(
            "Config team member budget not found: budget_id=%s",
            budget_id,
        )
        return None, False

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
    return budget, True


async def enforce_config_team_member_budget_inheritance(
    *,
    team_id: str,
    prisma_client: Any,
    user_api_key_cache: Any = None,
) -> None:
    """
    Point every membership at the shared team_member_budget_id and drop stale caches.

    Config teams do not support per-member budget overrides; private membership
    budget_ids left over from earlier behavior would keep My Budgets / enforcement
    on the old cap after YAML raises team_member_budget.
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
