"""
test_podstock_parse_pull.py — Tests the Podstock text-block parser against
REAL data captured from actual Podstock pulls (not synthetic fixtures),
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
    metrics, _, _, _, _ = podstock_parse_pull.parse_pull(_load_real_pull(), period_date=date(2026, 8, 17))
    by_key = {(r["platform"], r["metric"]): r["value"] for r in metrics}

    assert by_key[("Spotify", "streams")] == 339866.0
    assert by_key[("Megaphone", "downloads")] == 305787.0
    assert by_key[("YouTube", "views")] == 64700.0
    assert by_key[("Art19", "downloads")] == 1590.0


def test_parses_hours_and_engagement_and_rates():
    metrics, _, _, _, _ = podstock_parse_pull.parse_pull(_load_real_pull(), period_date=date(2026, 8, 17))
    by_key = {(r["platform"], r["metric"]): r["value"] for r in metrics}

    assert by_key[("Spotify", "hours_spent")] == 113694.0
    # PRESERVED naming: this metric is "total_interactions", not
    # "engagements_total" -- a real regression caught and fixed during the
    # rewrite, since real historical data already used this name.
    assert by_key[("combined", "total_interactions")] == 1255.0
    assert by_key[("combined", "likes")] == 1008.0
    assert by_key[("combined", "engagement_rate_pct")] == 1.99
    assert by_key[("combined", "positive_reaction_rate_pct")] == 96.8


def test_parses_channel_followers():
    metrics, _, _, _, _ = podstock_parse_pull.parse_pull(_load_real_pull(), period_date=date(2026, 8, 17))
    by_key = {(r["platform"], r["metric"]): r["value"] for r in metrics}

    # PRESERVED naming: "subscribers", not "followers" -- same class of
    # regression as total_interactions above.
    assert by_key[("Spotify", "subscribers")] == 104369.0
    assert by_key[("Apple", "subscribers")] == 46365.0
    assert by_key[("YouTube", "subscribers")] == 8220.0


def test_pct_change_is_captured_not_silently_dropped():
    """The actual bug that started this whole rewrite: every %-change
    figure was being silently dropped. This confirms it's captured now."""
    metrics, _, _, _, _ = podstock_parse_pull.parse_pull(_load_real_pull(), period_date=date(2026, 8, 17))
    by_key = {(r["platform"], r["metric"]): r for r in metrics}

    assert by_key[("Spotify", "streams")]["pct_change"] == -23.0
    assert by_key[("combined", "total_interactions")]["pct_change"] == 13.0


def test_missing_metric_is_flagged_not_silently_skipped():
    """If the dashboard's format ever changes and a metric can't be found,
    that must be visible in `skipped`, not just absent from `rows` with no
    explanation."""
    incomplete_text = "OVERVIEW\nTotal delivery: 1,000 (0%)\n"
    metrics, _, _, _, skipped = podstock_parse_pull.parse_pull(incomplete_text, period_date=date(2026, 8, 17))

    assert len(metrics) == 1  # total_delivery itself DID parse
    assert any("Spotify" in s for s in skipped)


def test_run_writes_to_all_four_tables():
    """run() must write metrics, demographics, bookings, AND top-episode
    rows -- not just podcast_metrics like the original scope."""
    full_pull = '''PODSTOCK DAILY PULL — 2026-08-27
OVERVIEW
Total delivery: 695,222 (-11%)
EPISODES
Total episodes: 175 (all-time)
Top recent episode: "Test Episode" (July 16, 2026) — 69,827 total delivery
SCHEDULE (next 30 days)
Aug 27, 2026 — "Test"
  Brand X — Host Read (Mid-Roll #1) — Booked
AUDIENCE
Age (% of total delivery): 25-34: 50.5%
Gender: Female 89.9%
Country (% of total delivery): United States 92.6%
'''
    with patch("builtins.open", __import__("unittest.mock", fromlist=["mock_open"]).mock_open(read_data=full_pull)), \
         patch("podstock_parse_pull.upsert_rows") as mock_upsert:
        mock_upsert.return_value = 1
        podstock_parse_pull.run("fake_path.txt")

        tables_written = [call.args[0] for call in mock_upsert.call_args_list]
        assert "podcast_metrics" in tables_written
        assert "podcast_audience_demographics" in tables_written
        assert "podcast_ad_bookings" in tables_written
        assert "podcast_top_episode_snapshots" in tables_written


def test_time_per_delivery_converted_to_seconds():
    """21m 22s duration format wasn't fitting the numeric-only column --
    confirms it's now converted correctly."""
    text = "OVERVIEW\nTime per delivery: 21m 22s (+14%)\n"
    metrics, _, _, _, _ = podstock_parse_pull.parse_pull(text, period_date=date(2026, 8, 27))
    row = next(m for m in metrics if m["metric"] == "time_per_delivery_seconds")
    assert row["value"] == 21 * 60 + 22  # 1282 seconds
    assert row["pct_change"] == 14.0


def test_duplicate_country_entry_flagged_not_silently_overwritten():
    """A known real quirk: Podstock once displayed the same country twice.
    Must be flagged in skipped, and only one row kept, not silently
    duplicated or crashed on."""
    text = 'AUDIENCE\nCountry (% of total delivery): South Africa 0.2%, South Africa 0.2%, Spain 0.1%\n'
    _, demo, _, _, skipped = podstock_parse_pull.parse_pull(text, period_date=date(2026, 8, 27))

    south_africa_rows = [d for d in demo if d["dimension_value"] == "South Africa"]
    assert len(south_africa_rows) == 1
    assert any("South Africa" in s and "more than once" in s for s in skipped)


def test_booking_slot_name_with_internal_hyphen_not_split_incorrectly():
    """Real regression caught during testing: 'Mid-Roll #7' contains a
    literal hyphen (part of the compound word), which a naive dash-based
    separator regex wrongly split into brand='Mid' / slot='Roll #7'."""
    text = 'SCHEDULE (next 30 days)\nAug 27, 2026\n  Mid-Roll #7 — Available\n'
    _, _, bookings, _, _ = podstock_parse_pull.parse_pull(text, period_date=date(2026, 8, 27))

    assert len(bookings) == 1
    assert bookings[0]["slot_type"] == "Mid-Roll #7"
    assert bookings[0]["brand"] is None


if __name__ == "__main__":
    test_parses_all_platform_delivery_metrics()
    test_parses_hours_and_engagement_and_rates()
    test_parses_channel_followers()
    test_pct_change_is_captured_not_silently_dropped()
    test_missing_metric_is_flagged_not_silently_skipped()
    test_run_writes_to_all_four_tables()
    test_time_per_delivery_converted_to_seconds()
    test_duplicate_country_entry_flagged_not_silently_overwritten()
    test_booking_slot_name_with_internal_hyphen_not_split_incorrectly()
    print("All Podstock parser tests passed.")
