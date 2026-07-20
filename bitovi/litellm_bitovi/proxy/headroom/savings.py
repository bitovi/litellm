"""Headroom compression savings (non-redacted, Bitovi fork).

Upstream stores Headroom ``tokens_before`` / ``tokens_after`` inside
``guardrail_response``, which spend logs redact by default. This module copies
numeric stats onto spend-log metadata so Logs/Usage can show savings without
``store_prompts_in_spend_logs``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping, Optional


HEADROOM_COMPRESSION_METADATA_KEY = "headroom_compression"

_STAT_KEYS = (
    "tokens_before",
    "tokens_after",
    "tokens_saved",
    "compression_ratio",
)


@dataclass(frozen=True, slots=True)
class HeadroomCompressionStats:
    tokens_before: int
    tokens_after: int
    tokens_saved: int
    compression_ratio: float

    def as_dict(self) -> dict[str, int | float]:
        return {
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "tokens_saved": self.tokens_saved,
            "compression_ratio": self.compression_ratio,
        }


def parse_compression_stats(raw: object) -> Optional[HeadroomCompressionStats]:
    if not isinstance(raw, Mapping):
        return None
    try:
        before = int(raw["tokens_before"])  # type: ignore[index]
        after = int(raw["tokens_after"])  # type: ignore[index]
        saved = int(raw.get("tokens_saved", before - after))  # type: ignore[arg-type]
        ratio = float(raw.get("compression_ratio", (after / before) if before else 1.0))  # type: ignore[arg-type]
    except (KeyError, TypeError, ValueError):
        return None
    if before < 0 or after < 0:
        return None
    return HeadroomCompressionStats(
        tokens_before=before,
        tokens_after=after,
        tokens_saved=max(saved, 0),
        compression_ratio=ratio,
    )


def _metadata_slots(request_data: MutableMapping[str, Any]) -> tuple[MutableMapping[str, Any], ...]:
    slots: list[MutableMapping[str, Any]] = []
    for key in ("metadata", "litellm_metadata"):
        container = request_data.get(key)
        if isinstance(container, dict):
            slots.append(container)
        elif container is None and key == "metadata":
            created: dict[str, Any] = {}
            request_data[key] = created
            slots.append(created)
    return tuple(slots)


def record_compression_stats(
    request_data: dict[str, Any],
    stats: Mapping[str, Any],
    logging_obj: object | None = None,
) -> Optional[HeadroomCompressionStats]:
    """Write numeric Headroom stats onto request metadata (spend-log safe).

    Returns the parsed stats when recorded, else None.
    """
    parsed = parse_compression_stats(stats)
    if parsed is None:
        return None
    payload = parsed.as_dict()
    for meta in _metadata_slots(request_data):
        meta[HEADROOM_COMPRESSION_METADATA_KEY] = payload
        spend_logs_meta = meta.get("spend_logs_metadata")
        if not isinstance(spend_logs_meta, dict):
            spend_logs_meta = {}
            meta["spend_logs_metadata"] = spend_logs_meta
        spend_logs_meta[HEADROOM_COMPRESSION_METADATA_KEY] = payload

    # Passthrough routes (/v1/messages) may use a separate metadata dict on the
    # logging object; mirror so spend logs still get headroom_compression.
    if logging_obj is not None:
        litellm_params = getattr(logging_obj, "litellm_params", None)
        if isinstance(litellm_params, dict):
            log_meta = litellm_params.get("metadata")
            if not isinstance(log_meta, dict):
                log_meta = {}
                litellm_params["metadata"] = log_meta
            log_meta[HEADROOM_COMPRESSION_METADATA_KEY] = payload
            spend_logs_meta = log_meta.get("spend_logs_metadata")
            if not isinstance(spend_logs_meta, dict):
                spend_logs_meta = {}
                log_meta["spend_logs_metadata"] = spend_logs_meta
            spend_logs_meta[HEADROOM_COMPRESSION_METADATA_KEY] = payload

    return parsed


def extract_compression_stats_from_spend_metadata(
    metadata: object,
) -> Optional[HeadroomCompressionStats]:
    if not isinstance(metadata, Mapping):
        return None
    direct = parse_compression_stats(metadata.get(HEADROOM_COMPRESSION_METADATA_KEY))
    if direct is not None:
        return direct
    spend_logs_meta = metadata.get("spend_logs_metadata")
    if isinstance(spend_logs_meta, Mapping):
        return parse_compression_stats(spend_logs_meta.get(HEADROOM_COMPRESSION_METADATA_KEY))
    return None


@dataclass(frozen=True, slots=True)
class HeadroomSavingsAggregate:
    requests_with_stats: int
    requests_with_savings: int
    tokens_before: int
    tokens_after: int
    tokens_saved: int

    @property
    def compression_ratio(self) -> float:
        if self.tokens_before <= 0:
            return 1.0
        return self.tokens_after / self.tokens_before

    def as_dict(self) -> dict[str, int | float]:
        return {
            "requests_with_stats": self.requests_with_stats,
            "requests_with_savings": self.requests_with_savings,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "tokens_saved": self.tokens_saved,
            "compression_ratio": self.compression_ratio,
        }


def aggregate_compression_stats(
    rows: tuple[Optional[HeadroomCompressionStats], ...],
) -> HeadroomSavingsAggregate:
    requests_with_stats = 0
    requests_with_savings = 0
    tokens_before = 0
    tokens_after = 0
    tokens_saved = 0
    for stats in rows:
        if stats is None:
            continue
        requests_with_stats += 1
        tokens_before += stats.tokens_before
        tokens_after += stats.tokens_after
        tokens_saved += stats.tokens_saved
        if stats.tokens_saved > 0:
            requests_with_savings += 1
    return HeadroomSavingsAggregate(
        requests_with_stats=requests_with_stats,
        requests_with_savings=requests_with_savings,
        tokens_before=tokens_before,
        tokens_after=tokens_after,
        tokens_saved=tokens_saved,
    )


def parse_spend_log_metadata_field(raw: object) -> Optional[dict[str, Any]]:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        import json

        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None
