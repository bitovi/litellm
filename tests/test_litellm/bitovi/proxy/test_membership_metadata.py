"""Tests for membership metadata coerce / Prisma write / auth cache helpers."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from prisma import Json

from litellm.proxy._types import LiteLLM_BudgetTable, LiteLLM_TeamMembership
from litellm_bitovi.proxy.config_teams import CONFIG_TEAM_METADATA_KEY
from litellm_bitovi.proxy.config_teams.member_budget_policy import POLICY_METADATA_KEY
from litellm_bitovi.proxy.config_teams.membership_metadata import (
    coerce_membership_metadata,
    invalidate_team_membership_auth_caches,
    metadata_for_prisma_write,
    team_membership_cache_keys,
    team_membership_from_db_row,
)
from litellm_bitovi.proxy.config_teams.member_budget_inheritance import (
    effective_team_member_max_budget_for_auth,
)


def test_coerce_membership_metadata_accepts_dict_and_json_string() -> None:
    policy = {POLICY_METADATA_KEY: {"temp_additive": 50}}
    assert coerce_membership_metadata(policy) == policy
    assert coerce_membership_metadata(json.dumps(policy)) == policy
    assert coerce_membership_metadata("not-json") is None
    assert coerce_membership_metadata(None) is None


def test_metadata_for_prisma_write_is_json_object_not_dumps_string() -> None:
    """
    Regression: json.dumps(metadata) stores a JSON *string* in a Json column.
    Auth then fails LiteLLM_TeamMembership validation / ignores budget policy.
    """
    payload = {POLICY_METADATA_KEY: {"temp_additive": 50, "recurring_additive": 100}}
    written = metadata_for_prisma_write(payload)

    assert not isinstance(written, str)
    assert isinstance(written, Json)
    assert written.data == payload
    # A dumps string would look like this and must never be written:
    assert written.data != json.dumps(payload)


def test_team_membership_from_db_row_coerces_string_metadata() -> None:
    row = SimpleNamespace(
        dict=lambda: {
            "user_id": "u1",
            "team_id": "systems",
            "spend": 130.0081718500001,
            "total_spend": 130.0081718500001,
            "budget_id": "b-shared",
            "metadata": json.dumps({POLICY_METADATA_KEY: {"temp_additive": 50}}),
            "litellm_budget_table": {
                "budget_id": "b-shared",
                "max_budget": 130.0,
            },
        }
    )
    membership = team_membership_from_db_row(row)
    assert isinstance(membership, LiteLLM_TeamMembership)
    assert membership.metadata == {POLICY_METADATA_KEY: {"temp_additive": 50}}
    assert membership.litellm_budget_table is not None
    assert membership.litellm_budget_table.max_budget == 130.0


def test_team_membership_from_db_row_rejects_uncocerced_string_via_model() -> None:
    """Prove the pre-fix failure mode: raw string metadata cannot build the model."""
    with pytest.raises(Exception):
        LiteLLM_TeamMembership(
            user_id="u1",
            team_id="systems",
            spend=130.0,
            metadata=json.dumps({POLICY_METADATA_KEY: {"temp_additive": 50}}),
        )


def test_team_membership_cache_keys_cover_both_auth_paths() -> None:
    keys = team_membership_cache_keys(user_id="u1", team_id="systems")
    assert keys == ("team_membership:u1:systems", "systems_u1")


@pytest.mark.asyncio
async def test_invalidate_team_membership_auth_caches_clears_both_keys() -> None:
    cache = MagicMock()
    cache.async_delete_cache = AsyncMock()
    await invalidate_team_membership_auth_caches(
        user_api_key_cache=cache,
        user_id="u1",
        team_id="systems",
    )
    deleted = {call.kwargs["key"] for call in cache.async_delete_cache.await_args_list}
    assert deleted == {"team_membership:u1:systems", "systems_u1"}


@pytest.mark.asyncio
async def test_key_auth_check3_would_429_on_linked_row_but_passes_with_policy() -> None:
    """
    Full coverage for the production failure:

    - Spend: 130.0081718500001
    - Shared litellm_budget_table.max_budget: 130.0  (what Check 3 used before)
    - Policy temp_additive: 50 -> effective 180

    Pre-fix Check 3: spend > 130 -> 429
    Post-fix: effective cap 180 -> allow
    """
    prisma = MagicMock()
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

    membership = team_membership_from_db_row(
        SimpleNamespace(
            dict=lambda: {
                "user_id": "109143166874845888534",
                "team_id": "0fc814df-71ba-4539-8b35-a6310336654b",
                "spend": 130.0081718500001,
                "total_spend": 130.0081718500001,
                "budget_id": "b-shared",
                "metadata": json.dumps({POLICY_METADATA_KEY: {"temp_additive": 50}}),
                "litellm_budget_table": {
                    "budget_id": "b-shared",
                    "max_budget": 130.0,
                },
            }
        )
    )
    spend = 130.0081718500001
    linked_only = membership.litellm_budget_table.max_budget
    assert linked_only == 130.0
    assert spend > linked_only  # pre-fix Check 3 would raise here

    with patch(
        "litellm.repositories.budget_repository.BudgetRepository",
        return_value=SimpleNamespace(table=budget_table),
    ):
        effective = await effective_team_member_max_budget_for_auth(
            team_metadata={
                CONFIG_TEAM_METADATA_KEY: True,
                "team_member_budget_id": "b-shared",
            },
            membership=membership,
            prisma_client=prisma,
            linked_budget_max=linked_only,
        )

    assert effective == 180.0
    assert spend < effective


@pytest.mark.asyncio
async def test_budget_policy_put_passes_prisma_json_not_dumps_string() -> None:
    """PUT /bitovi/.../budget-policy must write metadata via metadata_for_prisma_write."""
    from datetime import datetime, timezone

    from litellm_bitovi.proxy.config_teams.endpoints import (
        MemberBudgetPolicyUpdateRequest,
        put_member_budget_policy,
    )

    team_obj = SimpleNamespace(
        team_id="systems",
        metadata={CONFIG_TEAM_METADATA_KEY: True, "team_member_budget_id": "b-shared"},
    )
    membership = SimpleNamespace(metadata={})
    updated_row = SimpleNamespace(metadata={POLICY_METADATA_KEY: {"temp_additive": 50}})

    membership_table = MagicMock()
    membership_table.update = AsyncMock(return_value=updated_row)

    cache = MagicMock()
    cache.async_delete_cache = AsyncMock()

    with (
        patch(
            "litellm_bitovi.proxy.config_teams.endpoints._load_team_and_membership",
            new=AsyncMock(return_value=(team_obj, membership)),
        ),
        patch(
            "litellm_bitovi.proxy.config_teams.endpoints._require_team_admin",
            return_value=None,
        ),
        patch(
            "litellm_bitovi.proxy.config_teams.endpoints._team_default_max_budget",
            new=AsyncMock(return_value=(130.0, datetime(2026, 8, 1, tzinfo=timezone.utc))),
        ),
        patch(
            "litellm.proxy.proxy_server.prisma_client",
            MagicMock(),
        ),
        patch(
            "litellm.proxy.proxy_server.user_api_key_cache",
            cache,
        ),
        patch(
            "litellm.repositories.table_repositories.TeamMembershipRepository",
            return_value=SimpleNamespace(table=membership_table),
        ),
    ):
        await put_member_budget_policy(
            team_id="systems",
            user_id="u1",
            data=MemberBudgetPolicyUpdateRequest(temp_additive=50),
            user_api_key_dict=MagicMock(),
        )

    written = membership_table.update.await_args.kwargs["data"]["metadata"]
    assert isinstance(written, Json)
    assert not isinstance(written, str)
    assert written.data[POLICY_METADATA_KEY]["temp_additive"] == 50
    deleted = {call.kwargs["key"] for call in cache.async_delete_cache.await_args_list}
    assert "team_membership:u1:systems" in deleted
    assert "systems_u1" in deleted
