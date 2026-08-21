"""
manual_affiliate_connector.py — Ingests Amazon + LTK affiliate exports.

Research confirmed neither source has a workable programmatic path today:
  - Amazon PA-API returns product catalog data only, NOT commission/earnings.
    Real commission data lives in the Associates dashboard, or via the
    S3 "Activity Report" data feed — which requires requesting credentials
    directly from Amazon Associates support (not self-serve). Until/unless
    that's granted, dashboard CSV export is the realistic path.
  - LTK has no public creator/agency API. Their Creator dashboard supports
    CSV/data export, which is the supported mechanism today.

This script assumes both exports land as CSVs in a known location, in
whatever column shape each dashboard actually produces — the shape below
is inferred from the reporting spec and needs a real sample file to confirm.

Expected CSV format (confirm against real exports before first run):
  affiliate_revenue.csv
      month,platform,gross_commission,clicks
      2026-09-01,Amazon,1200.50,3400
      2026-09-01,LTK,2100.00,1900

Requires (via env vars):
    AFFILIATE_REVENUE_CSV_PATH -- path to the combined/normalized affiliate CSV
"""

import os
import csv
from datetime import date

from writer import upsert_rows

AFFILIATE_REVENUE_CSV_PATH = os.environ.get("AFFILIATE_REVENUE_CSV_PATH", "data/affiliate_revenue.csv")


def _parse_month(value: str) -> str:
    parsed = date.fromisoformat(value[:10])
    return date(parsed.year, parsed.month, 1).isoformat()


def run(path: str = AFFILIATE_REVENUE_CSV_PATH) -> int:
    if not os.path.exists(path):
        print(f"[manual_affiliate] CSV not found at {path}, skipping.")
        return 0

    rows = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            rows.append(
                {
                    "month": _parse_month(row["month"]),
                    "platform": row["platform"],
                    "gross_commission": float(row["gross_commission"]) if row.get("gross_commission") else None,
                    "clicks": int(row["clicks"]) if row.get("clicks") else None,
                }
            )
    return upsert_rows("affiliate_revenue", rows)


if __name__ == "__main__":
    count = run()
    print(f"Manual affiliate connector: upserted {count} rows.")
