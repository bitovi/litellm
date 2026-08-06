"""
Coverage lock for config-team *total* team-member budget enforcement.

There are multiple request-time paths that can 429 on team-member spend.
A fix in only one of them is not enough (we already shipped that once).

This module:
1. Source-scans every known enforcement site and requires a Bitovi policy seam
2. Behavior-tests each site with the production failure shape
   (linked row $130, spend $130.008, temp +$50 -> effective $180)
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import litellm
from litellm.caching.dual_cache import DualCache
from litellm.proxy._types import (
    LiteLLM_TeamMembership,
    LiteLLM_TeamTable,
    LiteLLM_UserTable,
    UserAPIKeyAuth,
)
from litellm.proxy.auth.auth_checks import _check_team_member_budget, get_team_membership
from litellm.proxy.utils import ProxyLogging
from litellm_bitovi.proxy.config_teams import CONFIG_TEAM_METADATA_KEY
from litellm_bitovi.proxy.config_teams.member_budget_policy import POLICY_METADATA_KEY
from litellm_bitovi.proxy.config_teams.membership_metadata import team_membership_from_db_row

REPO_ROOT = Path(__file__).resolve().parents[4]

# (relative path, required Bitovi symbol that applies policy additives)
TEAM_MEMBER_TOTAL_BUDGET_ENFORCEMENT_SEAMS: tuple[tuple[str, str], ...] = (
    (
        "litellm/proxy/auth/user_api_key_auth.py",
        "effective_team_member_max_budget_for_auth",
    ),
    (
        "litellm/proxy/auth/auth_checks.py",
        "resolve_config_team_member_budget",
    ),
    (
        "litellm/proxy/spend_tracking/budget_reservation.py",
        "effective_team_member_max_budget_for_auth",
    ),
    (
        "litellm/proxy/auth/auth_checks.py",
        "resolve_inheriting_key_max_budget",
    ),
)

LINKED_MAX = 130.0
TEMP_ADDITIVE = 50.0
EFFECTIVE_MAX = LINKED_MAX + TEMP_ADDITIVE
OVER_LINKED_SPEND = 130.0081718500001


def _team_metadata() -> dict:
    return {
        CONFIG_TEAM_METADATA_KEY: True,
        "team_member_budget_id": "b-shared",
    }


def _membership_with_policy(*, spend: float = OVER_LINKED_SPEND) -> LiteLLM_TeamMembership:
    return team_membership_from_db_row(
        SimpleNamespace(
            dict=lambda: {
                "user_id": "u1",
                "team_id": "systems",
                "spend": spend,
                "total_spend": spend,
                "budget_id": "b-shared",
                "metadata": json.dumps({POLICY_METADATA_KEY: {"temp_additive": TEMP_ADDITIVE}}),
                "litellm_budget_table": {
                    "budget_id": "b-shared",
                    "max_budget": LINKED_MAX,
                },
            }
        )
    )


def _shared_budget_row() -> SimpleNamespace:
    return SimpleNamespace(
        dict=lambda: {
            "budget_id": "b-shared",
            "max_budget": LINKED_MAX,
            "soft_budget": None,
            "max_parallel_requests": None,
            "tpm_limit": None,
            "rpm_limit": None,
            "model_max_budget": None,
            "budget_duration": "30d",
            "budget_reset_at": None,
        }
    )


@pytest.mark.parametrize("rel_path, required_symbol", TEAM_MEMBER_TOTAL_BUDGET_ENFORCEMENT_SEAMS)
def test_enforcement_sites_call_bitovi_policy_seam(rel_path: str, required_symbol: str) -> None:
    """
    Fail if a known team-member total-budget path stops using the Bitovi policy helper.

    This is the guard that would have caught the user_api_key_auth Check 3 miss:
    auth_checks was fixed, but another file still used the linked row alone.
    """
    source = (REPO_ROOT / rel_path).read_text()
    assert required_symbol in source, (
        f"{rel_path} must call Bitovi `{required_symbol}` for config-team "
        f"member budget policy; otherwise overrides can 429 at the shared row."
    )


def test_inventory_includes_all_spend_team_member_writers_that_set_max_budget() -> None:
    """
    Heuristic net: any proxy file that both references spend:team_member and
    assigns max_budget near team_member must be in the seam inventory above.
    """
    proxy_root = REPO_ROOT / "litellm" / "proxy"
    required = {path for path, _ in TEAM_MEMBER_TOTAL_BUDGET_ENFORCEMENT_SEAMS}
    found: set[str] = set()
    for path in proxy_root.rglob("*.py"):
        text = path.read_text(errors="ignore")
        if "spend:team_member:" not in text:
            continue
        if "max_budget" not in text or "team_member" not in text:
            continue
        # skip spend accounting / reset jobs that don't choose the cap
        if path.name in {"proxy_server.py", "spend_counter_reseed.py", "reset_budget_job.py"}:
            continue
        rel = str(path.relative_to(REPO_ROOT))
        found.add(rel)
    missing = found - required
    assert not missing, (
        "New team-member spend enforcement site(s) found without a Bitovi policy seam "
        f"entry: {sorted(missing)}. Add the file to TEAM_MEMBER_TOTAL_BUDGET_ENFORCEMENT_SEAMS "
        "and wire effective_team_member_max_budget_for_auth / resolve_config_team_member_budget."
    )


@pytest.mark.asyncio
async def test_auth_checks_path_allows_spend_over_linked_row_with_policy() -> None:
    membership = _membership_with_policy()
    assert OVER_LINKED_SPEND > LINKED_MAX

    budget_table = MagicMock()
    budget_table.find_unique = AsyncMock(return_value=_shared_budget_row())
    cache = DualCache()

    async def mock_get_current_spend(counter_key, fallback_spend, max_budget=None, **kwargs):
        return OVER_LINKED_SPEND

    with (
        patch(
            "litellm.proxy.auth.auth_checks.get_team_membership",
            new=AsyncMock(return_value=membership),
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
            team_object=LiteLLM_TeamTable(team_id="systems", metadata=_team_metadata()),
            user_object=LiteLLM_UserTable(user_id="u1"),
            valid_token=UserAPIKeyAuth(token="tok", user_id="u1", team_id="systems"),
            prisma_client=MagicMock(),
            user_api_key_cache=cache,
            proxy_logging_obj=ProxyLogging(user_api_key_cache=None),
        )


@pytest.mark.asyncio
async def test_user_api_key_auth_helper_cap_exceeds_linked_row() -> None:
    from litellm_bitovi.proxy.config_teams import effective_team_member_max_budget_for_auth

    membership = _membership_with_policy()
    budget_table = MagicMock()
    budget_table.find_unique = AsyncMock(return_value=_shared_budget_row())

    with patch(
        "litellm.repositories.budget_repository.BudgetRepository",
        return_value=SimpleNamespace(table=budget_table),
    ):
        cap = await effective_team_member_max_budget_for_auth(
            team_metadata=_team_metadata(),
            membership=membership,
            prisma_client=MagicMock(),
            linked_budget_max=LINKED_MAX,
        )

    assert cap == EFFECTIVE_MAX
    assert OVER_LINKED_SPEND < cap
    assert OVER_LINKED_SPEND > LINKED_MAX


@pytest.mark.asyncio
async def test_budget_reservation_counter_uses_policy_effective_max() -> None:
    from litellm.proxy.spend_tracking.budget_reservation import _get_team_member_budget_counter

    membership = _membership_with_policy()
    cache = DualCache()
    await cache.async_set_cache(
        key="team_membership:u1:systems",
        value=membership,
    )

    budget_table = MagicMock()
    budget_table.find_unique = AsyncMock(return_value=_shared_budget_row())

    with (
        patch(
            "litellm.proxy.proxy_server.prisma_client",
            MagicMock(),
        ),
        patch(
            "litellm.repositories.budget_repository.BudgetRepository",
            return_value=SimpleNamespace(table=budget_table),
        ),
        patch(
            "litellm.proxy.common_utils.user_api_key_cache.get_management_object_ttl",
            return_value=60.0,
        ),
    ):
        counter = await _get_team_member_budget_counter(
            valid_token=UserAPIKeyAuth(token="tok", user_id="u1", team_id="systems"),
            team_object=LiteLLM_TeamTable(team_id="systems", metadata=_team_metadata()),
            user_object=LiteLLM_UserTable(user_id="u1"),
            user_api_key_cache=cache,
        )

    assert counter is not None
    assert counter.max_budget == EFFECTIVE_MAX
    assert counter.counter_key == "spend:team_member:u1:systems"


@pytest.mark.asyncio
async def test_get_team_membership_and_auth_checks_agree_on_effective_cap() -> None:
    """Both membership load + auth_checks enforcement must see the same effective max."""
    from litellm_bitovi.proxy.config_teams import resolve_config_team_member_budget

    row = SimpleNamespace(
        dict=lambda: {
            "user_id": "u1",
            "team_id": "systems",
            "spend": OVER_LINKED_SPEND,
            "total_spend": OVER_LINKED_SPEND,
            "budget_id": "b-shared",
            "metadata": json.dumps({POLICY_METADATA_KEY: {"temp_additive": TEMP_ADDITIVE}}),
            "litellm_budget_table": {
                "budget_id": "b-shared",
                "max_budget": LINKED_MAX,
            },
        }
    )
    membership_table = MagicMock()
    membership_table.find_unique = AsyncMock(return_value=row)
    budget_table = MagicMock()
    budget_table.find_unique = AsyncMock(return_value=_shared_budget_row())
    cache = DualCache()

    with (
        patch(
            "litellm.proxy.auth.auth_checks.TeamMembershipRepository",
            return_value=SimpleNamespace(table=membership_table),
        ),
        patch(
            "litellm.repositories.budget_repository.BudgetRepository",
            return_value=SimpleNamespace(table=budget_table),
        ),
        patch(
            "litellm.proxy.common_utils.user_api_key_cache.get_management_object_ttl",
            return_value=60.0,
        ),
    ):
        membership = await get_team_membership(
            user_id="u1",
            team_id="systems",
            prisma_client=MagicMock(),
            user_api_key_cache=cache,
        )
        assert membership is not None
        budget, _, breakdown = await resolve_config_team_member_budget(
            team_metadata=_team_metadata(),
            prisma_client=MagicMock(),
            user_api_key_cache=cache,
            membership=membership,
        )

    assert budget is not None
    assert budget.max_budget == EFFECTIVE_MAX
    assert breakdown is not None
    assert breakdown["temp_additive"] == TEMP_ADDITIVE
    # Linked row alone would still 429 this spend.
    assert OVER_LINKED_SPEND > LINKED_MAX
    assert OVER_LINKED_SPEND < EFFECTIVE_MAX


@pytest.mark.asyncio
async def test_auth_checks_still_blocks_when_over_effective_max() -> None:
    membership = _membership_with_policy(spend=EFFECTIVE_MAX + 1)
    budget_table = MagicMock()
    budget_table.find_unique = AsyncMock(return_value=_shared_budget_row())

    async def mock_get_current_spend(counter_key, fallback_spend, max_budget=None, **kwargs):
        return EFFECTIVE_MAX + 1

    with (
        patch(
            "litellm.proxy.auth.auth_checks.get_team_membership",
            new=AsyncMock(return_value=membership),
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
        with pytest.raises(litellm.BudgetExceededError) as exc_info:
            await _check_team_member_budget(
                team_object=LiteLLM_TeamTable(team_id="systems", metadata=_team_metadata()),
                user_object=LiteLLM_UserTable(user_id="u1"),
                valid_token=UserAPIKeyAuth(token="tok", user_id="u1", team_id="systems"),
                prisma_client=MagicMock(),
                user_api_key_cache=DualCache(),
                proxy_logging_obj=ProxyLogging(user_api_key_cache=None),
            )

    assert exc_info.value.max_budget == EFFECTIVE_MAX
    assert exc_info.value.current_cost == EFFECTIVE_MAX + 1
