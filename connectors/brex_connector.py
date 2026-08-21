"""
brex_connector.py — Brex cash account balances for Dani Austin LLC.

Adapted from a reference connector pattern originally written for a
different, multi-entity context (the EGE hub's shared balance-tracking
framework — core.models.BalanceRecord, multiple named account holders like
"Divi"). Rewritten here against our own framework (db.py/models.py/writer.py)
and our own schema — Brex balances land in da_cash_current_balance, the same
table Plaid/Chase writes to, since both are just cash-balance snapshots.

Structured as a list of accounts (BREX_ACCOUNTS) rather than a single
hardcoded token, so a second Brex account can be added later without a
rewrite — but as of this build, Dani Austin has exactly one known Brex
account. Do not assume a second one exists; that assumption in the
reference file was almost certainly scoped to a different entity.

AUTH: static API token (Bearer), not OAuth — see the setup guide already
walked through: Brex Dashboard -> Developer -> Settings -> Create Token,
scope accounts.cash.readonly. No approval wait, no expiry as long as it's
used at least once every 90 days (a daily sync easily satisfies this).

BASE URL: using api.brex.com (the current recommended base as of the Jan
2026 migration) rather than the legacy platform.brexapis.com the reference
file used — Brex says the legacy URL remains available "for the
foreseeable future," but there's no reason to build against the one being
phased out.

NOTE: Brex was acquired by Capital One, completed April 7, 2026 (confirmed
via Capital One's own press release, not just the reference file's
comment). The API is reported unchanged post-acquisition — worth a periodic
check of Capital One's developer comms in case that changes token validity
down the line.

Requires (via env vars, sourced from 1Password at run time):
    BREX_API_TOKEN
"""

import os
import requests
from datetime import datetime, timezone

from models import CashBalance
from writer import upsert_rows

BASE_URL = "https://api.brex.com"

# (env_var, account_label). Add a second tuple here only once a second
# Dani Austin-owned Brex account is actually confirmed to exist.
BREX_ACCOUNTS = [
    ("BREX_API_TOKEN", "Dani Austin"),
]


def fetch_cash_accounts(token: str) -> list:
    """
    GET /v2/accounts/cash — returns all cash accounts for this token,
    including balance in cents. Brex paginates under an 'items' key.
    """
    resp = requests.get(
        f"{BASE_URL}/v2/accounts/cash",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    return resp.json().get("items", [])


def build_records(accounts: list, account_label: str, as_of: datetime) -> list[CashBalance]:
    """
    Converts raw Brex accounts into CashBalance records.

    Unlike the reference pattern, this does NOT skip zero-balance or
    inactive accounts by default — for a single-entity cash-tracking table
    (not a noisy multi-entity aggregator), a zero balance or a newly
    inactive account is meaningful information, not noise. Reconsider this
    if Brex returns sub-accounts that genuinely shouldn't be tracked (e.g.
    closed legacy accounts) once real data is visible.
    """
    records = []
    for account in accounts:
        current = account.get("current_balance", {})
        raw_cents = current.get("amount", 0)
        balance_usd = raw_cents / 100.0

        name = account.get("name") or account.get("description") or "Brex Cash Account"
        records.append(
            CashBalance(
                account_name=f"Brex ({account_label}) — {name}",
                current_balance=round(balance_usd, 2),
                as_of=as_of,
            )
        )
    return records


def run() -> int:
    as_of = datetime.now(timezone.utc)
    all_records: list[CashBalance] = []

    for env_var, account_label in BREX_ACCOUNTS:
        token = os.environ.get(env_var)
        if not token:
            print(f"[brex] {env_var} not set — skipping {account_label}.")
            continue

        accounts = fetch_cash_accounts(token)
        all_records.extend(build_records(accounts, account_label, as_of))

    return upsert_rows("da_cash_current_balance", [r.to_row() for r in all_records])


if __name__ == "__main__":
    count = run()
    print(f"Brex connector: wrote {count} balance snapshot(s).")
