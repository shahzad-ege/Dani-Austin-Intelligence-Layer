"""
test_airtable_connector.py — Tests Airtable connector parsing against a
fake records response, no real network/database calls.
"""

import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("AIRTABLE_API_KEY", "test")
os.environ.setdefault("AIRTABLE_BASE_ID", "test")

import airtable_connector  # noqa: E402


FAKE_RECORDS_PAGE_1 = {
    "records": [
        {
            "id": "rec001",
            "fields": {
                "Invoice #": "INV-1001",
                "Status": "Invoiced",
                "Platform": "IG In-Feed",
                "Agency Source": "Acme Agency",
                "Returning Partner": True,
                "Gross Amount": 5000,
                "Net Amount": 4250,
                "Month Committed": "2026-03-01",
                "Month Completed": "2026-04-01",
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
                "Invoice #": None,
                "Status": "Contract",
                "Platform": "TikTok",
                "Agency Source": None,
                "Returning Partner": False,
                "Gross Amount": 3000,
                "Net Amount": 3000,
                "Month Committed": "2026-05-01",
                "Month Completed": None,
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


def test_run_parses_fields_and_handles_missing_dates():
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
        assert first["invoice_no"] == "INV-1001"
        assert first["deliverable_platform"] == "IG In-Feed"
        assert first["month_completed"] == "2026-04-01"

        second = written_rows[1]
        assert second["deal_id"] == "rec002"
        assert second["month_completed"] is None  # missing date handled, not crashed


if __name__ == "__main__":
    test_fetch_records_paginates_correctly()
    test_run_parses_fields_and_handles_missing_dates()
    print("All Airtable connector tests passed.")
