"""
manual_forecast_connector.py — Ingests Katelyn's Revenue Projections and
Cash Forecast files as CSV exports.

There's no API for these — they're Excel workbooks maintained by hand.
The realistic automation here is: Katelyn (or whoever owns the sheet)
exports to CSV into a known folder/path, and this script picks it up on
the same daily schedule as the API connectors.

Expected CSV formats (confirm against Katelyn's real files before first run
— these are the shapes implied by the framework doc, not confirmed):

  revenue_forecast.csv
      month,business_unit,estimate,goal
      2026-09-01,Affiliate,15000,18000
      2026-09-01,Partnerships,40000,45000

  cash_flow_forecast.csv
      month,line_item,value
      2026-09-01,Payroll,-22000
      2026-09-01,Projected Revenue,55000

Requires (via env vars):
    REVENUE_FORECAST_CSV_PATH   -- path to the revenue forecast CSV
    CASH_FLOW_FORECAST_CSV_PATH -- path to the cash flow forecast CSV
"""

import os
import csv
from datetime import date

from models import CashBalance  # noqa: F401 (kept for symmetry/future use)
from writer import upsert_rows

REVENUE_FORECAST_CSV_PATH = os.environ.get("REVENUE_FORECAST_CSV_PATH", "data/revenue_forecast.csv")
CASH_FLOW_FORECAST_CSV_PATH = os.environ.get("CASH_FLOW_FORECAST_CSV_PATH", "data/cash_flow_forecast.csv")


def _parse_month(value: str) -> str:
    """Normalizes a month value to YYYY-MM-01 regardless of day given."""
    parsed = date.fromisoformat(value[:10])
    return date(parsed.year, parsed.month, 1).isoformat()


def load_revenue_forecast(path: str = REVENUE_FORECAST_CSV_PATH) -> int:
    if not os.path.exists(path):
        print(f"[manual_forecast] revenue forecast CSV not found at {path}, skipping.")
        return 0

    rows = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            rows.append(
                {
                    "month": _parse_month(row["month"]),
                    "business_unit": row["business_unit"],
                    "estimate": float(row["estimate"]) if row.get("estimate") else None,
                    "goal": float(row["goal"]) if row.get("goal") else None,
                }
            )
    return upsert_rows("da_revenue_forecast", rows)


def load_cash_flow_forecast(path: str = CASH_FLOW_FORECAST_CSV_PATH) -> int:
    if not os.path.exists(path):
        print(f"[manual_forecast] cash flow forecast CSV not found at {path}, skipping.")
        return 0

    rows = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            rows.append(
                {
                    "month": _parse_month(row["month"]),
                    "line_item": row["line_item"],
                    "value": float(row["value"]),
                }
            )
    return upsert_rows("da_cash_flow_forecast", rows)


def run() -> int:
    return load_revenue_forecast() + load_cash_flow_forecast()


if __name__ == "__main__":
    count = run()
    print(f"Manual forecast connector: upserted {count} rows total.")
