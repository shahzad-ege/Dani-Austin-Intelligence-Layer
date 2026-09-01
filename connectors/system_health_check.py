"""
system_health_check.py — Comprehensive LIVE health check for the Dani
Austin Supabase project.

This is DIFFERENT from the pytest suite in tests/, and deliberately so:
pytest tests CODE correctness against mocked data (does the parser handle
this input correctly, does the connector call the right endpoint). This
script checks the REAL, CURRENT STATE of the live database -- is the data
actually fresh, do the numbers actually add up, are there orphaned or
duplicate records sitting in production right now. A connector can pass
every unit test and still leave the real database in a bad state (this
project has hit that exact situation more than once -- e.g. the account
dedup issue, the writer.py registration gaps found during the last full
regression pass).

USAGE:
    python system_health_check.py

Exits 0 if everything passes, 1 if anything FAILs (WARNs don't affect exit
code -- they're worth a look but aren't necessarily broken). Safe to run
anytime; entirely read-only, writes nothing.

WHAT THIS DOES NOT COVER: security/RLS auditing. That needs direct
Postgres catalog access (pg_policies, etc.) which isn't exposed through
the standard Supabase client this script uses -- run Supabase's own
Advisor (dashboard, or via the Supabase MCP tool's get_advisors) for that
instead. This script is about data health, not access control.
"""

import sys
from datetime import date, datetime, timezone

from db import get_client

# (table, date_column, max_days_stale, notes)
FRESHNESS_EXPECTATIONS = [
    ("qb_da_transaction_lines", "txn_date", 3, "daily sync"),
    ("social_metrics", "period_date", 3, "daily sync, filtered to source=api"),
    ("social_posts", "posted_at", 4, "12-hourly sync, but only new posts move this"),
    ("podcast_metrics", "period_date", 14, "manual browser pull, no fixed schedule"),
    ("da_cash_current_balance", "as_of", 3, "daily sync"),
    ("qb_da_invoices_daily_snapshot", "snapshot_date", 3, "daily sync, part of run_all.py"),
]

results = []  # (status, message) -- status is "PASS", "WARN", or "FAIL"


def check(status: str, message: str):
    results.append((status, message))
    print(f"[{status}] {message}")


def _parse_to_date(raw) -> date:
    """Handles both plain date strings ('2026-08-27') and full timestamps
    ('2026-08-27T13:29:26.856735+00:00') -- tries the richer format first,
    falls back to plain date. Deliberately simple/testable rather than a
    heuristic trying to guess the format from string shape."""
    raw = str(raw)
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return date.fromisoformat(raw)


def check_freshness(client):
    print("\n=== Freshness ===")
    today = date.today()
    for table, date_col, max_days, notes in FRESHNESS_EXPECTATIONS:
        try:
            resp = client.table(table).select(date_col).order(date_col, desc=True).limit(1).execute()
            if not resp.data:
                check("WARN", f"{table}: no rows at all -- may genuinely be empty, or sync never ran")
                continue
            latest = _parse_to_date(resp.data[0][date_col])
            days_stale = (today - latest).days
            if days_stale > max_days:
                check("FAIL", f"{table}: latest data is {latest} ({days_stale} days old, expected within {max_days} -- {notes})")
            else:
                check("PASS", f"{table}: fresh as of {latest} ({days_stale} day(s) old)")
        except Exception as e:
            check("WARN", f"{table}: freshness check itself failed to run ({e})")


def check_revenue_forecast_consistency(client):
    print("\n=== Revenue Forecast: sub-line-items sum to Total ===")
    try:
        resp = client.table("da_revenue_forecast").select("month,business_unit,estimate").execute()
        by_month = {}
        for row in resp.data:
            by_month.setdefault(row["month"], {})[row["business_unit"]] = row["estimate"] or 0

        mismatches = 0
        for month, units in sorted(by_month.items()):
            total = units.get("Total")
            if total is None:
                continue
            parts_sum = sum(v for k, v in units.items() if k != "Total")
            if abs((parts_sum or 0) - total) > 0.02:
                check("FAIL", f"da_revenue_forecast {month}: parts sum to {parts_sum}, Total row says {total}")
                mismatches += 1
        if mismatches == 0:
            check("PASS", f"da_revenue_forecast: all {len(by_month)} months' sub-line-items match their Total row exactly")
    except Exception as e:
        check("WARN", f"revenue forecast consistency check failed to run ({e})")


def check_cash_flow_chain_integrity(client):
    print("\n=== Cash Flow: month-over-month chain integrity ===")
    try:
        resp = client.table("da_cash_flow_monthly_actuals").select("month,beginning_balance,ending_balance").order("month").execute()
        rows = resp.data
        gaps = 0
        for i in range(len(rows) - 1):
            this_end = rows[i]["ending_balance"]
            next_begin = rows[i + 1]["beginning_balance"]
            if this_end is not None and next_begin is not None and abs(this_end - next_begin) > 0.02:
                check("FAIL", f"Cash flow chain break: {rows[i]['month']} ending={this_end} != {rows[i+1]['month']} beginning={next_begin}")
                gaps += 1
        if gaps == 0:
            check("PASS", f"da_cash_flow_monthly_actuals: all {len(rows)-1} consecutive month-pairs chain correctly")
    except Exception as e:
        check("WARN", f"cash flow chain check failed to run ({e})")


def check_social_account_hygiene(client):
    print("\n=== Social Accounts: no orphans or empty IDs ===")
    try:
        resp = client.table("social_accounts").select("account_id,platform,handle").execute()
        empty_ids = [r for r in resp.data if not r["account_id"]]
        if empty_ids:
            check("FAIL", f"{len(empty_ids)} social_accounts row(s) with an empty account_id -- orphaned, should be deleted")
        else:
            check("PASS", f"social_accounts: all {len(resp.data)} rows have a real account_id")

        by_platform = {}
        for r in resp.data:
            by_platform.setdefault(r["platform"], []).append(r["handle"])
        for platform, handles in by_platform.items():
            if len(set(handles)) < len(handles):
                check("WARN", f"{platform} has duplicate handles across different account_id rows: {handles}")
    except Exception as e:
        check("WARN", f"social account hygiene check failed to run ({e})")


def check_ar_sanity(client):
    print("\n=== Accounts Receivable: sanity bounds ===")
    try:
        resp = client.table("da_ar_current_position").select("*").execute()
        if not resp.data:
            check("WARN", "da_ar_current_position returned no rows -- has sync_ar_aging() ever run?")
            return
        row = resp.data[0]
        total = row.get("total_outstanding") or 0
        overdue = row.get("total_overdue") or 0
        if total < 0:
            check("FAIL", f"total_outstanding is negative ({total}) -- shouldn't be possible for open invoice balances")
        elif overdue > total:
            check("FAIL", f"total_overdue ({overdue}) exceeds total_outstanding ({total}) -- shouldn't be possible")
        else:
            pct_overdue = round(100 * overdue / total, 1) if total else 0
            check("PASS", f"AR position sane: ${total:,.2f} total, ${overdue:,.2f} overdue ({pct_overdue}%)")
            if pct_overdue > 40:
                check("WARN", f"{pct_overdue}% of AR is overdue -- worth a real collections review, not just a data check")
    except Exception as e:
        check("WARN", f"AR sanity check failed to run ({e})")


def check_needs_review_materiality(client):
    print("\n=== QuickBooks: needs_review materiality ===")
    try:
        resp = client.table("qb_da_transaction_lines").select("amount").eq("source", "needs_review").execute()
        total = sum(abs(r["amount"] or 0) for r in resp.data)
        count = len(resp.data)
        if total > 100000:
            check("WARN", f"${total:,.2f} across {count} needs_review transactions -- material enough to be worth classifying, not just flagging")
        else:
            check("PASS", f"needs_review total is ${total:,.2f} across {count} transactions -- not yet material")
    except Exception as e:
        check("WARN", f"needs_review materiality check failed to run ({e})")


def check_follower_dedup_view(client):
    print("\n=== Social Followers: dedup view returns exactly one row per platform ===")
    try:
        resp = client.table("social_followers_deduped").select("platform,period_date").execute()
        latest_date = max((r["period_date"] for r in resp.data), default=None)
        if latest_date is None:
            check("WARN", "social_followers_deduped returned no rows at all")
            return
        latest_rows = [r for r in resp.data if r["period_date"] == latest_date]
        platforms = [r["platform"] for r in latest_rows]
        if len(platforms) != len(set(platforms)):
            check("FAIL", f"social_followers_deduped has duplicate platforms on {latest_date}: {platforms} -- dedup logic may have regressed")
        else:
            check("PASS", f"social_followers_deduped: exactly one row per platform ({sorted(platforms)}) on {latest_date}")
    except Exception as e:
        check("WARN", f"follower dedup check failed to run ({e})")


def main() -> int:
    client = get_client()

    check_freshness(client)
    check_revenue_forecast_consistency(client)
    check_cash_flow_chain_integrity(client)
    check_social_account_hygiene(client)
    check_ar_sanity(client)
    check_needs_review_materiality(client)
    check_follower_dedup_view(client)

    print("\n" + "=" * 60)
    passed = sum(1 for s, _ in results if s == "PASS")
    warned = sum(1 for s, _ in results if s == "WARN")
    failed = sum(1 for s, _ in results if s == "FAIL")
    print(f"SUMMARY: {passed} passed, {warned} warnings, {failed} failed")

    if failed:
        print("\nFAILURES (need real attention):")
        for status, msg in results:
            if status == "FAIL":
                print(f"  - {msg}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
