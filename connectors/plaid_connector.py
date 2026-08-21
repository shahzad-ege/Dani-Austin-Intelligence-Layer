"""
plaid_connector.py — Chase Business balance for Dani Austin LLC, via Plaid.

IMPORTANT — SHARED TOKEN, FILTERED DOWN:
The Plaid access token in use here is shared across the whole EGE family
office and returns balances for FIVE accounts, not one:
    - Chase Business — Dani Austin Checking   <- the only one we want
    - Chase Business — EGE Checking
    - Chase Business — Domas Checking
    - Chase Business — Slingshot Checking
    - Chase Business — COMM CHKG W/INT

Per the spoke/hub isolation principle (this database must never contain
EGE or other portfolio entities' data), this connector explicitly filters
to ONLY the Dani Austin account_id below. The other four accounts are
fetched as part of the same API response (Plaid returns all accounts tied
to the token in one call) but are discarded in code before anything is
written -- they are never inserted into da_cash_current_balance, even
transiently. If Plaid ever adds a second Dani Austin account under this
same token, it would NOT be picked up automatically -- the filter is an
explicit allowlist, not a name-based guess, on purpose.

Requires (via env vars, sourced from 1Password at run time):
    PLAID_CLIENT_ID
    PLAID_SECRET          -- must be the Production/Trial secret, NOT the
                             Sandbox secret. Plaid issues a different secret
                             per environment; using the wrong one fails auth.
    PLAID_ACCESS_TOKEN
    PLAID_ENV             -- "sandbox" or "production". Defaults to
                             "production" if unset, since a real shared
                             EGE token pulling real balances is almost
                             certainly production -- but this is now an
                             explicit, checkable setting, not a silent
                             assumption baked into the code.
    PLAID_DA_ACCOUNT_ID   -- defaults to the known Dani Austin account_id
                             below if not set; overridable in case Plaid
                             ever reissues it.

Docs: https://plaid.com/docs/api/products/balance/
"""

import os
import requests
from datetime import datetime, timezone

from models import CashBalance
from writer import upsert_rows

PLAID_BASE_URLS = {
    "sandbox": "https://sandbox.plaid.com",
    "production": "https://production.plaid.com",
}

# The ONLY account this connector is allowed to write. Confirmed directly
# from a real balance pull against the shared EGE Plaid token.
DA_ACCOUNT_ID_DEFAULT = "Kna3BME5DDiwKg7OB459I0wm36E3RPFEAp9ng"


def fetch_balances(client_id: str, secret: str, access_token: str, base_url: str) -> list:
    """POST /accounts/balance/get — returns balances for every account
    tied to this access token (all five, for this shared EGE token)."""
    resp = requests.post(
        f"{base_url}/accounts/balance/get",
        json={
            "client_id": client_id,
            "secret": secret,
            "access_token": access_token,
        },
    )
    resp.raise_for_status()
    return resp.json().get("accounts", [])


def build_record(accounts: list, target_account_id: str, as_of: datetime) -> CashBalance | None:
    """
    Filters the full account list down to exactly one -- the Dani Austin
    account -- and discards everything else. Returns None (and logs) if
    the target account isn't found in the response at all, rather than
    silently writing nothing with no explanation.
    """
    for account in accounts:
        if account.get("account_id") != target_account_id:
            continue

        name = account.get("official_name") or account.get("name") or "Chase Business"
        balance = account.get("balances", {}).get("current")
        if balance is None:
            print(f"[plaid] Found Dani Austin account but 'current' balance is null: {account}")
            return None

        return CashBalance(
            account_name=f"Chase Business (Dani Austin) — {name}",
            current_balance=round(float(balance), 2),
            as_of=as_of,
        )

    print(
        f"[plaid] Target account_id {target_account_id} not found among "
        f"{len(accounts)} account(s) returned. Other entities' accounts "
        f"were present but correctly discarded, not the one we want."
    )
    return None


def run() -> int:
    client_id = os.environ.get("PLAID_CLIENT_ID")
    secret = os.environ.get("PLAID_SECRET")
    access_token = os.environ.get("PLAID_ACCESS_TOKEN")
    target_account_id = os.environ.get("PLAID_DA_ACCOUNT_ID", DA_ACCOUNT_ID_DEFAULT)

    if not client_id or not secret or not access_token:
        print("[plaid] PLAID_CLIENT_ID / PLAID_SECRET / PLAID_ACCESS_TOKEN not fully set — skipping.")
        return 0

    # `.get("PLAID_ENV", "production")` alone isn't safe here: GitHub Actions
    # always creates this env var from ${{ secrets.PLAID_ENV }} even if that
    # secret was never actually set, giving an empty string rather than a
    # missing key -- which would silently defeat the "default to production"
    # fallback and hit the validation error below with a confusing message.
    # `or "production"` correctly treats "" the same as unset.
    plaid_env = (os.environ.get("PLAID_ENV") or "production").strip().lower()
    if plaid_env not in PLAID_BASE_URLS:
        raise ValueError(
            f"PLAID_ENV={plaid_env!r} is not valid — must be one of {list(PLAID_BASE_URLS)}. "
            "Failing loudly here rather than silently guessing an environment."
        )
    base_url = PLAID_BASE_URLS[plaid_env]

    as_of = datetime.now(timezone.utc)
    accounts = fetch_balances(client_id, secret, access_token, base_url)
    record = build_record(accounts, target_account_id, as_of)

    if record is None:
        return 0

    return upsert_rows("da_cash_current_balance", [record.to_row()])


if __name__ == "__main__":
    count = run()
    print(f"Plaid connector: wrote {count} balance snapshot(s) (Dani Austin account only).")
