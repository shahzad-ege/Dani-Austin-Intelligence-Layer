"""
qb_connector.py — QuickBooks Online connector for Dani Austin LLC.

REWRITTEN from a Reports API approach to the Accounting API entity-query
approach, adapted from a reference connector used for a different
QuickBooks company (Domas Holdings). This rewrite fixed two proven, real
bugs in the previous version, not stylistic preferences:

1. IDENTIFIER BUG (was causing 82.7% data loss in production): the old
   version used QuickBooks' `doc_num` (a user-facing, optional "document
   number" field) as the unique transaction identifier. Most transaction
   types -- deposits, transfers, many expense categorizations -- simply
   don't have one. A real production run showed 647 of 782 real
   transactions silently excluded because of this. This version uses each
   entity's real `Id` field, which QuickBooks guarantees is always present
   -- it's the actual database primary key, not an optional display field.

2. REFRESH TOKEN ROTATION BUG (never triggered yet, but would have caused
   silent failure on the very next scheduled run): QuickBooks rotates the
   refresh token every time it's used. The old version read
   QB_REFRESH_TOKEN from .env and never saved the new one back anywhere --
   meaning the first successful run would invalidate the token still
   sitting in .env, and the next scheduled run would fail. This version
   persists the rotated token to qb_oauth_credentials immediately after
   refreshing, before doing anything else that could fail.

WHAT'S SYNCED (matches standard accrual-basis practice, same convention as
the reference connector): Purchase + Bill -> expense. Invoice + SalesReceipt
+ Deposit -> income. BillPayment is deliberately excluded -- Bill already
captures the expense on an accrual basis; including BillPayment too would
double-count the same expense once as accrued and once as paid.

CAVEAT ON DEPOSIT: not every Deposit is necessarily true revenue (could be
a transfer, an owner contribution, etc.) -- this connector follows the same
income classification convention as the reference connector for
consistency, but this is a real simplification worth knowing about, not a
guarantee that every Deposit is booked revenue in an accounting sense.

CATEGORY IS NOW DETERMINISTIC, NOT GUESSED: the old version's
classify_category() guessed income/expense from account-name keywords --
a known placeholder, flagged as unreliable from the start. This version
derives category directly from which QuickBooks entity type a transaction
is (Purchase/Bill are unambiguously expenses; Invoice/SalesReceipt/Deposit
are unambiguously income) -- no guessing involved at all.

SOURCE/BUSINESS-UNIT (Class) EXTRACTION IS UNCONFIRMED: this connector
attempts to read a ClassRef from each line, the same way the account/item
reference is read. Whether Dani Austin's QuickBooks setup actually uses
Class tracking, and exactly where ClassRef appears in the JSON for each
entity type, has NOT been confirmed against a real account yet. If `source`
comes back consistently None once this runs for real, that's the first
thing to check -- see extract_class_name() below.

Requires (via env vars, sourced from 1Password at run time):
    QB_CLIENT_ID
    QB_CLIENT_SECRET
    QB_REALM_ID
    QB_REFRESH_TOKEN      -- used only to bootstrap the very first run;
                             every run after that reads/writes the current
                             token from/to qb_oauth_credentials instead
    QB_ENVIRONMENT        -- sandbox | production (default: production)
"""

import os
from datetime import date, timedelta

import requests

from models import QBTransactionLine
from writer import upsert_rows
from db import get_client

QB_CLIENT_ID = os.environ["QB_CLIENT_ID"]
QB_CLIENT_SECRET = os.environ["QB_CLIENT_SECRET"]
QB_REALM_ID = os.environ["QB_REALM_ID"]
QB_ENVIRONMENT = (os.environ.get("QB_ENVIRONMENT") or "production").strip().lower()

QB_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
QB_API_BASE = (
    "https://quickbooks.api.intuit.com"
    if QB_ENVIRONMENT == "production"
    else "https://sandbox-quickbooks.api.intuit.com"
)

PAGE_SIZE = 500  # QBO's max is 1000; 500 leaves a safer response-size margin


def load_stored_refresh_token() -> str:
    """
    Reads the current refresh token from qb_oauth_credentials. Falls back
    to QB_REFRESH_TOKEN from .env only if no row exists yet (i.e. this is
    the very first run since the OAuth Playground consent step) -- every
    run after that uses the rotated token stored here, not the original
    .env value, which QuickBooks will have already invalidated.
    """
    client = get_client()
    result = client.table("qb_oauth_credentials").select("*").eq("realm_id", QB_REALM_ID).execute()
    if result.data:
        return result.data[0]["refresh_token"]

    bootstrap_token = os.environ.get("QB_REFRESH_TOKEN")
    if not bootstrap_token:
        raise RuntimeError(
            "No stored refresh token in qb_oauth_credentials, and QB_REFRESH_TOKEN "
            "is not set in the environment to bootstrap from. Run the OAuth "
            "Playground consent flow first."
        )
    return bootstrap_token


def save_refreshed_token(refresh_token: str) -> None:
    """
    Saves the newly rotated refresh token IMMEDIATELY after refreshing,
    before doing anything else that could fail -- so a later error in this
    run can never lose the new token and strand the connection.
    """
    upsert_rows(
        "qb_oauth_credentials",
        [{"realm_id": QB_REALM_ID, "refresh_token": refresh_token}],
    )


def refresh_access_token() -> str:
    """Exchanges the current refresh token for a short-lived access token,
    and immediately persists the newly rotated refresh token QuickBooks
    always issues back."""
    current_refresh_token = load_stored_refresh_token()

    resp = requests.post(
        QB_TOKEN_URL,
        auth=(QB_CLIENT_ID, QB_CLIENT_SECRET),
        data={"grant_type": "refresh_token", "refresh_token": current_refresh_token},
        headers={"Accept": "application/json"},
    )
    resp.raise_for_status()
    token_data = resp.json()

    # Save the new refresh token right away -- QuickBooks has already
    # invalidated the old one by this point.
    save_refreshed_token(token_data["refresh_token"])

    return token_data["access_token"]


def qb_query(access_token: str, query: str) -> list[dict]:
    """Runs a QBO SQL-like query against the Accounting API, paginating
    until all results are fetched."""
    all_rows = []
    start_position = 1
    entity_name = query.split("FROM")[1].strip().split(" ")[0]

    while True:
        paged_query = f"{query} STARTPOSITION {start_position} MAXRESULTS {PAGE_SIZE}"
        resp = requests.get(
            f"{QB_API_BASE}/v3/company/{QB_REALM_ID}/query",
            params={"query": paged_query},
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        rows = data.get("QueryResponse", {}).get(entity_name, [])
        all_rows.extend(rows)

        if len(rows) < PAGE_SIZE:
            break
        start_position += PAGE_SIZE

    return all_rows


_class_diagnostic_printed = 0


_account_business_unit_cache: dict[str, str] | None = None


def load_account_business_unit_map() -> dict[str, str]:
    """
    Loaded once per run, not per row. CONFIRMED via direct diagnostic that
    Dani Austin's QuickBooks doesn't use Class tracking at all (ClassRef is
    genuinely absent at detail/line/txn level on real transactions, checked
    directly) -- so business-unit tagging comes from a maintained
    account-name lookup instead, same pattern as the Domas reference
    connector's qb_account_subcategory_map. Unmapped accounts return
    'needs_review' via .get() at the call site, never silently guessed.
    """
    global _account_business_unit_cache
    if _account_business_unit_cache is None:
        client = get_client()
        result = client.table("qb_account_business_unit_map").select("account_name,business_unit").execute()
        _account_business_unit_cache = {row["account_name"]: row["business_unit"] for row in result.data}
    return _account_business_unit_cache


def extract_class_name(txn: dict, line: dict, detail: dict) -> str | None:
    """
    Attempts to extract a Class reference for the source/business_unit tag.

    Checks three levels, in order: line-detail, line, then transaction
    header. CONFIRMED (not just suspected) that this always returns None
    for Dani Austin's QuickBooks: a direct diagnostic on real transactions
    showed ClassRef genuinely absent from all three levels' actual keys --
    this business doesn't use Class tracking. Kept in place (rather than
    removed) so it costs nothing and works automatically if Class tracking
    is ever turned on later -- see extract_business_unit() below for the
    account-name-based fallback that's the real source of `source` today.
    """
    global _class_diagnostic_printed

    class_ref = detail.get("ClassRef") or line.get("ClassRef") or txn.get("ClassRef")
    if class_ref:
        return class_ref.get("name")

    if _class_diagnostic_printed < 3:
        print(f"[qb] DIAGNOSTIC (class extraction, sample {_class_diagnostic_printed + 1}/3): "
              f"no ClassRef found at detail/line/txn level.")
        print(f"[qb]   txn keys: {list(txn.keys())}")
        print(f"[qb]   line keys: {list(line.keys())}")
        print(f"[qb]   detail keys: {list(detail.keys())}")
        _class_diagnostic_printed += 1

    return None


def extract_business_unit(txn: dict, line: dict, detail: dict, account_name: str | None) -> str | None:
    """
    The actual source of `source`/business_unit today: Class first (works
    automatically if ever enabled), falling back to the account-name
    lookup table. Unmapped accounts return 'needs_review' explicitly --
    same philosophy as the Domas reference connector -- rather than being
    silently left as None, which would be indistinguishable from "checked
    and genuinely has no business unit."
    """
    class_result = extract_class_name(txn, line, detail)
    if class_result:
        return class_result

    if not account_name:
        return "needs_review"

    mapping = load_account_business_unit_map()
    return mapping.get(account_name, "needs_review")


def extract_expense_lines(txn: dict, txn_type: str) -> list[QBTransactionLine]:
    """Extracts one row per real line item from a Purchase or Bill."""
    records = []
    txn_id = txn.get("Id")
    txn_date_str = txn.get("TxnDate")
    if not txn_id or not txn_date_str:
        return records

    for line in txn.get("Line", []):
        detail = line.get("AccountBasedExpenseLineDetail") or line.get("ItemBasedExpenseLineDetail")
        if not detail:
            continue  # subtotal/discount lines with no account/item detail -- not a real posting

        account_name = (detail.get("AccountRef") or detail.get("ItemRef") or {}).get("name")
        amount = line.get("Amount")
        if account_name is None or amount is None:
            continue

        records.append(
            QBTransactionLine(
                qb_txn_id=str(txn_id),
                qb_line_id=str(line.get("Id")) if line.get("Id") is not None else None,
                qb_txn_type=txn_type,
                txn_date=date.fromisoformat(txn_date_str),
                category="expense",
                account=account_name,
                source=extract_business_unit(txn, line, detail, account_name),
                amount=-abs(float(amount)),  # expenses stored as negative
                memo=line.get("Description"),
            )
        )
    return records


def extract_income_lines(txn: dict, txn_type: str) -> list[QBTransactionLine]:
    """Extracts one row per real line item from an Invoice, SalesReceipt,
    or Deposit. See the module docstring's caveat on Deposit specifically."""
    records = []
    txn_id = txn.get("Id")
    txn_date_str = txn.get("TxnDate")
    if not txn_id or not txn_date_str:
        return records

    for line in txn.get("Line", []):
        detail = line.get("SalesItemLineDetail") or line.get("DepositLineDetail")
        if not detail:
            continue

        account_name = (detail.get("ItemRef") or detail.get("AccountRef") or {}).get("name")
        amount = line.get("Amount")
        if account_name is None or amount is None:
            continue

        records.append(
            QBTransactionLine(
                qb_txn_id=str(txn_id),
                qb_line_id=str(line.get("Id")) if line.get("Id") is not None else None,
                qb_txn_type=txn_type,
                txn_date=date.fromisoformat(txn_date_str),
                category="income",
                account=account_name,
                source=extract_business_unit(txn, line, detail, account_name),
                amount=abs(float(amount)),  # income stored as positive
                memo=line.get("Description"),
            )
        )
    return records


ENTITY_CONFIG = [
    ("Purchase", extract_expense_lines),
    ("Bill", extract_expense_lines),
    ("Invoice", extract_income_lines),
    ("SalesReceipt", extract_income_lines),
    ("Deposit", extract_income_lines),
]


def extract_ar_invoice(txn: dict) -> dict | None:
    """
    Extracts invoice-HEADER-level AR data: Balance (remaining unpaid amount)
    and DueDate. Deliberately separate from extract_income_lines() -- those
    fields live on the invoice itself, not on individual line items, so
    this needs its own extraction path rather than reusing the line-level
    one. Balance and DueDate are core, long-standing QuickBooks Invoice
    fields (unlike some of the more obscure fields this project has had to
    discover through trial and error elsewhere) -- not guessed.
    """
    invoice_id = txn.get("Id")
    if invoice_id is None:
        return None
    return {
        "qb_invoice_id": str(invoice_id),
        "customer_name": (txn.get("CustomerRef") or {}).get("name"),
        "txn_date": txn.get("TxnDate"),
        "due_date": txn.get("DueDate"),
        "total_amount": txn.get("TotalAmt"),
        "balance": txn.get("Balance"),
    }


def sync_ar_aging() -> int:
    """
    Pulls ALL Invoice entities -- deliberately NOT filtered by a rolling
    date window the way the regular transaction-line sync is. AR aging
    cares about which invoices are STILL OPEN today regardless of how old
    they are; a 2-year-old unpaid invoice is exactly as relevant to a
    current AR position as one from last week. Separate entry point from
    run(), since it's a different query shape and a different table.

    Writes to TWO tables, not one:
      - qb_da_invoices: current state (upserted, overwrites balance each
        run) -- the fast, simple "what's owed right now" table.
      - qb_da_invoices_daily_snapshot: append-only, one row per invoice per
        day. Needed because the upsert table alone can't answer "was this
        settled, and when" -- once an invoice is paid, its prior open
        balance would just be overwritten and lost with no history.
    """
    access_token = refresh_access_token()
    invoices = qb_query(access_token, "SELECT * FROM Invoice")

    records = []
    for inv in invoices:
        parsed = extract_ar_invoice(inv)
        if parsed and parsed["qb_invoice_id"]:
            records.append(parsed)

    written = upsert_rows("qb_da_invoices", records)

    snapshot_rows = [
        {
            "qb_invoice_id": r["qb_invoice_id"],
            "customer_name": r["customer_name"],
            "due_date": r["due_date"],
            "balance": r.get("balance") or 0,
        }
        for r in records
    ]
    upsert_rows("qb_da_invoices_daily_snapshot", snapshot_rows)

    open_count = sum(1 for r in records if (r.get("balance") or 0) > 0)
    print(f"[qb] AR sync: {len(records)} invoice(s) total, {open_count} currently open (unpaid)")
    return written


def run(since: date | None = None) -> int:
    since = since or (date.today() - timedelta(days=90))
    access_token = refresh_access_token()

    all_records: list[QBTransactionLine] = []
    for entity, extractor in ENTITY_CONFIG:
        query = f"SELECT * FROM {entity} WHERE TxnDate >= '{since.isoformat()}'"
        txns = qb_query(access_token, query)
        for txn in txns:
            all_records.extend(extractor(txn, entity))

    return upsert_rows("qb_da_transaction_lines", [r.to_row() for r in all_records])


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sync QuickBooks data to Supabase")
    parser.add_argument("--since", type=str, default=None,
                        help="Pull transactions from this date onward (YYYY-MM-DD). "
                             "Default: last 90 days.")
    parser.add_argument("--full-history", action="store_true",
                        help="Pull EVERYTHING the company file has, ignoring --since. "
                             "QuickBooks itself has no retention limit -- the 90-day "
                             "default is our own choice, not a platform constraint. "
                             "Expect this to surface accounts not yet in "
                             "qb_account_business_unit_map; new needs_review rows are "
                             "expected, not a bug.")
    parser.add_argument("--ar-aging", action="store_true",
                        help="Sync Accounts Receivable aging instead of transaction "
                             "lines -- pulls all Invoice records (open and closed) with "
                             "their Balance and DueDate, for the AR position/aging "
                             "views. A separate mode from the regular sync since it's a "
                             "different query and a different table.")
    args = parser.parse_args()

    if args.ar_aging:
        count = sync_ar_aging()
        print(f"QuickBooks AR aging sync: upserted {count} invoice(s).")
    else:
        if args.full_history:
            since_date = date(2000, 1, 1)  # effectively "everything"
            print("[qb] Full-history backfill requested -- pulling all available transactions.")
        elif args.since:
            since_date = date.fromisoformat(args.since)
        else:
            since_date = None  # falls back to run()'s own 90-day default

        count = run(since=since_date)
        print(f"QuickBooks connector: upserted {count} transaction lines.")
