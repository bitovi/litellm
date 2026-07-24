"""Config teams inherit shared team_member_budget; keys refresh on team update."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import litellm
from litellm.caching.dual_cache import DualCache
from litellm.proxy._types import LiteLLM_TeamTable, LiteLLM_UserTable, UserAPIKeyAuth
from litellm.proxy.auth.auth_checks import _check_team_member_budget, get_team_membership
from litellm.proxy.utils import ProxyLogging
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
async def test_resolve_applies_policy_when_metadata_is_json_string() -> None:
    """Budget-policy PUT stores metadata via json.dumps; Prisma may return a str."""
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
        metadata=json.dumps(
            {
                POLICY_METADATA_KEY: {
                    "temp_additive": 50,
                }
            }
        )
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
    assert budget.max_budget == 150.0
    assert breakdown is not None
    assert breakdown["temp_additive"] == 50


@pytest.mark.asyncio
async def test_get_team_membership_loads_json_string_metadata() -> None:
    """Regression: string metadata must not fail LiteLLM_TeamMembership validation."""
    prisma = MagicMock()
    cache = DualCache()
    membership_row = SimpleNamespace(
        dict=lambda: {
            "user_id": "u1",
            "team_id": "systems",
            "spend": 120.0,
            "total_spend": 120.0,
            "budget_id": "b-shared",
            "metadata": json.dumps({POLICY_METADATA_KEY: {"temp_additive": 50}}),
            "litellm_budget_table": None,
        }
    )
    membership_table = MagicMock()
    membership_table.find_unique = AsyncMock(return_value=membership_row)

    with patch(
        "litellm.proxy.auth.auth_checks.TeamMembershipRepository",
        return_value=SimpleNamespace(table=membership_table),
    ):
        membership = await get_team_membership(
            user_id="u1",
            team_id="systems",
            prisma_client=prisma,
            user_api_key_cache=cache,
        )

    assert membership is not None
    assert membership.metadata == {POLICY_METADATA_KEY: {"temp_additive": 50}}


@pytest.mark.asyncio
async def test_budget_override_applies_when_membership_metadata_is_json_string() -> None:
    """
    Regression for 429-after-override: budget-policy PUT stores membership
    metadata as json.dumps(...). Prisma returns a str; auth must still load
    membership and enforce team_default + temp_additive (not team_default alone).

    Spend $120 with team default $100 and temp +$50 must be allowed.
    Spend $160 must still 429 against effective $150.
    """
    team_object = LiteLLM_TeamTable(
        team_id="systems",
        metadata={
            CONFIG_TEAM_METADATA_KEY: True,
            "team_member_budget_id": "b-shared",
        },
    )
    user_object = LiteLLM_UserTable(user_id="u1")
    valid_token = UserAPIKeyAuth(token="tok", user_id="u1", team_id="systems")
    proxy_logging_obj = ProxyLogging(user_api_key_cache=None)
    prisma = MagicMock()
    cache = DualCache()

    membership_row = SimpleNamespace(
        dict=lambda: {
            "user_id": "u1",
            "team_id": "systems",
            "spend": 120.0,
            "total_spend": 120.0,
            "budget_id": "b-shared",
            "metadata": json.dumps({POLICY_METADATA_KEY: {"temp_additive": 50}}),
            "litellm_budget_table": None,
        }
    )
    membership_table = MagicMock()
    membership_table.find_unique = AsyncMock(return_value=membership_row)

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

    current_spend = 120.0

    async def mock_get_current_spend(counter_key, fallback_spend, max_budget=None, **kwargs):
        if counter_key == "spend:team_member:u1:systems":
            return current_spend
        return fallback_spend

    with (
        patch(
            "litellm.proxy.auth.auth_checks.TeamMembershipRepository",
            return_value=SimpleNamespace(table=membership_table),
        ),
        patch(
            "litellm.repositories.budget_repository.BudgetRepository",
            return_value=SimpleNamespace(table=budget_table),
        ),
        patch("litellm.proxy.proxy_server.get_current_spend", mock_get_current_spend),
        patch(
            "litellm.proxy.common_utils.user_api_key_cache.get_management_object_ttl",
            return_value=60.0,
        ),
    ):
        await _check_team_member_budget(
            team_object=team_object,
            user_object=user_object,
            valid_token=valid_token,
            prisma_client=prisma,
            user_api_key_cache=cache,
            proxy_logging_obj=proxy_logging_obj,
        )

        current_spend = 160.0
        with pytest.raises(litellm.BudgetExceededError) as exc_info:
            await _check_team_member_budget(
                team_object=team_object,
                user_object=user_object,
                valid_token=valid_token,
                prisma_client=prisma,
                user_api_key_cache=cache,
                proxy_logging_obj=proxy_logging_obj,
            )

    assert exc_info.value.current_cost == 160.0
    assert exc_info.value.max_budget == 150.0


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
