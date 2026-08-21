"""
podstock_parse_pull.py — Converts the structured text block produced by the
Claude-in-Chrome Podstock scheduled task into podcast_metrics rows and
writes them to Supabase.

This is NOT a connector in the usual sense -- there's no Podstock API to
call (confirmed via deep research: no public API, no export feature found
anywhere in their docs/ToS/privacy policy). The actual data source is a
human-scheduled browser task running on Jordan's own machine, which
produces a text block in the exact format defined in
podstock_daily_pull_prompt.md. This script is the bridge from that text
block into the database, so the only manual step is running the browser
task -- not manually reformatting numbers into a CSV by hand.

WORKFLOW:
  1. Claude in Chrome runs the scheduled prompt against podstock.io
  2. Its text output gets saved to a file (or pasted into one)
  3. Run: python podstock_parse_pull.py path/to/pull.txt
  4. This parses it and writes to podcast_metrics

SCOPE, DELIBERATELY LIMITED: only the Overview (delivery, hours,
engagement) and Channels (followers) sections are parsed into
podcast_metrics -- these map cleanly onto its existing show/platform/
metric/date/value shape. Episodes, Schedule (ad bookings), and Audience
(age/gender/country) do NOT fit that shape well and are NOT parsed here.
Storing them would mean either distorting podcast_metrics with awkward
metric names, or designing new tables -- a real decision, not something to
guess at silently. They're logged as skipped, not dropped without a trace.

SHOW_ID: hardcoded to "dani-austin-show" as a placeholder, since there's
only one show. Revisit if this project ever needs to track more than one.
"""

import re
import sys
from datetime import date

from writer import upsert_rows

SHOW_ID = "dani-austin-show"


def _num(s: str) -> float:
    """Parses a number, stripping commas."""
    return float(s.replace(",", "").replace("%", "").strip())


def parse_pull(text: str, period_date: date | None = None) -> tuple[list[dict], list[str]]:
    """
    Parses the structured text block. Returns (rows, skipped_notes) --
    skipped_notes lists anything found in the text but not converted to a
    row, so nothing silently vanishes.
    """
    period_date = period_date or date.today()
    rows: list[dict] = []
    skipped: list[str] = []

    def add(platform: str, metric: str, value: float):
        rows.append({
            "show_id": SHOW_ID,
            "platform": platform,
            "metric": metric,
            "period_date": period_date.isoformat(),
            "value": value,
        })

    # --- Overview: per-platform delivery ---
    platform_delivery_patterns = [
        ("Spotify", "streams", r"Spotify Streams:\s*([\d,]+)"),
        ("Megaphone", "downloads", r"Megaphone Downloads:\s*([\d,]+)"),
        ("YouTube", "views", r"YouTube Views:\s*([\d,]+)"),
        ("Art19", "downloads", r"Art19 Downloads:\s*([\d,]+)"),
    ]
    for platform, metric, pattern in platform_delivery_patterns:
        m = re.search(pattern, text)
        if m:
            add(platform, metric, _num(m.group(1)))
        else:
            skipped.append(f"delivery metric not found: {platform} {metric}")

    # --- Overview: per-platform hours ---
    hours_section = re.search(r"Total hours:.*?(?=Time per delivery|$)", text, re.DOTALL)
    if hours_section:
        for platform in ["Spotify", "Apple", "YouTube"]:
            m = re.search(rf"{platform}:\s*([\d,]+)", hours_section.group(0))
            if m:
                add(platform, "hours_spent", _num(m.group(1)))
            else:
                skipped.append(f"hours not found for {platform}")

    # --- Overview: engagement totals (platform-agnostic, tagged "combined") ---
    engagement_patterns = [
        ("total_interactions", r"Engagements total:\s*([\d,]+)"),
        ("likes", r"Likes:\s*([\d,]+)"),
        ("comments", r"Comments:\s*([\d,]+)"),
        ("shares", r"Shares:\s*([\d,]+)"),
    ]
    for metric, pattern in engagement_patterns:
        m = re.search(pattern, text)
        if m:
            add("combined", metric, _num(m.group(1)))
        else:
            skipped.append(f"engagement metric not found: {metric}")

    rate_patterns = [
        ("engagement_rate_pct", r"Engagement rate:\s*([\d.]+)%"),
        ("positive_reaction_rate_pct", r"Positive reaction rate:\s*([\d.]+)%"),
        ("sharing_rate_pct", r"Sharing rate:\s*([\d.]+)%"),
        ("comment_rate_pct", r"Comment rate:\s*([\d.]+)%"),
    ]
    for metric, pattern in rate_patterns:
        m = re.search(pattern, text)
        if m:
            add("combined", metric, _num(m.group(1)))
        else:
            skipped.append(f"rate metric not found: {metric}")

    # --- Channels: followers/subscribers ---
    channels_section = re.search(r"CHANNELS.*?(?=SCHEDULE|AUDIENCE|$)", text, re.DOTALL)
    if channels_section:
        for platform in ["Spotify", "Apple", "YouTube"]:
            m = re.search(rf"{platform}:\s*([\d,]+)", channels_section.group(0))
            if m:
                add(platform, "subscribers", _num(m.group(1)))
            else:
                skipped.append(f"follower count not found for {platform}")

    # --- Explicitly out of scope for now, per the docstring ---
    if re.search(r"EPISODES", text):
        skipped.append("EPISODES section present but not parsed (per-episode grain doesn't fit current schema)")
    if re.search(r"SCHEDULE", text):
        skipped.append("SCHEDULE section present but not parsed (ad-booking data needs its own table, not podcast_metrics)")
    if re.search(r"AUDIENCE", text):
        skipped.append("AUDIENCE section present but not parsed (demographic breakdown needs a schema decision)")

    return rows, skipped


def run(filepath: str) -> int:
    with open(filepath) as f:
        text = f.read()

    rows, skipped = parse_pull(text)

    for note in skipped:
        print(f"[podstock_parse] SKIPPED: {note}")

    if not rows:
        print("[podstock_parse] No rows parsed -- check the input format matches the expected prompt output.")
        return 0

    return upsert_rows("podcast_metrics", rows)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python podstock_parse_pull.py path/to/pull.txt")
        sys.exit(1)
    count = run(sys.argv[1])
    print(f"Podstock parser: upserted {count} rows.")
