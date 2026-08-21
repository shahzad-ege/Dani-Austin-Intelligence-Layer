"""
test_brex_connector.py — Tests Brex connector parsing against a fake
/v2/accounts/cash response. No real network/database calls.
"""

import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("BREX_API_TOKEN", "test_token")

import brex_connector  # noqa: E402


FAKE_ACCOUNTS_RESPONSE = {
    "items": [
        {
            "id": "acc_001",
            "name": "Primary Cash Account",
            "status": "ACTIVE",
            "current_balance": {"amount": 1523456, "currency": "USD"},  # $15,234.56
        },
        {
            "id": "acc_002",
            "description": "Money Market",
            "status": "ACTIVE",
            "current_balance": {"amount": 0, "currency": "USD"},
        },
    ]
}


def test_fetch_cash_accounts_parses_items():
    with patch("brex_connector.requests.get") as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200, json=lambda: FAKE_ACCOUNTS_RESPONSE, raise_for_status=lambda: None
        )
        accounts = brex_connector.fetch_cash_accounts("fake_token")

    assert len(accounts) == 2
    assert accounts[0]["id"] == "acc_001"


def test_build_records_converts_cents_to_dollars_and_keeps_zero_balance():
    from datetime import datetime, timezone

    as_of = datetime.now(timezone.utc)
    records = brex_connector.build_records(FAKE_ACCOUNTS_RESPONSE["items"], "Dani Austin", as_of)

    assert len(records) == 2  # zero-balance account NOT dropped, unlike the reference pattern
    assert records[0].current_balance == 15234.56
    assert records[0].account_name == "Brex (Dani Austin) — Primary Cash Account"
    assert records[1].current_balance == 0.0
    assert records[1].account_name == "Brex (Dani Austin) — Money Market"


def test_run_skips_gracefully_when_token_missing():
    with patch.dict(os.environ, {"BREX_API_TOKEN": ""}, clear=False), \
         patch("brex_connector.upsert_rows") as mock_upsert:
        mock_upsert.return_value = 0
        count = brex_connector.run()
        assert count == 0  # no crash, just skips


def test_run_writes_records_when_token_present():
    with patch("brex_connector.requests.get") as mock_get, \
         patch("brex_connector.upsert_rows") as mock_upsert:

        mock_get.return_value = MagicMock(
            status_code=200, json=lambda: FAKE_ACCOUNTS_RESPONSE, raise_for_status=lambda: None
        )
        mock_upsert.return_value = 2

        count = brex_connector.run()

        assert count == 2
        written_rows = mock_upsert.call_args[0][1]
        assert written_rows[0]["current_balance"] == 15234.56


if __name__ == "__main__":
    test_fetch_cash_accounts_parses_items()
    test_build_records_converts_cents_to_dollars_and_keeps_zero_balance()
    test_run_skips_gracefully_when_token_missing()
    test_run_writes_records_when_token_present()
    print("All Brex connector tests passed.")
