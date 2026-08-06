"""Membership metadata coerce / Prisma write helpers for config-team budget policy."""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional

from litellm._logging import verbose_proxy_logger

TEAM_MEMBERSHIP_CACHE_KEY = "team_membership:{user_id}:{team_id}"
# Early Check 3 in user_api_key_auth.py uses this alternate key.
USER_API_KEY_AUTH_MEMBERSHIP_CACHE_KEY = "{team_id}_{user_id}"


def coerce_membership_metadata(metadata: Any) -> Optional[dict[str, Any]]:
    """Prisma Json columns may come back as dict or as a JSON string."""
    if isinstance(metadata, Mapping):
        return dict(metadata)
    if isinstance(metadata, str):
        try:
            parsed = json.loads(metadata)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return dict(parsed) if isinstance(parsed, Mapping) else None
    return None


def metadata_for_prisma_write(metadata: Mapping[str, Any]) -> Any:
    """
    Value to pass into a Prisma Json column update.

    Pass a dict wrapped in prisma.Json so Postgres stores a JSON object.
    Never pass json.dumps(...) (a str): that stores a JSON *string* and
    makes auth fail to load LiteLLM_TeamMembership / ignore budget policy.
    """
    payload = dict(metadata)
    try:
        from prisma import Json

        return Json(payload)
    except Exception:
        # Prisma may be ungenerated in some tooling contexts; dict still works
        # for clients that accept raw JSON objects.
        return payload


def team_membership_from_db_row(db_row: Any) -> Any:
    """Build LiteLLM_TeamMembership with metadata coerced to a dict."""
    from litellm.proxy._types import LiteLLM_TeamMembership

    if hasattr(db_row, "dict"):
        membership_data = db_row.dict()
    elif isinstance(db_row, Mapping):
        membership_data = dict(db_row)
    else:
        raise TypeError(f"Unsupported team membership row type: {type(db_row)!r}")

    membership_data["metadata"] = coerce_membership_metadata(membership_data.get("metadata"))
    return LiteLLM_TeamMembership(**membership_data)


def team_membership_cache_keys(*, user_id: str, team_id: str) -> tuple[str, str]:
    return (
        TEAM_MEMBERSHIP_CACHE_KEY.format(user_id=user_id, team_id=team_id),
        USER_API_KEY_AUTH_MEMBERSHIP_CACHE_KEY.format(team_id=team_id, user_id=user_id),
    )


async def invalidate_team_membership_auth_caches(
    *,
    user_api_key_cache: Any,
    user_id: str,
    team_id: str,
) -> None:
    if user_api_key_cache is None:
        return
    for cache_key in team_membership_cache_keys(user_id=user_id, team_id=team_id):
        try:
            await user_api_key_cache.async_delete_cache(key=cache_key)
        except Exception:
            verbose_proxy_logger.debug(
                "Failed to invalidate team membership cache key=%s",
                cache_key,
                exc_info=True,
            )
