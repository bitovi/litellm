"""Unit tests for Bitovi Headroom compression savings helpers."""

from litellm_bitovi.proxy.headroom.savings import (
    HEADROOM_COMPRESSION_METADATA_KEY,
    aggregate_compression_stats,
    extract_compression_stats_from_spend_metadata,
    parse_compression_stats,
    record_compression_stats,
)


def test_parse_compression_stats_happy_path() -> None:
    stats = parse_compression_stats(
        {
            "tokens_before": 1000,
            "tokens_after": 700,
            "tokens_saved": 300,
            "compression_ratio": 0.7,
        }
    )
    assert stats is not None
    assert stats.tokens_before == 1000
    assert stats.tokens_after == 700
    assert stats.tokens_saved == 300
    assert stats.compression_ratio == 0.7


def test_parse_compression_stats_rejects_garbage() -> None:
    assert parse_compression_stats(None) is None
    assert parse_compression_stats({"tokens_before": "x"}) is None
    assert parse_compression_stats({}) is None


def test_record_compression_stats_writes_non_redacted_metadata() -> None:
    request_data: dict = {"metadata": {"applied_guardrails": ["headroom-compression"]}}
    recorded = record_compression_stats(
        request_data,
        {
            "tokens_before": 500,
            "tokens_after": 400,
            "tokens_saved": 100,
            "compression_ratio": 0.8,
            "transforms_applied": ["router:mixed:0.50"],
        },
    )
    assert recorded is not None
    meta = request_data["metadata"]
    assert meta[HEADROOM_COMPRESSION_METADATA_KEY] == {
        "tokens_before": 500,
        "tokens_after": 400,
        "tokens_saved": 100,
        "compression_ratio": 0.8,
    }
    assert meta["spend_logs_metadata"][HEADROOM_COMPRESSION_METADATA_KEY]["tokens_saved"] == 100
    # transforms must not be copied (keep spend metadata numeric-only)
    assert "transforms_applied" not in meta[HEADROOM_COMPRESSION_METADATA_KEY]


def test_record_creates_metadata_when_missing() -> None:
    request_data: dict = {}
    record_compression_stats(
        request_data,
        {"tokens_before": 10, "tokens_after": 8, "tokens_saved": 2, "compression_ratio": 0.8},
    )
    assert HEADROOM_COMPRESSION_METADATA_KEY in request_data["metadata"]


def test_extract_from_spend_metadata_nested_or_top_level() -> None:
    top = extract_compression_stats_from_spend_metadata(
        {HEADROOM_COMPRESSION_METADATA_KEY: {"tokens_before": 9, "tokens_after": 6, "tokens_saved": 3}}
    )
    assert top is not None and top.tokens_saved == 3
    nested = extract_compression_stats_from_spend_metadata(
        {
            "spend_logs_metadata": {
                HEADROOM_COMPRESSION_METADATA_KEY: {
                    "tokens_before": 9,
                    "tokens_after": 6,
                    "tokens_saved": 3,
                    "compression_ratio": 0.666,
                }
            }
        }
    )
    assert nested is not None and nested.tokens_before == 9


def test_aggregate_compression_stats() -> None:
    a = parse_compression_stats(
        {"tokens_before": 100, "tokens_after": 80, "tokens_saved": 20, "compression_ratio": 0.8}
    )
    b = parse_compression_stats(
        {"tokens_before": 100, "tokens_after": 100, "tokens_saved": 0, "compression_ratio": 1.0}
    )
    agg = aggregate_compression_stats((a, None, b))
    assert agg.requests_with_stats == 2
    assert agg.requests_with_savings == 1
    assert agg.tokens_before == 200
    assert agg.tokens_after == 180
    assert agg.tokens_saved == 20
