"""
test_podstock_parse_pull.py — Tests the Podstock text-block parser against
REAL data captured from an actual Podstock pull (not synthetic fixtures),
since there's no API to mock against here -- the "API response" IS a
human-readable text block, and testing against a made-up version of that
would risk missing real formatting quirks the real dashboard produces.
"""

import os
import sys
from datetime import date
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import podstock_parse_pull  # noqa: E402

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "real_podstock_pull_2026-08-17.txt")


def _load_real_pull() -> str:
    with open(FIXTURE_PATH) as f:
        return f.read()


def test_parses_all_platform_delivery_metrics():
    rows, _ = podstock_parse_pull.parse_pull(_load_real_pull(), period_date=date(2026, 8, 17))
    by_key = {(r["platform"], r["metric"]): r["value"] for r in rows}

    assert by_key[("Spotify", "streams")] == 339866.0
    assert by_key[("Megaphone", "downloads")] == 305787.0
    assert by_key[("YouTube", "views")] == 64700.0
    assert by_key[("Art19", "downloads")] == 1590.0


def test_parses_hours_and_engagement_and_rates():
    rows, _ = podstock_parse_pull.parse_pull(_load_real_pull(), period_date=date(2026, 8, 17))
    by_key = {(r["platform"], r["metric"]): r["value"] for r in rows}

    assert by_key[("Spotify", "hours_spent")] == 113694.0
    assert by_key[("combined", "total_interactions")] == 1255.0
    assert by_key[("combined", "likes")] == 1008.0
    assert by_key[("combined", "engagement_rate_pct")] == 1.99
    assert by_key[("combined", "positive_reaction_rate_pct")] == 96.8


def test_parses_channel_followers():
    rows, _ = podstock_parse_pull.parse_pull(_load_real_pull(), period_date=date(2026, 8, 17))
    by_key = {(r["platform"], r["metric"]): r["value"] for r in rows}

    assert by_key[("Spotify", "subscribers")] == 104369.0
    assert by_key[("Apple", "subscribers")] == 46365.0
    assert by_key[("YouTube", "subscribers")] == 8220.0


def test_out_of_scope_sections_are_flagged_not_silently_dropped():
    """Episodes, Schedule, and Audience data exist in the real pull but
    don't fit podcast_metrics' shape -- they must be explicitly named as
    skipped, not silently vanish with no trace."""
    _, skipped = podstock_parse_pull.parse_pull(_load_real_pull(), period_date=date(2026, 8, 17))

    skipped_text = " ".join(skipped)
    assert "EPISODES" in skipped_text
    assert "SCHEDULE" in skipped_text
    assert "AUDIENCE" in skipped_text


def test_missing_metric_is_flagged_not_silently_skipped():
    """If the dashboard's format ever changes and a metric can't be found,
    that must be visible in `skipped`, not just absent from `rows` with no
    explanation."""
    incomplete_text = "OVERVIEW\nTotal delivery: 1,000 (0%)\n"
    rows, skipped = podstock_parse_pull.parse_pull(incomplete_text, period_date=date(2026, 8, 17))

    assert len(rows) == 0
    assert any("Spotify" in s for s in skipped)


def test_run_writes_parsed_rows_via_upsert():
    with patch("podstock_parse_pull.upsert_rows") as mock_upsert:
        mock_upsert.return_value = 18
        count = podstock_parse_pull.run(FIXTURE_PATH)

        assert count == 18
        table, rows = mock_upsert.call_args[0]
        assert table == "podcast_metrics"
        assert len(rows) == 18
        assert all(r["show_id"] == "dani-austin-show" for r in rows)


if __name__ == "__main__":
    test_parses_all_platform_delivery_metrics()
    test_parses_hours_and_engagement_and_rates()
    test_parses_channel_followers()
    test_out_of_scope_sections_are_flagged_not_silently_dropped()
    test_missing_metric_is_flagged_not_silently_skipped()
    test_run_writes_parsed_rows_via_upsert()
    print("All Podstock parser tests passed.")
