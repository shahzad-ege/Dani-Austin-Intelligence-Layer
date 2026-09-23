"""
parse_megaphone_backfill.py — Parses the real Megaphone Report Builder
CSV export (Sep 2026 historical backfill), built from an actual
confirmed file, not a guessed format.

REAL, CONFIRMED FORMAT: 4 quoted columns -- DAY, EPISODE TITLE,
DOWNLOADS, PLAYS. Numbers are quoted strings WITH embedded
thousand-separator commas (e.g. "20,965"), which a naive comma-split
would corrupt -- Python's csv module handles this correctly since it
respects quoting, but the numeric strings still need comma-stripping
before int() conversion.

REAL, CONFIRMED LIMITATION: despite exporting the full range back to
the podcast's actual inception (March 7, 2023), the earliest DAY value
present for ANY episode is October 2024 -- confirmed by checking the
earliest known episode directly, which appears in the export (697 rows)
but never with a date anywhere near its true 2023 publish window.
Megaphone's daily-granularity delivery data has a real retention window
of roughly 2 years; this is a platform limitation, not an export bug.
"""

import csv
import sys
from dataclasses import dataclass
from datetime import date


@dataclass
class DailyDownloadRow:
    episode_title: str
    day: date
    downloads: int
    plays: int

    def to_row(self) -> dict:
        return {
            "episode_title": self.episode_title,
            "day": self.day.isoformat(),
            "downloads": self.downloads,
            "plays": self.plays,
        }


def _parse_int(value: str) -> int:
    """Real format has thousand-separator commas inside quoted numeric
    strings (e.g. "20,965") -- strip commas before int() or this would
    raise or silently truncate."""
    cleaned = value.replace(",", "").strip()
    if not cleaned:
        return 0
    return int(cleaned)


def parse_file(filepath: str) -> tuple[list[DailyDownloadRow], list[str]]:
    """Returns (parsed_rows, warnings). Malformed individual rows are
    skipped with a warning, not silently dropped or allowed to crash
    the whole parse -- same resilience discipline used throughout this
    project's other parsers."""
    rows: list[DailyDownloadRow] = []
    warnings: list[str] = []

    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        expected_cols = {"DAY", "EPISODE TITLE", "DOWNLOADS", "PLAYS"}
        if reader.fieldnames is None or not expected_cols.issubset(set(reader.fieldnames)):
            warnings.append(f"Unexpected columns: {reader.fieldnames} -- expected {expected_cols}")
            return [], warnings

        for i, raw in enumerate(reader, start=2):  # start=2: header is row 1
            try:
                day = date.fromisoformat(raw["DAY"].strip())
            except (ValueError, KeyError):
                warnings.append(f"Row {i}: unparseable DAY {raw.get('DAY')!r} -- skipped")
                continue

            title = raw.get("EPISODE TITLE", "").strip()
            if not title:
                warnings.append(f"Row {i}: empty EPISODE TITLE -- skipped")
                continue

            try:
                downloads = _parse_int(raw.get("DOWNLOADS", "0"))
                plays = _parse_int(raw.get("PLAYS", "0"))
            except ValueError:
                warnings.append(f"Row {i}: unparseable DOWNLOADS/PLAYS ({raw.get('DOWNLOADS')!r}, {raw.get('PLAYS')!r}) -- skipped")
                continue

            rows.append(DailyDownloadRow(episode_title=title, day=day, downloads=downloads, plays=plays))

    return rows, warnings


def run(filepath: str) -> int:
    from writer import upsert_rows

    rows, warnings = parse_file(filepath)
    for w in warnings:
        print(f"[megaphone_backfill] WARNING: {w}")

    if not rows:
        print("[megaphone_backfill] No rows parsed.")
        return 0

    # REAL CONSIDERATION: this dataset is genuinely large (75,970 rows
    # in the actual Sep 2026 backfill) -- sending that in one request
    # would very likely fail on payload size or timeout. Batched in
    # chunks of 1000, matching a conservative, safe size rather than
    # guessing at Supabase's real limit.
    BATCH_SIZE = 1000
    total_written = 0
    row_dicts = [r.to_row() for r in rows]
    for i in range(0, len(row_dicts), BATCH_SIZE):
        batch = row_dicts[i:i + BATCH_SIZE]
        written = upsert_rows("podcast_episode_daily_downloads", batch)
        total_written += written
        print(f"[megaphone_backfill] Batch {i // BATCH_SIZE + 1}: wrote {written} row(s) (running total: {total_written})")

    print(f"[megaphone_backfill] Parsed {len(rows)} row(s), wrote {total_written} to Supabase.")
    return total_written


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python parse_megaphone_backfill.py path/to/export.csv")
        sys.exit(1)
    run(sys.argv[1])
