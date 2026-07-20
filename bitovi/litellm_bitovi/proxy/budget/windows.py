"""Calendar-aligned model budget window helpers (Bitovi fork)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from litellm.litellm_core_utils.duration_parser import duration_in_seconds

MODEL_BUDGET_WINDOW_TTL_BUFFER_SECONDS = 3600


@dataclass(frozen=True, slots=True)
class ModelBudgetWindow:
    """A calendar-aligned budget window for a given duration.

    ``window_start`` and ``reset_at`` are the inclusive start and exclusive end
    of the current window in the configured budget-reset timezone (UTC by
    default). ``epoch`` is the integer ``window_start`` timestamp used to key the
    spend counter so it rolls over deterministically at each boundary without a
    first-request anchor or a scheduled reset job.
    """

    window_start: datetime
    reset_at: datetime
    epoch: int


def current_model_budget_window(budget_duration: str) -> ModelBudgetWindow:
    from litellm.proxy.common_utils.timezone_utils import get_budget_reset_time

    reset_at = get_budget_reset_time(budget_duration=budget_duration)
    if reset_at.tzinfo is None:
        reset_at = reset_at.replace(tzinfo=timezone.utc)
    window_start = reset_at - timedelta(seconds=duration_in_seconds(budget_duration))
    return ModelBudgetWindow(window_start=window_start, reset_at=reset_at, epoch=int(window_start.timestamp()))


def windowed_cache_key(base_key: str, window_epoch: int) -> str:
    return f"{base_key}:w{window_epoch}"


def window_ttl_seconds(reset_at: datetime) -> int:
    remaining = int((reset_at - datetime.now(timezone.utc)).total_seconds())
    return max(remaining, 1) + MODEL_BUDGET_WINDOW_TTL_BUFFER_SECONDS
