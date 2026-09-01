"""
podstock_parse_pull.py — Converts the structured text block produced by the
Claude-in-Chrome Podstock scheduled task into rows across FOUR tables and
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
  4. This parses it and writes to podcast_metrics, podcast_audience_demographics,
     podcast_ad_bookings, and podcast_top_episode_snapshots

HISTORY: originally scoped to Overview + Channels only, since Episodes/
Schedule/Audience didn't fit podcast_metrics' plain metric shape. Extended
after a manual gap-check against a real pull found several genuine misses:
pct_change was being silently dropped everywhere, time_per_delivery's
duration format ("21m 22s") wasn't handled, episode platform-split was
skipped, and the named top episode had nowhere to go. Three new tables
were added rather than distorting podcast_metrics to force-fit them.

KNOWN LIMITATION, not fixed: if Podstock ever displays the same country
twice with different values (observed once for South Africa on a real
pull), only one row can be stored per country per day -- the unique
constraint on podcast_audience_demographics means a second distinct entry
would silently overwrite the first. No code fix attempted since it's
unclear what a genuine second entry would even represent.

SHOW_ID: hardcoded to "dani-austin-show" as a placeholder, since there's
only one show. Revisit if this project ever needs to track more than one.
"""

import re
import sys
from datetime import date, datetime

from writer import upsert_rows

SHOW_ID = "dani-austin-show"


def _num(s: str) -> float:
    """Parses a number, stripping commas."""
    return float(s.replace(",", "").replace("%", "").strip())


def _duration_to_seconds(minutes: str, seconds: str) -> int:
    """Converts a 'Xm Ys' duration string's captured groups to total seconds."""
    return int(minutes) * 60 + int(seconds)


def _extract_value_and_pct(pattern: str, text: str) -> tuple:
    """
    Matches a "Label: NUMBER (+/-X%)" style line and returns (value, pct).
    The pct group is optional in the regex itself -- if it's absent, pct
    comes back None rather than skipping the value.
    """
    m = re.search(pattern, text)
    if not m:
        return None, None
    value = _num(m.group(1))
    pct = None
    if m.lastindex and m.lastindex >= 2 and m.group(2):
        pct = _num(m.group(2))
    return value, pct


def _try_parse_date(date_str):
    """Best-effort parse of dates like 'Aug 27, 2026' or 'July 16, 2026' into
    ISO format. Returns None (not a guess) if the format doesn't match."""
    if not date_str:
        return None
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_pull(text: str, period_date=None):
    """
    Parses the structured text block. Returns
    (metric_rows, demographic_rows, booking_rows, top_episode_rows, skipped_notes) --
    skipped_notes lists anything found in the text but not converted to a
    row, so nothing silently vanishes.
    """
    period_date = period_date or date.today()
    metric_rows = []
    demographic_rows = []
    booking_rows = []
    top_episode_rows = []
    skipped = []

    def add(platform, metric, value, pct_change=None):
        metric_rows.append({
            "show_id": SHOW_ID,
            "platform": platform,
            "metric": metric,
            "period_date": period_date.isoformat(),
            "value": value,
            "pct_change": pct_change,
        })

    # --- Overview: total delivery + per-platform delivery, each with pct_change ---
    delivery_patterns = [
        ("combined", "total_delivery", r"Total delivery:\s*([\d,]+)\s*\(([+-]?\d+)%\)"),
        ("Spotify", "streams", r"Spotify Streams:\s*([\d,]+)\s*\(([+-]?\d+)%\)"),
        ("Megaphone", "downloads", r"Megaphone Downloads:\s*([\d,]+)\s*\(([+-]?\d+)%\)"),
        ("YouTube", "views", r"YouTube Views:\s*([\d,]+)\s*\(([+-]?\d+)%\)"),
        ("Art19", "downloads", r"Art19 Downloads:\s*([\d,]+)\s*\(([+-]?\d+)%\)"),
    ]
    for platform, metric, pattern in delivery_patterns:
        value, pct = _extract_value_and_pct(pattern, text)
        if value is not None:
            add(platform, metric, value, pct)
        else:
            skipped.append(f"delivery metric not found: {platform} {metric}")

    # --- Overview: total hours + per-platform hours ---
    hours_total_value, hours_total_pct = _extract_value_and_pct(
        r"Total hours:\s*([\d,]+)\s*\(([+-]?\d+)%\)", text)
    if hours_total_value is not None:
        add("combined", "hours_spent", hours_total_value, hours_total_pct)
    else:
        skipped.append("total hours not found")

    hours_section = re.search(r"Total hours:.*?(?=Time per delivery|$)", text, re.DOTALL)
    if hours_section:
        for platform in ["Spotify", "Apple", "YouTube"]:
            value, pct = _extract_value_and_pct(rf"{platform}:\s*([\d,]+)\s*\(([+-]?\d+)%\)", hours_section.group(0))
            if value is not None:
                add(platform, "hours_spent", value, pct)
            else:
                skipped.append(f"hours not found for {platform}")

    # --- Overview: time per delivery, duration format converted to seconds ---
    m = re.search(r"Time per delivery:\s*(\d+)m\s*(\d+)s\s*\(([+-]?\d+)%\)", text)
    if m:
        seconds = _duration_to_seconds(m.group(1), m.group(2))
        add("combined", "time_per_delivery_seconds", seconds, _num(m.group(3)))
    else:
        skipped.append("time per delivery (combined) not found or not in Xm Ys format")

    for platform_match in re.finditer(r"(\w+)\s+(\d+)m\s*(\d+)s\s*\(([+-]?\d+)%\)", text):
        platform_name = platform_match.group(1)
        if platform_name not in ("YouTube", "Spotify", "Apple"):
            continue
        seconds = _duration_to_seconds(platform_match.group(2), platform_match.group(3))
        add(platform_name, "time_per_delivery_seconds", seconds, _num(platform_match.group(4)))

    # --- Overview: new releases vs. back catalog, delivery and hours ---
    delivery_half = re.search(
        r"delivery:\s*New Releases\s*([\d,]+)\s*\(([+-]?\d+)%\)\s*/\s*Back Catalog\s*([\d,]+)\s*\(([+-]?\d+)%\)", text)
    if delivery_half:
        add("combined", "new_releases_delivery", _num(delivery_half.group(1)), _num(delivery_half.group(2)))
        add("combined", "back_catalog_delivery", _num(delivery_half.group(3)), _num(delivery_half.group(4)))
    else:
        skipped.append("new releases/back catalog delivery split not found")

    hours_half = re.search(
        r"hours:\s*New Releases\s*([\d,]+)\s*\(([+-]?\d+)%\)\s*/\s*Back Catalog\s*([\d,]+)\s*\(([+-]?\d+)%\)", text)
    if hours_half:
        add("combined", "new_releases_hours", _num(hours_half.group(1)), _num(hours_half.group(2)))
        add("combined", "back_catalog_hours", _num(hours_half.group(3)), _num(hours_half.group(4)))
    else:
        skipped.append("new releases/back catalog hours split not found")

    # --- Overview: engagement totals ---
    engagement_patterns = [
        ("total_interactions", r"Engagements total:\s*([\d,]+)\s*\(([+-]?\d+)%\)"),
        ("likes", r"Likes:\s*([\d,]+)\s*\(([+-]?\d+)%\)"),
        ("comments", r"Comments:\s*([\d,]+)\s*\(([+-]?\d+)%\)"),
        ("shares", r"Shares:\s*([\d,]+)\s*\(([+-]?\d+)%\)"),
    ]
    for metric, pattern in engagement_patterns:
        value, pct = _extract_value_and_pct(pattern, text)
        if value is not None:
            add("combined", metric, value, pct)
        else:
            skipped.append(f"engagement metric not found: {metric}")

    rate_patterns = [
        ("engagement_rate_pct", r"Engagement rate:\s*([\d.]+)%\s*\(([+-]?\d+)%\)"),
        ("positive_reaction_rate_pct", r"Positive reaction rate:\s*([\d.]+)%\s*\(([+-]?\d+)%\)"),
        ("sharing_rate_pct", r"Sharing rate:\s*([\d.]+)%\s*\(([+-]?\d+)%\)"),
        ("comment_rate_pct", r"Comment rate:\s*([\d.]+)%\s*\(([+-]?\d+)%\)"),
    ]
    for metric, pattern in rate_patterns:
        value, pct = _extract_value_and_pct(pattern, text)
        if value is not None:
            add("combined", metric, value, pct)
        else:
            skipped.append(f"rate metric not found: {metric}")

    # --- Episodes: aggregate stats + platform split + top episode ---
    episodes_section = re.search(r"EPISODES(.*?)(?=CHANNELS|$)", text, re.DOTALL)
    if episodes_section:
        es = episodes_section.group(1)
        m = re.search(r"Total episodes:\s*([\d,]+)", es)
        if m:
            add("combined", "total_episodes", _num(m.group(1)))
        m = re.search(r"Avg delivery/episode:\s*([\d,]+)", es)
        if m:
            add("combined", "avg_delivery_per_episode", _num(m.group(1)))

        for label, platform in [("Spotify", "Spotify"), ("Downloads", "Downloads"), ("YouTube", "YouTube")]:
            m = re.search(rf"{label}[^:]*?([\d.]+)%/([\d,]+)", es)
            if m:
                add(platform, "episode_delivery_pct", _num(m.group(1)))
                add(platform, "episode_delivery_count", _num(m.group(2)))
            else:
                skipped.append(f"episode platform split not found for {label}")

        m = re.search(r'Top recent episode:\s*"([^"]+)"(?:\s*\(([^)]+)\))?\s*[–—]\s*([\d,]+)\s*total delivery', es)
        if m:
            title, air_date_str, delivery = m.group(1), m.group(2), _num(m.group(3))
            top_episode_rows.append({
                "show_id": SHOW_ID,
                "episode_title": title,
                "episode_air_date": _try_parse_date(air_date_str),
                "total_delivery": delivery,
                "pulled_at": period_date.isoformat(),
            })
        else:
            skipped.append("top episode line not found or didn't match expected format")
    else:
        skipped.append("EPISODES section not found at all")

    # --- Channels: followers/subscribers ---
    channels_section = re.search(r"CHANNELS(.*?)(?=SCHEDULE|AUDIENCE|$)", text, re.DOTALL)
    if channels_section:
        cs = channels_section.group(0)
        total_value, total_pct = _extract_value_and_pct(r"Total followers:\s*([\d,]+)\s*\(([+-]?\d+)%\)", cs)
        if total_value is not None:
            add("combined", "followers_total", total_value, total_pct)
        for platform in ["Spotify", "Apple", "YouTube"]:
            value, pct = _extract_value_and_pct(rf"{platform}:\s*([\d,]+)\s*\(([+-]?\d+)%\)", cs)
            if value is not None:
                add(platform, "subscribers", value, pct)
            else:
                skipped.append(f"follower count not found for {platform} "
                               f"(may genuinely not be displayed this pull -- not necessarily an error)")
        m = re.search(r"Active connections:\s*(\d+)", cs)
        if m:
            add("combined", "active_connections", _num(m.group(1)))

    # --- Schedule: ad-slot bookings, separate table (deal-level, not a metric) ---
    schedule_section = re.search(r"SCHEDULE.*?\n(.*?)(?=AUDIENCE|$)", text, re.DOTALL)
    if schedule_section:
        current_air_date = None
        current_title = None
        for line in schedule_section.group(1).splitlines():
            line = line.strip()
            if not line:
                continue
            date_header = re.match(r'^([A-Z][a-z]{2}\s+\d{1,2},\s*\d{4})(?:\s*[–—]\s*"([^"]+)")?$', line)
            if date_header:
                current_air_date = _try_parse_date(date_header.group(1))
                current_title = date_header.group(2)
                continue
            booking = re.match(r'^(?:(.+?)\s*[–—]\s*)?(.+?)\s*[–—]\s*(Booked|Available)(?:\s*\(([^)]+)\))?$', line)
            if booking and current_air_date:
                brand, slot_type, status, notes = booking.groups()
                booking_rows.append({
                    "show_id": SHOW_ID,
                    "episode_air_date": current_air_date,
                    "episode_title": current_title,
                    "brand": brand,
                    "slot_type": slot_type,
                    "status": status,
                    "notes": notes,
                    "pulled_at": period_date.isoformat(),
                })
        if not booking_rows:
            skipped.append("SCHEDULE section present but no booking lines matched the expected format")
    else:
        skipped.append("SCHEDULE section not found")

    # --- Audience: age/gender/country, separate table (dimension pattern) ---
    audience_section = re.search(r"AUDIENCE(.*)$", text, re.DOTALL)
    if audience_section:
        aus = audience_section.group(1)

        age_line = re.search(r"Age.*?:\s*(.+)", aus)
        if age_line:
            for bracket, pct in re.findall(r"([\d]+-?[\d]*\+?):\s*([\d.]+)%", age_line.group(1)):
                demographic_rows.append({
                    "show_id": SHOW_ID, "dimension": "age", "dimension_value": bracket,
                    "value": _num(pct), "period_date": period_date.isoformat(),
                })

        gender_line = re.search(r"Gender:\s*(.+)", aus)
        if gender_line:
            for gender, pct in re.findall(r"([A-Za-z ]+?)\s*([\d.]+)%", gender_line.group(1)):
                demographic_rows.append({
                    "show_id": SHOW_ID, "dimension": "gender", "dimension_value": gender.strip(),
                    "value": _num(pct), "period_date": period_date.isoformat(),
                })

        country_line = re.search(r"Country.*?:\s*(.+)", aus)
        if country_line:
            seen_countries = set()
            for country, pct in re.findall(r"([A-Za-z][A-Za-z .]+?)\s+([\d.]+)%", country_line.group(1)):
                country = country.strip()
                if country in seen_countries:
                    skipped.append(f"country '{country}' appeared more than once in the pull -- "
                                   f"only the first occurrence was kept (known Podstock display quirk, see docstring)")
                    continue
                seen_countries.add(country)
                demographic_rows.append({
                    "show_id": SHOW_ID, "dimension": "country", "dimension_value": country,
                    "value": _num(pct), "period_date": period_date.isoformat(),
                })

        if not demographic_rows:
            skipped.append("AUDIENCE section present but no age/gender/country lines matched")
    else:
        skipped.append("AUDIENCE section not found")

    return metric_rows, demographic_rows, booking_rows, top_episode_rows, skipped


def run(filepath: str) -> int:
    with open(filepath) as f:
        text = f.read()

    metric_rows, demographic_rows, booking_rows, top_episode_rows, skipped = parse_pull(text)

    for note in skipped:
        print(f"[podstock_parse] SKIPPED: {note}")

    total_written = 0
    if metric_rows:
        total_written += upsert_rows("podcast_metrics", metric_rows)
    if demographic_rows:
        total_written += upsert_rows("podcast_audience_demographics", demographic_rows)
    if booking_rows:
        total_written += upsert_rows("podcast_ad_bookings", booking_rows)
    if top_episode_rows:
        total_written += upsert_rows("podcast_top_episode_snapshots", top_episode_rows)

    if not total_written:
        print("[podstock_parse] No rows parsed -- check the input format matches the expected prompt output.")

    print(f"[podstock_parse] {len(metric_rows)} metric row(s), {len(demographic_rows)} demographic row(s), "
          f"{len(booking_rows)} booking row(s), {len(top_episode_rows)} top-episode row(s)")
    return total_written


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python podstock_parse_pull.py path/to/pull.txt")
        sys.exit(1)
    count = run(sys.argv[1])
    print(f"Podstock parser: upserted {count} rows.")
