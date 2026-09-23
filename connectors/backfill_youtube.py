"""
backfill_youtube.py — Full historical backfill: ALL real videos (not
the 50-video cap the regular connector uses), and Analytics/traffic-
source data over each video's own real lifetime (publish date to
today), not just the regular connector's 7-day rolling window.

WHY A SEPARATE SCRIPT, same reasoning as the TikTok backfill: the
regular run() is deliberately scoped narrow (7-day window, real API
quota courtesy) for ongoing daily use. A full backfill is a genuinely
different, one-time operation.
"""

import sys
from datetime import date
import youtube_connector as yc


def main() -> None:
    print("Fetching ALL real videos on the channel (no cap)...")
    # max_videos set very high -- fetch_video_stats() already paginates
    # internally via pageToken; this just removes the artificial ceiling.
    stats_records = yc.fetch_video_stats(max_videos=10_000)
    print(f"Total real videos found: {len(stats_records)}\n")

    if not stats_records:
        print("No videos found -- nothing to backfill.")
        return

    from writer import upsert_rows
    stats_written = upsert_rows("youtube_video_stats", [r.to_row() for r in stats_records])
    print(f"Video stats: {stats_written} row(s) written.\n")

    today = date.today()
    all_analytics = []
    all_traffic = []

    for i, stat in enumerate(stats_records, 1):
        # Real, full lifetime window: this video's own publish date
        # through today -- not the regular connector's 7-day window.
        start = stat.published_at
        print(f"[{i}/{len(stats_records)}] {stat.video_id} (published {start}): fetching real lifetime analytics...")

        try:
            analytics = yc.fetch_video_analytics([stat.video_id], start, today)
            all_analytics.extend(analytics)
        except RuntimeError as e:
            print(f"  Analytics fetch failed, stopping backfill here (real credentials issue): {e}")
            break

        try:
            traffic = yc.fetch_traffic_sources([stat.video_id], start, today)
            all_traffic.extend(traffic)
        except RuntimeError as e:
            print(f"  Traffic source fetch failed for this video: {e}")

    print(f"\nReal totals: {len(all_analytics)} analytics row(s), {len(all_traffic)} traffic source row(s).")

    analytics_written = upsert_rows("youtube_video_analytics", [r.to_row() for r in all_analytics]) if all_analytics else 0
    traffic_written = upsert_rows("youtube_traffic_sources", [r.to_row() for r in all_traffic]) if all_traffic else 0

    print(f"\nWrote {analytics_written} analytics row(s), {traffic_written} traffic source row(s).")
    print(f"Backfill complete: {stats_written + analytics_written + traffic_written} total rows written.")


if __name__ == "__main__":
    main()
