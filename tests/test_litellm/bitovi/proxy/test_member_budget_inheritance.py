"""Config teams inherit shared team_member_budget; keys refresh on team update."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from litellm_bitovi.proxy.config_teams import CONFIG_TEAM_METADATA_KEY
from litellm_bitovi.proxy.config_teams.member_budget_inheritance import (
    config_team_forces_member_budget_inheritance,
    enforce_config_team_member_budget_inheritance,
    refresh_inheriting_keys_for_team,
    resolve_config_team_member_budget,
)
from litellm_bitovi.proxy.config_teams.member_budget_policy import (
    INHERITS_TEAM_MEMBER_BUDGET_KEY,
    POLICY_METADATA_KEY,
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
        budget, using_default, breakdown = await resolve_config_team_member_budget(
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
    assert breakdown is not None
    assert breakdown["effective_max"] == 130.0
    cache.async_set_cache.assert_awaited()


@pytest.mark.asyncio
async def test_resolve_applies_membership_policy_additives() -> None:
    prisma = MagicMock()
    budget_row = SimpleNamespace(
        dict=lambda: {
            "budget_id": "b-shared",
            "max_budget": 100.0,
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
    membership = SimpleNamespace(
        metadata={
            POLICY_METADATA_KEY: {
                "recurring_additive": 100,
                "temp_additive": 50,
            }
        }
    )

    with patch(
        "litellm.repositories.budget_repository.BudgetRepository",
        return_value=SimpleNamespace(table=budget_table),
    ):
        budget, using_default, breakdown = await resolve_config_team_member_budget(
            team_metadata={
                CONFIG_TEAM_METADATA_KEY: True,
                "team_member_budget_id": "b-shared",
            },
            prisma_client=prisma,
            membership=membership,
        )

    assert using_default is False
    assert budget is not None
    assert budget.max_budget == 250.0
    assert breakdown is not None
    assert breakdown["recurring_additive"] == 100
    assert breakdown["temp_additive"] == 50


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
        patch(
            "litellm_bitovi.proxy.config_teams.member_budget_inheritance.refresh_inheriting_keys_for_team",
            new=AsyncMock(return_value=0),
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


@pytest.mark.asyncio
async def test_inheriting_key_follows_team_member_budget_update() -> None:
    """Team default 100 -> key stamped 100 -> team updated to 150 -> key becomes 150."""
    from litellm_bitovi.proxy.config_teams.sync import apply_team_member_budget_to_sa_key

    data = SimpleNamespace(user_id=None, max_budget=None, budget_duration=None, metadata=None)
    team_table = SimpleNamespace(
        metadata={
            CONFIG_TEAM_METADATA_KEY: True,
            "team_member_budget_id": "b-shared",
        }
    )
    budget_100 = SimpleNamespace(max_budget=100.0, budget_duration="30d")

    with patch(
        "litellm.proxy.auth.auth_checks.get_team_member_default_budget",
        new=AsyncMock(return_value=budget_100),
    ):
        await apply_team_member_budget_to_sa_key(
            data=data,
            team_table=team_table,
            prisma_client=MagicMock(),
            user_api_key_cache=MagicMock(),
        )

    assert data.max_budget == 100.0
    assert data.metadata[INHERITS_TEAM_MEMBER_BUDGET_KEY] is True

    prisma = MagicMock()
    cache = MagicMock()
    cache.async_delete_cache = AsyncMock()

    team_repo_table = MagicMock()
    team_repo_table.find_unique = AsyncMock(
        return_value=SimpleNamespace(
            team_id="systems",
            metadata={
                CONFIG_TEAM_METADATA_KEY: True,
                "team_member_budget_id": "b-shared",
            },
        )
    )
    budget_row = SimpleNamespace(
        dict=lambda: {
            "budget_id": "b-shared",
            "max_budget": 150.0,
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

    key_row = SimpleNamespace(
        token="hashed-token",
        team_id="systems",
        max_budget=100.0,
        metadata={INHERITS_TEAM_MEMBER_BUDGET_KEY: True},
    )
    prisma.db.litellm_verificationtoken.find_many = AsyncMock(return_value=[key_row])
    prisma.db.litellm_verificationtoken.update = AsyncMock()

    with (
        patch(
            "litellm.repositories.team_repository.TeamRepository",
            return_value=SimpleNamespace(table=team_repo_table),
        ),
        patch(
            "litellm.repositories.budget_repository.BudgetRepository",
            return_value=SimpleNamespace(table=budget_table),
        ),
    ):
        refreshed = await refresh_inheriting_keys_for_team(
            team_id="systems",
            prisma_client=prisma,
            user_api_key_cache=cache,
        )

    assert refreshed == 1
    prisma.db.litellm_verificationtoken.update.assert_awaited_once_with(
        where={"token": "hashed-token"},
        data={"max_budget": 150.0, "budget_duration": "30d"},
    )
