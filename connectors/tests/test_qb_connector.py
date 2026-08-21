"""
test_qb_connector.py — Tests the Accounting-API-based QuickBooks connector.

This replaces the old Reports-API test suite entirely, since the underlying
approach changed completely (proven necessary by 82.7% real data loss in
production with the old approach -- see qb_connector.py's module docstring).
"""

import os
import sys
from datetime import date
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("QB_CLIENT_ID", "test")
os.environ.setdefault("QB_CLIENT_SECRET", "test")
os.environ.setdefault("QB_REALM_ID", "test_realm")
os.environ.setdefault("QB_REFRESH_TOKEN", "test_bootstrap_token")
os.environ.setdefault("DA_SUPABASE_URL", "https://fake.supabase.co")
os.environ.setdefault("DA_SUPABASE_SERVICE_KEY", "fake_key")

import qb_connector  # noqa: E402


# Realistic multi-line Bill: two expense lines against different accounts,
# one Class-tagged. This is exactly the shape the old identifier bug
# couldn't have handled correctly even if it worked -- doc_num is a
# per-TRANSACTION field, not per-line, so multi-line transactions were
# always going to collapse incorrectly under the old scheme.
FAKE_BILL = {
    "Id": "9001",
    "TxnDate": "2026-06-15",
    "Line": [
        {
            "Id": "1",
            "Amount": 500.00,
            "Description": "June retainer",
            "AccountBasedExpenseLineDetail": {
                "AccountRef": {"name": "Professional Services"},
                "ClassRef": {"name": "Partnerships"},
            },
        },
        {
            "Id": "2",
            "Amount": 89.00,
            "Description": "Software",
            "AccountBasedExpenseLineDetail": {
                "AccountRef": {"name": "Software Expense"},
            },
        },
    ],
}

FAKE_INVOICE = {
    "Id": "5001",
    "TxnDate": "2026-06-20",
    "Line": [
        {
            "Id": "1",
            "Amount": 1200.50,
            "SalesItemLineDetail": {
                "ItemRef": {"name": "Affiliate Commission"},
                "ClassRef": {"name": "Affiliate"},
            },
        }
    ],
}

# A line with no usable detail at all (e.g. a subtotal line) -- must be
# skipped, not crash.
FAKE_BILL_WITH_SUBTOTAL_LINE = {
    "Id": "9002",
    "TxnDate": "2026-06-16",
    "Line": [
        {"Id": "1", "Amount": 100.00, "DetailType": "SubTotalLineDetail"},
        {
            "Id": "2",
            "Amount": 100.00,
            "AccountBasedExpenseLineDetail": {"AccountRef": {"name": "Travel"}},
        },
    ],
}


def test_extract_class_name_falls_back_to_transaction_level():
    """The actual fix for a real bug: 100% of 635 real rows came back with
    source=NULL because ClassRef can live at the transaction header level,
    which the original version never checked at all."""
    txn_with_header_level_class = {"ClassRef": {"name": "Podcast"}}
    line_with_no_class = {}
    detail_with_no_class = {}

    result = qb_connector.extract_class_name(
        txn_with_header_level_class, line_with_no_class, detail_with_no_class
    )
    assert result == "Podcast"


def test_extract_class_name_prints_diagnostic_when_truly_absent(capsys):
    txn_no_class = {"Id": "123", "TxnDate": "2026-06-01"}
    line_no_class = {"Id": "1", "Amount": 50}
    detail_no_class = {"AccountRef": {"name": "Travel"}}

    qb_connector._class_diagnostic_printed = 0  # reset shared counter
    result = qb_connector.extract_class_name(txn_no_class, line_no_class, detail_no_class)

    assert result is None
    output = capsys.readouterr().out
    assert "DIAGNOSTIC" in output
    assert "txn keys" in output


def test_extract_expense_lines_handles_multiple_lines_per_transaction():
    """The core fix: one Bill with two line items must produce TWO
    records, each with its own qb_line_id -- not collapse to one row
    the way the old doc_num-keyed approach effectively risked."""
    records = qb_connector.extract_expense_lines(FAKE_BILL, "Bill")

    assert len(records) == 2
    assert records[0].qb_txn_id == "9001"
    assert records[0].qb_line_id == "1"
    assert records[1].qb_line_id == "2"
    assert records[0].qb_txn_id == records[1].qb_txn_id  # same transaction
    assert records[0].amount == -500.00  # expenses negative
    assert records[1].amount == -89.00
    assert records[0].source == "Partnerships"  # ClassRef extracted
    assert records[1].source == "needs_review"  # no ClassRef, and account not in the (empty, mocked) lookup table


def test_extract_income_lines_produces_positive_amounts():
    records = qb_connector.extract_income_lines(FAKE_INVOICE, "Invoice")

    assert len(records) == 1
    assert records[0].qb_txn_id == "5001"
    assert records[0].category == "income"
    assert records[0].amount == 1200.50  # positive, not negative
    assert records[0].account == "Affiliate Commission"
    assert records[0].source == "Affiliate"


def test_extract_expense_lines_skips_subtotal_lines_without_crashing():
    records = qb_connector.extract_expense_lines(FAKE_BILL_WITH_SUBTOTAL_LINE, "Bill")

    assert len(records) == 1  # the subtotal line skipped, the real one kept
    assert records[0].account == "Travel"


def test_category_is_deterministic_from_entity_type_not_guessed():
    """The old classify_category() guessed from account-name keywords.
    This must now be 100% determined by which QB entity type it is."""
    bill_records = qb_connector.extract_expense_lines(FAKE_BILL, "Bill")
    invoice_records = qb_connector.extract_income_lines(FAKE_INVOICE, "Invoice")

    assert all(r.category == "expense" for r in bill_records)
    assert all(r.category == "income" for r in invoice_records)


def test_refresh_access_token_persists_rotated_token_immediately():
    """The other real bug this rewrite fixes: the new refresh token
    QuickBooks issues on every use must be saved right away, or the next
    scheduled run fails with an invalidated token."""
    with patch("qb_connector.load_stored_refresh_token", return_value="old_token"), \
         patch("qb_connector.requests.post") as mock_post, \
         patch("qb_connector.upsert_rows") as mock_upsert:

        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"access_token": "new_access", "refresh_token": "new_refresh_token"},
            raise_for_status=lambda: None,
        )

        access_token = qb_connector.refresh_access_token()

        assert access_token == "new_access"
        # The NEW refresh token must be what gets saved, not the old one
        mock_upsert.assert_called_once()
        saved_table, saved_rows = mock_upsert.call_args[0]
        assert saved_table == "qb_oauth_credentials"
        assert saved_rows[0]["refresh_token"] == "new_refresh_token"


def test_load_stored_refresh_token_bootstraps_from_env_when_table_empty():
    """First-ever run: no row in qb_oauth_credentials yet, so it must fall
    back to QB_REFRESH_TOKEN from .env rather than failing."""
    fake_client = MagicMock()
    fake_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []

    with patch("qb_connector.get_client", return_value=fake_client):
        token = qb_connector.load_stored_refresh_token()

    assert token == "test_bootstrap_token"  # from the env var set at top of this file


def test_load_stored_refresh_token_prefers_stored_token_over_env():
    """Every run AFTER the first must use the rotated token from Supabase,
    not the original (now-invalidated) .env value."""
    fake_client = MagicMock()
    fake_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"refresh_token": "rotated_token_from_supabase"}
    ]

    with patch("qb_connector.get_client", return_value=fake_client):
        token = qb_connector.load_stored_refresh_token()

    assert token == "rotated_token_from_supabase"


def test_run_queries_all_five_entity_types_and_writes_combined_result():
    with patch("qb_connector.refresh_access_token", return_value="fake_access"), \
         patch("qb_connector.qb_query") as mock_query, \
         patch("qb_connector.upsert_rows") as mock_upsert:

        def query_side_effect(access_token, query):
            if "Bill" in query:
                return [FAKE_BILL]
            if "Invoice" in query:
                return [FAKE_INVOICE]
            return []

        mock_query.side_effect = query_side_effect
        mock_upsert.return_value = 3

        count = qb_connector.run(since=date(2026, 6, 1))

        assert count == 3
        written = mock_upsert.call_args[0][1]
        assert len(written) == 3  # 2 from the Bill, 1 from the Invoice
        assert mock_query.call_count == 5  # Purchase, Bill, Invoice, SalesReceipt, Deposit


if __name__ == "__main__":
    test_extract_expense_lines_handles_multiple_lines_per_transaction()
    test_extract_income_lines_produces_positive_amounts()
    test_extract_expense_lines_skips_subtotal_lines_without_crashing()
    test_category_is_deterministic_from_entity_type_not_guessed()
    test_refresh_access_token_persists_rotated_token_immediately()
    test_load_stored_refresh_token_bootstraps_from_env_when_table_empty()
    test_load_stored_refresh_token_prefers_stored_token_over_env()
    test_run_queries_all_five_entity_types_and_writes_combined_result()
    print("All QuickBooks connector tests passed.")


# ---------- Business unit via account-name lookup (Class confirmed absent) ----------

def test_extract_business_unit_uses_class_when_present():
    """Class checked first -- works automatically if this business ever
    turns Class tracking on later, without needing another code change."""
    txn_with_class = {"ClassRef": {"name": "Podcast"}}
    result = qb_connector.extract_business_unit(txn_with_class, {}, {}, "Some Account")
    assert result == "Podcast"


def test_extract_business_unit_falls_back_to_account_lookup():
    """The actual fix: Class is confirmed absent for this business, so the
    account-name lookup table is what actually determines business_unit."""
    fake_client = MagicMock()
    fake_client.table.return_value.select.return_value.execute.return_value.data = [
        {"account_name": "Brand Partnership", "business_unit": "Partnerships"},
        {"account_name": "Podcast Ad Sponsorship", "business_unit": "Podcast"},
    ]
    qb_connector._account_business_unit_cache = None  # force reload

    with patch("qb_connector.get_client", return_value=fake_client):
        result = qb_connector.extract_business_unit({}, {}, {}, "Brand Partnership")

    assert result == "Partnerships"


def test_extract_business_unit_flags_unmapped_accounts_explicitly():
    """An account not yet in the mapping table must come back as
    'needs_review', NOT silently None or a guessed value -- same philosophy
    as the Domas reference connector."""
    fake_client = MagicMock()
    fake_client.table.return_value.select.return_value.execute.return_value.data = [
        {"account_name": "Brand Partnership", "business_unit": "Partnerships"},
    ]
    qb_connector._account_business_unit_cache = None

    with patch("qb_connector.get_client", return_value=fake_client):
        result = qb_connector.extract_business_unit({}, {}, {}, "Some Brand New Account Nobody Has Seen")

    assert result == "needs_review"


def test_account_business_unit_map_loaded_once_not_per_row():
    """The mapping table must be fetched once per run, not once per
    transaction line -- 635+ real rows would mean 635+ redundant queries
    otherwise."""
    fake_client = MagicMock()
    fake_client.table.return_value.select.return_value.execute.return_value.data = [
        {"account_name": "Brand Partnership", "business_unit": "Partnerships"},
    ]
    qb_connector._account_business_unit_cache = None

    with patch("qb_connector.get_client", return_value=fake_client) as mock_get_client:
        qb_connector.extract_business_unit({}, {}, {}, "Brand Partnership")
        qb_connector.extract_business_unit({}, {}, {}, "Brand Partnership")
        qb_connector.extract_business_unit({}, {}, {}, "Brand Partnership")

    mock_get_client.assert_called_once()
