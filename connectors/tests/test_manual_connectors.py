"""
test_manual_connectors.py — Tests the manual CSV connectors with real,
dummy CSV files written to a temp directory. No mocking needed here since
there's no external API — just verifies the CSV-parsing logic and the
graceful-skip behavior when a file is missing.
"""

import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import manual_forecast_connector  # noqa: E402
import manual_affiliate_connector  # noqa: E402
import manual_podcast_connector  # noqa: E402


def test_revenue_forecast_parses_csv():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "revenue_forecast.csv")
        with open(path, "w") as f:
            f.write("month,business_unit,estimate,goal\n")
            f.write("2026-09-01,Affiliate,15000,18000\n")
            f.write("2026-09-15,Partnerships,40000,45000\n")  # mid-month date, should normalize to 1st

        with patch("manual_forecast_connector.upsert_rows") as mock_upsert:
            mock_upsert.return_value = 2
            count = manual_forecast_connector.load_revenue_forecast(path)

            assert count == 2
            rows = mock_upsert.call_args[0][1]
            assert rows[0]["month"] == "2026-09-01"
            assert rows[1]["month"] == "2026-09-01"  # normalized from the 15th
            assert rows[0]["estimate"] == 15000.0


def test_revenue_forecast_skips_missing_file_gracefully():
    count = manual_forecast_connector.load_revenue_forecast("/tmp/does_not_exist_12345.csv")
    assert count == 0  # should skip, not raise


def test_affiliate_csv_parses_correctly():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "affiliate.csv")
        with open(path, "w") as f:
            f.write("month,platform,gross_commission,clicks\n")
            f.write("2026-06-01,Amazon,1200.50,3400\n")
            f.write("2026-06-01,LTK,2100.00,1900\n")

        with patch("manual_affiliate_connector.upsert_rows") as mock_upsert:
            mock_upsert.return_value = 2
            count = manual_affiliate_connector.run(path)

            assert count == 2
            rows = mock_upsert.call_args[0][1]
            assert rows[0]["platform"] == "Amazon"
            assert rows[0]["clicks"] == 3400
            assert rows[1]["gross_commission"] == 2100.00


def test_podcast_csv_parses_correctly():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "podcast.csv")
        with open(path, "w") as f:
            f.write("show_id,platform,metric,period_date,value\n")
            f.write("dani-austin-show,Spotify,streams,2026-09-01,12000\n")

        with patch("manual_podcast_connector.upsert_rows") as mock_upsert:
            mock_upsert.return_value = 1
            count = manual_podcast_connector.run(path)

            assert count == 1
            rows = mock_upsert.call_args[0][1]
            assert rows[0]["platform"] == "Spotify"
            assert rows[0]["value"] == 12000.0


if __name__ == "__main__":
    test_revenue_forecast_parses_csv()
    test_revenue_forecast_skips_missing_file_gracefully()
    test_affiliate_csv_parses_correctly()
    test_podcast_csv_parses_correctly()
    print("All manual connector tests passed.")
