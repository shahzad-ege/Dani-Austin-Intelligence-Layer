"""
test_paypal_connector.py — Tests PayPal connector parsing against fake
OAuth token + balance responses. No real network/database calls.
"""

import os
import sys
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("PAYPAL_CLIENT_ID_DANI", "test")
os.environ.setdefault("PAYPAL_CLIENT_SECRET_DANI", "test")
os.environ.setdefault("PAYPAL_CLIENT_ID_KATELYN", "test")
os.environ.setdefault("PAYPAL_CLIENT_SECRET_KATELYN", "test")

import paypal_connector  # noqa: E402


FAKE_TOKEN_RESPONSE = {"access_token": "fake_token_123"}
FAKE_BALANCE_RESPONSE = {
    "balances": [
        {
            "currency": "USD",
            "available_balance": {"currency_code": "USD", "value": "4321.99"},
            "total_balance": {"currency_code": "USD", "value": "4321.99"},
            "withheld_balance": {"currency_code": "USD", "value": "0.00"},
        }
    ]
}


def test_get_access_token():
    with patch("paypal_connector.requests.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200, json=lambda: FAKE_TOKEN_RESPONSE, raise_for_status=lambda: None
        )
        token = paypal_connector.get_access_token("id", "secret")
    assert token == "fake_token_123"


def test_build_records_keeps_accounts_separate():
    as_of = datetime.now(timezone.utc)
    dani_records = paypal_connector.build_records(FAKE_BALANCE_RESPONSE, "Dani Austin", as_of)
    katelyn_records = paypal_connector.build_records(FAKE_BALANCE_RESPONSE, "Katelyn", as_of)

    # Two separate calls, two separately labeled records -- NOT combined
    # into one figure, unlike the reference connector's behavior.
    assert dani_records[0].account_name == "PayPal (Dani Austin) — USD"
    assert katelyn_records[0].account_name == "PayPal (Katelyn) — USD"
    assert dani_records[0].current_balance == 4321.99


def test_run_writes_both_accounts_as_separate_rows():
    with patch("paypal_connector.requests.post") as mock_post, \
         patch("paypal_connector.requests.get") as mock_get, \
         patch("paypal_connector.upsert_rows") as mock_upsert:

        mock_post.return_value = MagicMock(
            status_code=200, json=lambda: FAKE_TOKEN_RESPONSE, raise_for_status=lambda: None
        )
        mock_get.return_value = MagicMock(
            status_code=200, json=lambda: FAKE_BALANCE_RESPONSE, raise_for_status=lambda: None
        )
        mock_upsert.return_value = 2

        count = paypal_connector.run()

        assert count == 2
        # First call writes the individual balances
        first_call_table, first_call_rows = mock_upsert.call_args_list[0][0]
        assert first_call_table == "da_cash_current_balance"
        account_names = {r["account_name"] for r in first_call_rows}
        assert account_names == {"PayPal (Dani Austin) — USD", "PayPal (Katelyn) — USD"}

        # Second call automatically writes the combined total -- no manual
        # query or separate step required, this happens every run.
        second_call_table, second_call_rows = mock_upsert.call_args_list[1][0]
        assert second_call_table == "da_entity_summary"
        assert second_call_rows[0]["metric"] == "paypal_total_cash"
        assert second_call_rows[0]["value"] == 8643.98  # 4321.99 + 4321.99, both fake accounts


def test_run_skips_account_with_missing_credentials():
    with patch.dict(os.environ, {"PAYPAL_CLIENT_ID_KATELYN": ""}, clear=False), \
         patch("paypal_connector.requests.post") as mock_post, \
         patch("paypal_connector.requests.get") as mock_get, \
         patch("paypal_connector.upsert_rows") as mock_upsert:

        mock_post.return_value = MagicMock(
            status_code=200, json=lambda: FAKE_TOKEN_RESPONSE, raise_for_status=lambda: None
        )
        mock_get.return_value = MagicMock(
            status_code=200, json=lambda: FAKE_BALANCE_RESPONSE, raise_for_status=lambda: None
        )
        mock_upsert.return_value = 1

        count = paypal_connector.run()

        assert count == 1  # only Dani Austin's account, Katelyn's skipped gracefully
        first_call_table, first_call_rows = mock_upsert.call_args_list[0][0]
        assert first_call_table == "da_cash_current_balance"
        assert len(first_call_rows) == 1
        assert first_call_rows[0]["account_name"] == "PayPal (Dani Austin) — USD"


if __name__ == "__main__":
    test_get_access_token()
    test_build_records_keeps_accounts_separate()
    test_run_writes_both_accounts_as_separate_rows()
    test_run_skips_account_with_missing_credentials()
    print("All PayPal connector tests passed.")
