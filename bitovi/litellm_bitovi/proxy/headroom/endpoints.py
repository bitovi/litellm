"""Bitovi Headroom savings API (aggregate tokens saved via LiteLLM)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from litellm.proxy._types import LitellmUserRoles, UserAPIKeyAuth
from litellm.proxy.auth.user_api_key_auth import user_api_key_auth
from litellm_bitovi.proxy.headroom.savings import (
    aggregate_compression_stats,
    extract_compression_stats_from_spend_metadata,
    parse_spend_log_metadata_field,
)

router = APIRouter(prefix="/bitovi/headroom", tags=["bitovi-headroom"])


class HeadroomSavingsResponse(BaseModel):
    start_date: str
    end_date: str
    requests_with_stats: int = Field(description="Spend logs that recorded headroom_compression stats")
    requests_with_savings: int = Field(description="Subset where tokens_saved > 0")
    tokens_before: int
    tokens_after: int
    tokens_saved: int
    compression_ratio: float


def _parse_day(value: str, *, end_of_day: bool) -> datetime:
    try:
        day = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid date '{value}', expected YYYY-MM-DD") from exc
    if end_of_day:
        return day + timedelta(days=1) - timedelta(microseconds=1)
    return day


def _require_admin_view(user_api_key_dict: UserAPIKeyAuth) -> None:
    role = user_api_key_dict.user_role
    allowed = {
        LitellmUserRoles.PROXY_ADMIN,
        LitellmUserRoles.PROXY_ADMIN_VIEW_ONLY,
        LitellmUserRoles.PROXY_ADMIN.value,
        LitellmUserRoles.PROXY_ADMIN_VIEW_ONLY.value,
    }
    if role not in allowed:
        raise HTTPException(status_code=403, detail="Admin role required to view Headroom savings")


@router.get("/savings", response_model=HeadroomSavingsResponse)
async def get_headroom_savings(
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD (UTC)"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD (UTC)"),
    user_api_key_dict: UserAPIKeyAuth = Depends(user_api_key_auth),
) -> HeadroomSavingsResponse:
    """Aggregate Headroom token savings from spend-log metadata.

    Stats come from ``metadata.headroom_compression`` written by the Bitovi
    Headroom seam (not from redacted ``guardrail_response``).
    """
    from litellm.proxy.proxy_server import prisma_client

    _require_admin_view(user_api_key_dict)

    if prisma_client is None:
        raise HTTPException(status_code=500, detail="Prisma client not initialized")

    now = datetime.now(timezone.utc)
    end = end_date or now.strftime("%Y-%m-%d")
    start = start_date or (now - timedelta(days=7)).strftime("%Y-%m-%d")
    start_dt = _parse_day(start, end_of_day=False)
    end_dt = _parse_day(end, end_of_day=True)

    rows: list[Any] = await prisma_client.db.litellm_spendlogs.find_many(
        where={
            "startTime": {"gte": start_dt, "lte": end_dt},
        },
        order={"startTime": "desc"},
        take=5000,
    )

    parsed_stats = tuple(
        extract_compression_stats_from_spend_metadata(
            parse_spend_log_metadata_field(getattr(row, "metadata", None))
        )
        for row in rows
    )
    agg = aggregate_compression_stats(parsed_stats)
    return HeadroomSavingsResponse(
        start_date=start,
        end_date=end,
        **agg.as_dict(),
    )
