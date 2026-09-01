"""
test_airtable_connector.py — Tests Airtable connector parsing against fake
records shaped like the REAL, CONFIRMED base schema (fetched via
check_airtable_schema.py against the live base), not the original guessed
field names. The old version of this test used "Invoice #", "Platform",
"Agency Source" -- all confirmed wrong once the real schema was seen.
"""

import os
import sys
from datetime import date
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("AIRTABLE_API_KEY", "test")
os.environ.setdefault("AIRTABLE_BASE_ID", "test")

import airtable_connector  # noqa: E402


# Field names below are the REAL ones confirmed against the live base.
FAKE_RECORDS_PAGE_1 = {
    "records": [
        {
            "id": "rec001",
            "fields": {
                "Invoice Number": "INV-1001",
                "Status": "Invoiced",
                "Deliverables": "IG In-Feed",
                "Client": "Acme Agency",
                "Gross Amt": 5000,
                "Net Amt": 4250,
                "Month Committed": "2026-03-01",
                "Month Completed": "2026-04-01",
                "In QBO": True,
                "Invoice Status": "Paid",
                "Agreement Status": "Signed",
            },
        }
    ],
    "offset": "page2token",
}

FAKE_RECORDS_PAGE_2 = {
    "records": [
        {
            "id": "rec002",
            "fields": {
                "Invoice Number": None,
                "Status": "Contract",
                "Deliverables": "TikTok",
                "Client": None,
                "Gross Amt": 3000,
                "Net Amt": 3000,
                "Month Committed": "2026-05-01",
                "Month Completed": None,
                "In QBO": False,
            },
        }
    ]
    # no offset -> pagination ends
}


def test_fetch_records_paginates_correctly():
    with patch("airtable_connector.requests.get") as mock_get:
        mock_get.side_effect = [
            MagicMock(status_code=200, json=lambda: FAKE_RECORDS_PAGE_1, raise_for_status=lambda: None),
            MagicMock(status_code=200, json=lambda: FAKE_RECORDS_PAGE_2, raise_for_status=lambda: None),
        ]
        records = airtable_connector.fetch_records()

    assert len(records) == 2
    assert records[0]["id"] == "rec001"
    assert records[1]["id"] == "rec002"


def test_fetch_records_logs_error_body_before_raising():
    """The real bug this project actually hit: a bare raise_for_status()
    threw away Airtable's error detail, making a 403
    (INVALID_PERMISSIONS_OR_MODEL_NOT_FOUND) indistinguishable from any
    other failure. Confirms the fix logs the body first."""
    import requests as real_requests
    with patch("airtable_connector.requests.get") as mock_get, \
         patch("builtins.print") as mock_print:
        error_resp = MagicMock(status_code=403, text='{"error":{"type":"INVALID_PERMISSIONS_OR_MODEL_NOT_FOUND"}}')
        error_resp.raise_for_status.side_effect = real_requests.HTTPError("403")
        mock_get.return_value = error_resp

        try:
            airtable_connector.fetch_records()
        except real_requests.HTTPError:
            pass

        printed = [str(c.args[0]) for c in mock_print.call_args_list]
        assert any("INVALID_PERMISSIONS_OR_MODEL_NOT_FOUND" in p for p in printed)


def test_run_parses_confirmed_real_field_names():
    with patch("airtable_connector.requests.get") as mock_get, \
         patch("airtable_connector.upsert_rows") as mock_upsert:

        mock_get.side_effect = [
            MagicMock(status_code=200, json=lambda: FAKE_RECORDS_PAGE_1, raise_for_status=lambda: None),
            MagicMock(status_code=200, json=lambda: FAKE_RECORDS_PAGE_2, raise_for_status=lambda: None),
        ]
        mock_upsert.return_value = 2

        count = airtable_connector.run()

        assert count == 2
        written_rows = mock_upsert.call_args[0][1]

        first = written_rows[0]
        assert first["deal_id"] == "rec001"
        assert first["invoice_no"] == "INV-1001"  # from "Invoice Number", not "Invoice #"
        assert first["deliverable_platform"] == "IG In-Feed"  # from "Deliverables", not "Platform"
        assert first["client"] == "Acme Agency"  # from "Client", not "Agency Source"
        assert first["gross_amt"] == 5000  # from "Gross Amt", not "Gross Amount"
        assert first["month_completed"] == "2026-04-01"
        assert first["in_qbo"] is True  # the new, real reconciliation signal
        assert first["invoice_status"] == "Paid"
        assert first["is_repeat"] is None  # always None -- no real field exists

        second = written_rows[1]
        assert second["deal_id"] == "rec002"
        assert second["month_completed"] is None  # missing date handled, not crashed
        assert second["in_qbo"] is False


def test_unchecked_checkbox_field_is_false_not_null():
    """Real Airtable API behavior, confirmed against their own docs: an
    unchecked checkbox is OMITTED from the response entirely, not
    returned as false. A naive fields.get() would store this as NULL
    (genuinely unknown) when it almost always means definitely
    unchecked -- these are different meanings that matter for anyone
    querying in_qbo later."""
    records_missing_checkbox = {
        "records": [
            {
                "id": "rec004",
                "fields": {
                    "Invoice Number": "INV-5555",
                    "Status": "Contract",
                    # "In QBO" key is deliberately ABSENT -- this is what
                    # Airtable actually sends for an unchecked box, not
                    # {"In QBO": false}
                },
            }
        ]
    }
    with patch("airtable_connector.requests.get") as mock_get, \
         patch("airtable_connector.upsert_rows") as mock_upsert:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: records_missing_checkbox, raise_for_status=lambda: None)
        mock_upsert.return_value = 1

        airtable_connector.run()

        row = mock_upsert.call_args[0][1][0]
        assert row["in_qbo"] is False  # NOT None


def test_unparseable_date_does_not_crash_the_whole_sync():
    """Month Committed/Completed are singleLineText in the real base, not
    a proper date field -- confirmed via schema check. Free text like
    'TBD' or 'Q1 2026' must be handled gracefully, not crash the sync."""
    weird_date_records = {
        "records": [
            {
                "id": "rec003",
                "fields": {
                    "Invoice Number": "INV-9999",
                    "Status": "Contract",
                    "Month Committed": "TBD",  # not a real date at all
                    "Month Completed": "Q1 2026",  # also not ISO-parseable
                },
            }
        ]
    }
    with patch("airtable_connector.requests.get") as mock_get, \
         patch("airtable_connector.upsert_rows") as mock_upsert:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: weird_date_records, raise_for_status=lambda: None)
        mock_upsert.return_value = 1

        count = airtable_connector.run()  # must NOT raise

        assert count == 1
        row = mock_upsert.call_args[0][1][0]
        assert row["month_committed"] is None
        assert row["month_completed"] is None


def test_month_year_format_is_recovered_not_discarded():
    """Confirmed against a real production run (1,351 records): the
    dominant real pattern is 'Month YYYY' text (e.g. 'January 2021'),
    not ISO. This recovers the large majority of what a naive ISO-only
    parser would silently drop."""
    assert airtable_connector._parse_month("January 2021") == date(2021, 1, 1)
    assert airtable_connector._parse_month("August 2023") == date(2023, 8, 1)
    assert airtable_connector._parse_month("June 2024") == date(2024, 6, 1)
    # Still handles real ISO dates (backward compatible)
    assert airtable_connector._parse_month("2026-04-01") == date(2026, 4, 1)


def test_bare_month_with_no_year_stays_null_not_guessed():
    """Genuinely ambiguous -- no way to know which year is meant.
    Guessing one would be fabricating data, not parsing it."""
    assert airtable_connector._parse_month("June") is None
    assert airtable_connector._parse_month("November") is None
    assert airtable_connector._parse_month("February ") is None  # trailing space, still bare


def test_likely_source_typos_stay_null_not_silently_corrected():
    """Real values found in production: 'September 22024' (extra digit),
    'January 20' (likely truncated). These are data-quality issues in the
    SOURCE base -- must not be silently "fixed" by guessing the intended
    value."""
    assert airtable_connector._parse_month("September 22024") is None
    assert airtable_connector._parse_month("January 20") is None


def test_suspiciously_far_future_date_is_parsed_and_flagged_not_discarded():
    """'September 2033' is syntactically valid -- the code has no
    legitimate way to know it's PROBABLY a typo for 2023. Silently
    nulling it would just be a different kind of guessing. Correct
    behavior: parse it as literally stated, but flag it for a human."""
    with patch("builtins.print") as mock_print:
        result = airtable_connector._parse_month("September 2033")

    assert result == date(2033, 9, 1)  # NOT discarded
    printed = [str(c.args[0]) for c in mock_print.call_args_list]
    assert any("unusually far in the future" in p for p in printed)  # but flagged


if __name__ == "__main__":
    test_fetch_records_paginates_correctly()
    test_fetch_records_logs_error_body_before_raising()
    test_run_parses_confirmed_real_field_names()
    test_unparseable_date_does_not_crash_the_whole_sync()
    print("All Airtable connector tests passed.")
