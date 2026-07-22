"""Config teams always inherit shared team_member_budget (no per-member overrides)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from litellm_bitovi.proxy.config_teams import CONFIG_TEAM_METADATA_KEY
from litellm_bitovi.proxy.config_teams.member_budget_inheritance import (
    config_team_forces_member_budget_inheritance,
    enforce_config_team_member_budget_inheritance,
    resolve_config_team_member_budget,
)


def test_config_team_forces_inheritance() -> None:
    assert config_team_forces_member_budget_inheritance({CONFIG_TEAM_METADATA_KEY: True}) is True
    assert config_team_forces_member_budget_inheritance({}) is False
    assert config_team_forces_member_budget_inheritance(None) is False


@pytest.mark.asyncio
async def test_resolve_config_team_member_budget_reads_shared_row() -> None:
    prisma = MagicMock()
    cache = MagicMock()
    cache.async_set_cache = AsyncMock()
    budget_row = SimpleNamespace(
        dict=lambda: {
            "budget_id": "b-shared",
            "max_budget": 130.0,
            "soft_budget": None,
            "max_parallel_requests": None,
            "tpm_limit": None,
            "rpm_limit": None,
            "model_max_budget": None,
            "budget_duration": "30d",
            "budget_reset_at": None,
        }
    )
    budget_table = MagicMock()
    budget_table.find_unique = AsyncMock(return_value=budget_row)

    with (
        patch(
            "litellm.repositories.budget_repository.BudgetRepository",
            return_value=SimpleNamespace(table=budget_table),
        ),
        patch(
            "litellm.proxy.common_utils.user_api_key_cache.get_management_object_ttl",
            return_value=60.0,
        ),
    ):
        budget, using_default = await resolve_config_team_member_budget(
            team_metadata={
                CONFIG_TEAM_METADATA_KEY: True,
                "team_member_budget_id": "b-shared",
            },
            prisma_client=prisma,
            user_api_key_cache=cache,
        )

    assert using_default is True
    assert budget is not None
    assert budget.budget_id == "b-shared"
    assert budget.max_budget == 130.0
    cache.async_set_cache.assert_awaited()


@pytest.mark.asyncio
async def test_enforce_reconnects_all_memberships_and_clears_caches() -> None:
    prisma = MagicMock()
    cache = MagicMock()
    cache.async_delete_cache = AsyncMock()

    team_table = MagicMock()
    team_table.find_unique = AsyncMock(
        return_value=SimpleNamespace(
            team_id="systems",
            metadata={
                CONFIG_TEAM_METADATA_KEY: True,
                "team_member_budget_id": "b-shared",
            },
        )
    )
    membership_table = MagicMock()
    membership_table.find_many = AsyncMock(
        return_value=[
            SimpleNamespace(user_id="u1"),
            SimpleNamespace(user_id="u2"),
        ]
    )
    membership_table.update_many = AsyncMock(return_value=2)

    with (
        patch(
            "litellm.repositories.team_repository.TeamRepository",
            return_value=SimpleNamespace(table=team_table),
        ),
        patch(
            "litellm.repositories.table_repositories.TeamMembershipRepository",
            return_value=SimpleNamespace(table=membership_table),
        ),
    ):
        await enforce_config_team_member_budget_inheritance(
            team_id="systems",
            prisma_client=prisma,
            user_api_key_cache=cache,
        )

    membership_table.update_many.assert_awaited_once_with(
        where={"team_id": "systems"},
        data={"budget_id": "b-shared"},
    )
    deleted_keys = {call.kwargs["key"] for call in cache.async_delete_cache.await_args_list}
    assert "team_member_default_budget:b-shared" in deleted_keys
    assert "team_membership:u1:systems" in deleted_keys
    assert "team_membership:u2:systems" in deleted_keys


@pytest.mark.asyncio
async def test_enforce_skips_non_config_teams() -> None:
    prisma = MagicMock()
    team_table = MagicMock()
    team_table.find_unique = AsyncMock(
        return_value=SimpleNamespace(team_id="manual", metadata={})
    )
    membership_table = MagicMock()
    membership_table.update_many = AsyncMock()

    with (
        patch(
            "litellm.repositories.team_repository.TeamRepository",
            return_value=SimpleNamespace(table=team_table),
        ),
        patch(
            "litellm.repositories.table_repositories.TeamMembershipRepository",
            return_value=SimpleNamespace(table=membership_table),
        ),
    ):
        await enforce_config_team_member_budget_inheritance(
            team_id="manual",
            prisma_client=prisma,
            user_api_key_cache=None,
        )

    membership_table.update_many.assert_not_called()
