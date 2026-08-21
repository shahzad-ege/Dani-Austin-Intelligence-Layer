"""
paypal_connector.py — PayPal balances for Dani Austin's two accounts.

Adapted from a reference connector pattern originally written for a
different project's shared framework (core.models.BalanceRecord). Rewritten
here against our own framework (db.py/models.py/writer.py), feeding the
same da_cash_current_balance table Plaid and Brex write to.

TWO ACCOUNTS, KEPT SEPARATE IN da_cash_current_balance (deliberate deviation
from the reference): the reference connector combined both accounts into a
single figure and discarded the individual balances entirely. This version
writes both as their own rows, same as brex_connector.py.

COMBINED TOTAL, COMPUTED AUTOMATICALLY EVERY RUN: in addition to the two
individual rows, this also writes a "paypal_total_cash" row to
da_entity_summary on every run -- no separate query or manual step needed,
the combined figure is just always current the moment the connector runs.
This does NOT replace the individual account rows (still written to
da_cash_current_balance as always) -- it's an additional, automatic
convenience on top, not a substitute for the underlying detail.

Note on naming: the reference file spelled the second account holder
"Kaitlyn." Dani Austin's confirmed accounting contact is spelled "Katelyn"
(accounting@daniaustin.com) — using that spelling here on the assumption
it's the same person. Flag if this is actually a different individual.

AUTH: OAuth2 client credentials flow, one client_id/client_secret pair per
PayPal business account. A fresh access token is fetched on every run — no
refresh-token management needed, unlike QuickBooks/TikTok.

Requires (via env vars, sourced from 1Password at run time):
    PAYPAL_CLIENT_ID_DANI
    PAYPAL_CLIENT_SECRET_DANI
    PAYPAL_CLIENT_ID_KATELYN
    PAYPAL_CLIENT_SECRET_KATELYN

Docs: https://developer.paypal.com/docs/transaction-search/
"""

import os
import requests
from datetime import datetime, timezone, date

from models import CashBalance
from writer import upsert_rows

BASE_URL = "https://api-m.paypal.com"

# (client_id_env_var, client_secret_env_var, account_label)
PAYPAL_ACCOUNTS = [
    ("PAYPAL_CLIENT_ID_DANI", "PAYPAL_CLIENT_SECRET_DANI", "Dani Austin"),
    ("PAYPAL_CLIENT_ID_KATELYN", "PAYPAL_CLIENT_SECRET_KATELYN", "Katelyn"),
]


def get_access_token(client_id: str, client_secret: str) -> str:
    """Exchanges client_id + client_secret for a short-lived access token."""
    resp = requests.post(
        f"{BASE_URL}/v1/oauth2/token",
        auth=(client_id, client_secret),
        headers={"Accept": "application/json"},
        data={"grant_type": "client_credentials"},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_balance(access_token: str) -> dict:
    """GET /v1/reporting/balances — total/available/withheld balance per currency."""
    resp = requests.get(
        f"{BASE_URL}/v1/reporting/balances",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"currency_code": "USD"},
    )
    resp.raise_for_status()
    return resp.json()


def build_records(balance_data: dict, account_label: str, as_of: datetime) -> list[CashBalance]:
    """
    One record per currency returned. Uses available_balance as the
    primary figure, falling back to total_balance if available_balance
    is absent for some reason.
    """
    records = []
    for b in balance_data.get("balances", []):
        currency = b.get("currency", "USD")
        available = b.get("available_balance", {})
        total = b.get("total_balance", {})
        raw_value = float(available.get("value", 0) or total.get("value", 0))

        records.append(
            CashBalance(
                account_name=f"PayPal ({account_label}) — {currency}",
                current_balance=round(raw_value, 2),
                as_of=as_of,
            )
        )
    return records


def run() -> int:
    as_of = datetime.now(timezone.utc)
    all_records: list[CashBalance] = []

    for client_id_var, client_secret_var, account_label in PAYPAL_ACCOUNTS:
        client_id = os.environ.get(client_id_var)
        client_secret = os.environ.get(client_secret_var)

        if not client_id or not client_secret:
            print(f"[paypal] {client_id_var}/{client_secret_var} not set — skipping {account_label}.")
            continue

        access_token = get_access_token(client_id, client_secret)
        balance_data = fetch_balance(access_token)
        all_records.extend(build_records(balance_data, account_label, as_of))

    written = upsert_rows("da_cash_current_balance", [r.to_row() for r in all_records])

    # Automatic combined total -- computed from the records this run just
    # fetched (no extra API/DB round-trip needed), written every time this
    # connector runs so it's always current without a separate manual step.
    if all_records:
        total = sum(r.current_balance for r in all_records)
        current_month = date(as_of.year, as_of.month, 1)
        upsert_rows(
            "da_entity_summary",
            [{
                "month": current_month.isoformat(),
                "metric": "paypal_total_cash",
                "value": round(total, 2),
                "synced_at": as_of.isoformat(),
            }],
        )
        print(f"[paypal] Combined total (both accounts): ${total:,.2f} -> da_entity_summary")

    return written


if __name__ == "__main__":
    count = run()
    print(f"PayPal connector: wrote {count} balance snapshot(s).")
