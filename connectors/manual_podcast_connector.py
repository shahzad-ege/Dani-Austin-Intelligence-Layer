"""
manual_podcast_connector.py — Ingests podcast metrics until Podstock access
is resolved.

Research found no public developer API for Podstock — it's a closed B2B
platform that itself pulls data FROM your hosting platforms (Spotify,
Apple, YouTube, Megaphone/Art19), rather than exposing an outbound feed.
Access, if any, would come through the Dear Media relationship as a
scheduled export or partner data feed — not a self-serve API key.

This script is a placeholder: it ingests whatever CSV export Dear Media
can currently provide (manually, for now), in the shape podcast_metrics
expects. Once Dear Media confirms an actual access model (API, scheduled
export, or "manual only"), replace or extend this connector accordingly —
don't build further automation on a guess.

Expected CSV format (placeholder — confirm against whatever Dear Media
can actually produce):
  podcast_metrics.csv
      show_id,platform,metric,period_date,value
      dani-austin-show,Spotify,streams,2026-09-01,12000
      dani-austin-show,Apple,downloads,2026-09-01,8500

Requires (via env vars):
    PODCAST_METRICS_CSV_PATH -- path to the podcast metrics CSV
"""

import os
import csv

from writer import upsert_rows

PODCAST_METRICS_CSV_PATH = os.environ.get("PODCAST_METRICS_CSV_PATH", "data/podcast_metrics.csv")


def run(path: str = PODCAST_METRICS_CSV_PATH) -> int:
    if not os.path.exists(path):
        print(f"[manual_podcast] CSV not found at {path}, skipping (expected until Dear Media confirms access).")
        return 0

    rows = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            rows.append(
                {
                    "show_id": row["show_id"],
                    "platform": row["platform"],
                    "metric": row["metric"],
                    "period_date": row["period_date"],
                    "value": float(row["value"]),
                }
            )
    return upsert_rows("podcast_metrics", rows)


if __name__ == "__main__":
    count = run()
    print(f"Manual podcast connector: upserted {count} rows.")
