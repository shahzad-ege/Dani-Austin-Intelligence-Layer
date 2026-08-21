"""
test_plaid_connector.py — Tests Plaid connector parsing AND, critically,
that it correctly filters out the other four EGE-family accounts and
writes only the Dani Austin one. No real network/database calls.
"""

import os
import sys
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("PLAID_CLIENT_ID", "test")
os.environ.setdefault("PLAID_SECRET", "test")
os.environ.setdefault("PLAID_ACCESS_TOKEN", "test")

import plaid_connector  # noqa: E402


# Real shape: all FIVE accounts come back from one API call, since they
# all share the same Plaid token.
FAKE_ACCOUNTS_RESPONSE = {
    "accounts": [
        {
            "account_id": "Kna3BME5DDiwKg7OB459I0wm36E3RPFEAp9ng",
            "name": "Dani Austin Checking",
            "official_name": "Chase Business Complete Checking",
            "balances": {"current": 84213.55, "available": 84213.55},
        },
        {
            "account_id": "vw0DvkY5RRSom6aAw0DeHKom0d50gaSVzQZX6",
            "name": "EGE Checking",
            "balances": {"current": 999999.00},
        },
        {
            "account_id": "k9nMLRB0rrSKXd1neogNCLoRdXOdvKIo0q56y",
            "name": "Domas Checking",
            "balances": {"current": 555555.00},
        },
        {
            "account_id": "AbEYQn7BvvSaRv5rM9eJHB8ngZJgbQUMQ7VYE",
            "name": "Slingshot Checking",
            "balances": {"current": 333333.00},
        },
        {
            "account_id": "038R46K5ZZfRrkEdyYnAcRa6xQgxjYIAobpyn",
            "name": "COMM CHKG W/INT",
            "balances": {"current": 111111.00},
        },
    ]
}


def test_build_record_filters_to_only_dani_austin():
    as_of = datetime.now(timezone.utc)
    record = plaid_connector.build_record(
        FAKE_ACCOUNTS_RESPONSE["accounts"],
        plaid_connector.DA_ACCOUNT_ID_DEFAULT,
        as_of,
    )

    assert record is not None
    assert record.current_balance == 84213.55
    assert "Dani Austin" in record.account_name
    # Critical: none of the other four entities' names leak into the result
    assert "EGE" not in record.account_name
    assert "Domas" not in record.account_name
    assert "Slingshot" not in record.account_name


def test_build_record_returns_none_if_target_account_missing():
    as_of = datetime.now(timezone.utc)
    record = plaid_connector.build_record(
        FAKE_ACCOUNTS_RESPONSE["accounts"],
        "some_account_id_that_does_not_exist",
        as_of,
    )
    assert record is None


def test_run_writes_only_one_record_despite_five_accounts_returned():
    with patch("plaid_connector.requests.post") as mock_post, \
         patch("plaid_connector.upsert_rows") as mock_upsert:

        mock_post.return_value = MagicMock(
            status_code=200, json=lambda: FAKE_ACCOUNTS_RESPONSE, raise_for_status=lambda: None
        )
        mock_upsert.return_value = 1

        count = plaid_connector.run()

        assert count == 1
        written_rows = mock_upsert.call_args[0][1]
        assert len(written_rows) == 1  # exactly one row, not five
        assert written_rows[0]["current_balance"] == 84213.55


def test_run_skips_gracefully_when_credentials_missing():
    with patch.dict(os.environ, {"PLAID_ACCESS_TOKEN": ""}, clear=False), \
         patch("plaid_connector.upsert_rows") as mock_upsert:
        count = plaid_connector.run()
        assert count == 0
        mock_upsert.assert_not_called()


def test_run_defaults_to_production_when_plaid_env_unset():
    with patch.dict(os.environ, {}, clear=False), \
         patch("plaid_connector.requests.post") as mock_post, \
         patch("plaid_connector.upsert_rows") as mock_upsert:

        os.environ.pop("PLAID_ENV", None)  # ensure truly unset, not just empty
        mock_post.return_value = MagicMock(
            status_code=200, json=lambda: FAKE_ACCOUNTS_RESPONSE, raise_for_status=lambda: None
        )
        mock_upsert.return_value = 1

        plaid_connector.run()

        called_url = mock_post.call_args[0][0]
        assert called_url.startswith("https://production.plaid.com")


def test_run_uses_sandbox_url_when_plaid_env_is_sandbox():
    with patch.dict(os.environ, {"PLAID_ENV": "sandbox"}, clear=False), \
         patch("plaid_connector.requests.post") as mock_post, \
         patch("plaid_connector.upsert_rows") as mock_upsert:

        mock_post.return_value = MagicMock(
            status_code=200, json=lambda: FAKE_ACCOUNTS_RESPONSE, raise_for_status=lambda: None
        )
        mock_upsert.return_value = 1

        plaid_connector.run()

        called_url = mock_post.call_args[0][0]
        assert called_url.startswith("https://sandbox.plaid.com")


def test_run_treats_empty_string_plaid_env_same_as_unset():
    # Simulates GitHub Actions injecting an env var from an unset secret --
    # the key exists but is "", which must still default to production,
    # not be treated as an explicit (invalid) environment name.
    with patch.dict(os.environ, {"PLAID_ENV": ""}, clear=False), \
         patch("plaid_connector.requests.post") as mock_post, \
         patch("plaid_connector.upsert_rows") as mock_upsert:

        mock_post.return_value = MagicMock(
            status_code=200, json=lambda: FAKE_ACCOUNTS_RESPONSE, raise_for_status=lambda: None
        )
        mock_upsert.return_value = 1

        plaid_connector.run()  # must NOT raise ValueError

        called_url = mock_post.call_args[0][0]
        assert called_url.startswith("https://production.plaid.com")


def test_run_fails_loudly_on_invalid_plaid_env():
    with patch.dict(os.environ, {"PLAID_ENV": "not_a_real_environment"}, clear=False):
        try:
            plaid_connector.run()
            assert False, "Expected a ValueError for an invalid PLAID_ENV, got none."
        except ValueError as e:
            assert "not_a_real_environment" in str(e)


if __name__ == "__main__":
    test_build_record_filters_to_only_dani_austin()
    test_build_record_returns_none_if_target_account_missing()
    test_run_writes_only_one_record_despite_five_accounts_returned()
    test_run_skips_gracefully_when_credentials_missing()
    test_run_defaults_to_production_when_plaid_env_unset()
    test_run_uses_sandbox_url_when_plaid_env_is_sandbox()
    test_run_treats_empty_string_plaid_env_same_as_unset()
    test_run_fails_loudly_on_invalid_plaid_env()
    print("All Plaid connector tests passed.")
