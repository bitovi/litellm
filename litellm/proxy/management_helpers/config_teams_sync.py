"""Compatibility shim. Prefer ``litellm_bitovi.proxy.config_teams``."""

from litellm_bitovi.proxy.config_teams import *  # noqa: F403
from litellm_bitovi.proxy.config_teams import (
    CONFIG_MEMBER_BUDGET_FIELDS,
    CONFIG_TEAM_BUDGET_FIELDS,
    CONFIG_TEAM_METADATA_KEY,
    _config_team_sync_active,
    apply_team_member_budget_to_sa_key,
    budget_fields_in_payload,
    extract_model_list_budgets,
    is_config_team_sync_active,
    merge_team_model_max_budget,
    parse_config_teams,
    sync_config_teams,
    team_is_from_config,
)

__all__ = (
    "CONFIG_MEMBER_BUDGET_FIELDS",
    "CONFIG_TEAM_BUDGET_FIELDS",
    "CONFIG_TEAM_METADATA_KEY",
    "_config_team_sync_active",
    "apply_team_member_budget_to_sa_key",
    "budget_fields_in_payload",
    "extract_model_list_budgets",
    "is_config_team_sync_active",
    "merge_team_model_max_budget",
    "parse_config_teams",
    "sync_config_teams",
    "team_is_from_config",
)
