"""
writer.py — Idempotent upsert into Supabase.

Reused pattern from the EGE build. Every connector calls upsert_rows() with
a table name, a list of row dicts, and the unique constraint columns for
that table. Re-running a connector never creates duplicate rows — it's safe
to run on a schedule (see run_all.py) or re-run manually after a failure.
"""

from db import get_client

# Maps each table to its natural-key / unique-constraint columns,
# matching the `unique (...)` constraints defined in the schema.
CONFLICT_KEYS = {
    "qb_da_transaction_lines": "qb_txn_id,qb_line_id",
    "qb_oauth_credentials": "realm_id",
    "airtable_partnerships": "deal_id",
    "da_cash_current_balance": None,  # append-only log, no upsert
    "da_cash_flow_forecast": "month,line_item",
    "da_cash_flow_monthly_actuals": "month,line_item",
    "da_revenue_forecast": "month,business_unit",
    "affiliate_revenue": "month,platform",
    "social_accounts": "account_id",
    "social_metrics": "account_id,metric,period_date,source",
    "social_audience_demographics": "account_id,dimension,dimension_value,period_date",
    "social_posts": "account_id,post_id",
    "social_post_metrics": "post_id,metric,fetched_at",
    "podcast_metrics": "show_id,platform,metric,period_date",
    "da_entity_summary": "month,metric",
}


def upsert_rows(table: str, rows: list[dict]) -> int:
    """
    Upserts rows into `table`. Returns the number of rows written.
    Raises if `table` isn't in CONFLICT_KEYS — every new table needs its
    conflict key registered here before it can be written to.
    """
    if not rows:
        return 0

    if table not in CONFLICT_KEYS:
        raise ValueError(
            f"No conflict key registered for '{table}'. "
            "Add it to CONFLICT_KEYS in writer.py before writing to this table."
        )

    client = get_client()
    conflict_key = CONFLICT_KEYS[table]

    if conflict_key is None:
        # Append-only tables (e.g. cash balance snapshots) just insert.
        client.table(table).insert(rows).execute()
    else:
        client.table(table).upsert(rows, on_conflict=conflict_key).execute()

    return len(rows)
