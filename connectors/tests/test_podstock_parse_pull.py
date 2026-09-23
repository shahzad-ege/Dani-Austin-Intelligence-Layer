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


# ---------- Real bugs found and fixed against a live pull (Sep 2026) ----------

def test_episode_prefixed_full_month_date_header_parses():
    """REAL bug: a live pull used 'Episode: September 10, 2026' -- the
    old regex required a bare 3-letter month abbreviation with no
    prefix, so this never matched. current_air_date stayed None,
    silently blocking every real booking line even though the
    booking-line regex itself parsed correctly."""
    text = """SCHEDULE (2026-09-08 to 2026-10-08)

Episode: September 10, 2026
Quince — Host Read (Mid-Roll #1) — Booked

AUDIENCE
"""
    metrics, demographics, bookings, top_episode, skipped = podstock_parse_pull.parse_pull(text, period_date=date(2026, 9, 8))
    assert len(bookings) == 1
    assert bookings[0]["episode_air_date"] == "2026-09-10"
    assert bookings[0]["brand"] == "Quince"


def test_time_per_delivery_with_comma_separator_parses():
    """REAL bug: two of three real pulls used 'Xm, Ys' (comma+space)
    rather than 'XmYs' -- the old regex had no room for a comma."""
    text = "OVERVIEW\nTime per delivery: 24m, 32s (+25%)\n"
    metrics, *_ = podstock_parse_pull.parse_pull(text, period_date=date(2026, 9, 8))
    matches = [m for m in metrics if m["metric"] == "time_per_delivery_seconds"]
    assert len(matches) == 1
    assert matches[0]["value"] == 24 * 60 + 32


def test_new_back_catalog_split_handles_all_three_real_formats():
    """REAL bug: three real pulls used three different formats for this
    field ('643,947/67,996', '643,947 (new) / 67,996 (back)', '623,006
    (new, -15%) / 67,161 (back, -8%)') -- the old regex required literal
    'New Releases'/'Back Catalog' text that never actually appeared in
    any real pull."""
    bare = "New vs. back catalog — delivery: 643,947/67,996, hours: 226,953/12,543\n"
    labeled_no_pct = "New vs. back catalog — delivery: 643,947 (new) / 67,996 (back), hours: 226,953 (new) / 12,543 (back)\n"
    labeled_with_pct = "New vs. back catalog — delivery: 623,006 (new, -15%) / 67,161 (back, -8%), hours: 261,200 (new, +6%) / 13,235 (back, -16%)\n"

    for text, expect_pct in [(bare, False), (labeled_no_pct, False), (labeled_with_pct, True)]:
        metrics, *_ = podstock_parse_pull.parse_pull(text, period_date=date(2026, 9, 8))
        new_delivery = [m for m in metrics if m["metric"] == "new_releases_delivery"]
        assert len(new_delivery) == 1, f"failed to parse: {text!r}"
        if expect_pct:
            assert new_delivery[0]["pct_change"] == -15.0
        else:
            assert new_delivery[0]["pct_change"] is None


def test_catalog_split_number_parsing_does_not_swallow_trailing_comma():
    """REAL bug caught while fixing the above: a loose [\\d,]+ number
    pattern greedily captured the separator comma before ', hours:',
    producing an unparseable '67,996,' value. Fixed with a precise
    thousand-separator pattern."""
    text = "New vs. back catalog — delivery: 643,947/67,996, hours: 226,953/12,543\n"
    metrics, *_ = podstock_parse_pull.parse_pull(text, period_date=date(2026, 9, 8))
    back_delivery = [m for m in metrics if m["metric"] == "back_catalog_delivery"]
    assert len(back_delivery) == 1
    assert back_delivery[0]["value"] == 67996.0  # not corrupted by a trailing comma


# ---------- Windows/Notepad text corruption, found after a real save-and-run ----------

def test_crlf_line_endings_do_not_break_parsing():
    """REAL bug: a manually saved Notepad file (Windows default is CRLF)
    correctly parsed metrics/demographics but silently dropped ALL
    bookings and the top-episode line, while the exact same text pasted
    directly worked fine. CRLF was the leading suspect since bookings
    rely on end-of-line anchors that simpler \\s*-based metric patterns
    don't."""
    text = """SCHEDULE (2026-09-08 to 2026-10-08)\r
\r
Episode: September 10, 2026\r
Quince — Host Read (Mid-Roll #1) — Booked\r
\r
AUDIENCE\r
"""
    metrics, demographics, bookings, top_episode, skipped = podstock_parse_pull.parse_pull(text, period_date=date(2026, 9, 8))
    assert len(bookings) == 1
    assert bookings[0]["brand"] == "Quince"


def test_smart_quotes_around_episode_title_do_not_break_parsing():
    """REAL bug, same investigation: Notepad/Windows commonly
    autocorrects straight quotes to curly ones. The top-episode regex
    requires a literal straight quote around the title."""
    text = 'EPISODES\nTop recent episode: \u201cWhy Moving to Nashville Changed Everything\u201d — 71,291 total delivery\n'
    metrics, demographics, bookings, top_episode, skipped = podstock_parse_pull.parse_pull(text, period_date=date(2026, 9, 8))
    assert len(top_episode) == 1
    assert top_episode[0]["episode_title"] == "Why Moving to Nashville Changed Everything"


def test_both_corruptions_together_still_parse_correctly():
    text = 'EPISODES\r\nTop recent episode: \u201cWhy Moving to Nashville Changed Everything\u201d — 71,291 total delivery\r\n'
    metrics, demographics, bookings, top_episode, skipped = podstock_parse_pull.parse_pull(text, period_date=date(2026, 9, 8))
    assert len(top_episode) == 1
    assert top_episode[0]["episode_title"] == "Why Moving to Nashville Changed Everything"


def test_run_reads_file_as_utf8_explicitly():
    """REAL bug, confirmed definitively via direct codepoint diagnosis on
    Shahzad's actual Windows machine: run()'s open(filepath) had no
    explicit encoding, defaulting to the OS locale encoding. Linux
    (this test environment) defaults to UTF-8, so this was invisible
    here -- but Windows commonly defaults to cp1252, which misreads a
    UTF-8 em-dash's bytes (E2 80 94) as garbage ('â€”'), silently
    breaking every dash-dependent match while pure-ASCII fields parsed
    fine. Reproduced exactly: reading the same UTF-8 file as cp1252
    turns a real em-dash match into None. This test guards the fix by
    asserting the actual open() call specifies UTF-8."""
    import inspect
    source = inspect.getsource(podstock_parse_pull.run)
    assert 'encoding="utf-8"' in source or "encoding='utf-8'" in source
