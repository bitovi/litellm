"""Compatibility shim. Prefer ``litellm_bitovi.proxy.config_teams.types``."""

from litellm_bitovi.proxy.config_teams.types import *  # noqa: F403
from litellm_bitovi.proxy.config_teams.types import ConfigTeamEntry, normalize_budget_config_dict

__all__ = ("ConfigTeamEntry", "normalize_budget_config_dict")
