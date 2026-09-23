"""
test_parse_megaphone_backfill.py — Tests built against the REAL
confirmed Megaphone Report Builder export format (Sep 2026 backfill).
"""

import os
import sys
import csv
import tempfile
from datetime import date
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("DA_SUPABASE_URL", "https://fake.supabase.co")
os.environ.setdefault("DA_SUPABASE_SERVICE_KEY", "fake")

import parse_megaphone_backfill as pmb  # noqa: E402


def _write_csv(rows, headers=("DAY", "EPISODE TITLE", "DOWNLOADS", "PLAYS")):
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8")
    writer = csv.writer(f, quoting=csv.QUOTE_ALL)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    f.close()
    return f.name


def test_real_confirmed_format_parses_correctly():
    path = _write_csv([("2025-02-06", "I Blew Up My Life", "20,965", "21,853")])
    rows, warnings = pmb.parse_file(path)
    assert warnings == []
    assert len(rows) == 1
    assert rows[0].day == date(2025, 2, 6)
    assert rows[0].downloads == 20965
    assert rows[0].plays == 21853


def test_comma_in_large_numbers_stripped_correctly():
    """Real format confirmed: numbers like 20,965 are quoted WITH the
    thousand-separator comma still embedded -- must be stripped before
    int(), not naively split on."""
    path = _write_csv([("2025-01-01", "Test", "1,234,567", "89")])
    rows, _ = pmb.parse_file(path)
    assert rows[0].downloads == 1234567


def test_malformed_date_skipped_not_crash():
    path = _write_csv([
        ("2025-02-06", "Good Episode", "100", "50"),
        ("not-a-date", "Bad Episode", "100", "50"),
    ])
    rows, warnings = pmb.parse_file(path)
    assert len(rows) == 1
    assert len(warnings) == 1
    assert "unparseable DAY" in warnings[0]


def test_empty_title_skipped_not_crash():
    path = _write_csv([
        ("2025-02-06", "", "100", "50"),
    ])
    rows, warnings = pmb.parse_file(path)
    assert len(rows) == 0
    assert "empty EPISODE TITLE" in warnings[0]


def test_missing_downloads_defaults_to_zero():
    path = _write_csv([("2025-02-06", "Test", "", "50")])
    rows, warnings = pmb.parse_file(path)
    assert len(rows) == 1
    assert rows[0].downloads == 0
    assert rows[0].plays == 50


def test_unexpected_columns_reported_not_crash():
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8")
    f.write('"WRONG","COLUMNS"\n"a","b"\n')
    f.close()
    rows, warnings = pmb.parse_file(f.name)
    assert rows == []
    assert len(warnings) == 1
    assert "Unexpected columns" in warnings[0]


def test_run_writes_to_correct_table():
    path = _write_csv([("2025-02-06", "Test", "100", "50")])
    with patch("writer.upsert_rows", return_value=1) as mock_upsert:
        result = pmb.run(path)
    assert result == 1
    assert mock_upsert.call_args.args[0] == "podcast_episode_daily_downloads"


def test_real_uploaded_file_parses_with_zero_warnings():
    """Regression guard against the actual real backfill file, if
    present in this environment."""
    real_path = "/mnt/user-data/uploads/Custom_report_2023-03-07_-_2026-09-11.csv"
    if not os.path.exists(real_path):
        return  # not present in CI, skip silently
    rows, warnings = pmb.parse_file(real_path)
    assert len(rows) == 75970
    assert warnings == []
