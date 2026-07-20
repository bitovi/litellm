"""Virtual-key ownership defaults (auto-assign user/team on generate)."""

from __future__ import annotations

from typing import Optional

import litellm
from fastapi import HTTPException

from litellm.constants import UI_SESSION_TOKEN_TEAM_ID
from litellm._logging import verbose_proxy_logger
from litellm.proxy._types import GenerateKeyRequest, UserAPIKeyAuth
from litellm.proxy.utils import PrismaClient
from litellm.repositories.user_repository import UserRepository


def user_membership_team_ids(teams: Optional[list[str]]) -> tuple[str, ...]:
    return tuple(
        team_id
        for team_id in (teams or [])
        if isinstance(team_id, str) and team_id and team_id != UI_SESSION_TOKEN_TEAM_ID
    )


async def apply_key_generation_ownership_defaults(
    *,
    data: GenerateKeyRequest,
    user_api_key_dict: UserAPIKeyAuth,
    prisma_client: PrismaClient,
    is_proxy_admin: bool,
) -> None:
    if not is_proxy_admin and data.user_id is None:
        data.user_id = user_api_key_dict.user_id
        verbose_proxy_logger.warning(
            "key/generate: auto-assigning user_id=%s for non-admin caller",
            user_api_key_dict.user_id,
        )

    await apply_user_team_id_from_membership(
        data=data,
        prisma_client=prisma_client,
    )

    apply_default_team_id_if_configured(
        data=data,
        caller_user_id=user_api_key_dict.user_id,
        is_proxy_admin=is_proxy_admin,
    )


async def apply_user_team_id_from_membership(
    *,
    data: GenerateKeyRequest,
    prisma_client: PrismaClient,
) -> None:
    if data.team_id is not None and data.team_id != "":
        return
    data.team_id = None
    target_user_id = data.user_id
    if target_user_id is None:
        return

    try:
        user_row = await UserRepository(prisma_client).table.find_unique(where={"user_id": target_user_id})
    except TypeError:
        return
    if user_row is None:
        return

    team_ids = user_membership_team_ids(getattr(user_row, "teams", None))
    if len(team_ids) == 0:
        return
    if len(team_ids) == 1:
        data.team_id = team_ids[0]
        verbose_proxy_logger.info(
            "key/generate: auto-assigning team_id=%s from user membership for user_id=%s",
            team_ids[0],
            target_user_id,
        )
        return

    raise HTTPException(
        status_code=400,
        detail=(
            f"User={target_user_id} belongs to multiple teams. "
            f"Specify team_id when generating a key. teams={list(team_ids)}"
        ),
    )


def apply_default_team_id_if_configured(
    *,
    data: GenerateKeyRequest,
    caller_user_id: Optional[str],
    is_proxy_admin: bool,
) -> None:
    if is_proxy_admin or data.team_id is not None or litellm.key_generation_settings is None:
        return
    personal_key_generation = litellm.key_generation_settings.get("personal_key_generation") or {}
    default_team_id = personal_key_generation.get("default_team_id")
    if not isinstance(default_team_id, str) or not default_team_id:
        return
    data.team_id = default_team_id
    verbose_proxy_logger.info(
        "key/generate: applying default_team_id=%s for caller user_id=%s",
        default_team_id,
        caller_user_id,
    )
