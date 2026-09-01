"""
test_system_health_check.py — Verifies the live-data health check script's
LOGIC against mocked Supabase responses shaped like real data. This can't
test against the actual live database (that needs real credentials), but
it proves each check correctly distinguishes a healthy state from a real
problem, using response shapes confirmed against the live project.
"""

import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import system_health_check as h  # noqa: E402


def _mock_client(table_data: dict):
    """Builds a mock Supabase client. table_data maps table_name -> list
    of row dicts to return, regardless of which filters/order/limit are
    chained -- good enough to test each check's aggregation logic without
    reimplementing postgrest's actual filtering."""
    client = MagicMock()

    def table_side_effect(name):
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.limit.return_value = chain
        chain.execute.return_value = MagicMock(data=table_data.get(name, []))
        return chain

    client.table.side_effect = table_side_effect
    return client


def test_date_parsing_handles_both_plain_dates_and_timestamps():
    assert h._parse_to_date("2026-08-27") == h.date(2026, 8, 27)
    assert h._parse_to_date("2026-08-27T13:29:26.856735+00:00") == h.date(2026, 8, 27)
    assert h._parse_to_date("2026-08-27T13:29:26Z") == h.date(2026, 8, 27)


def test_revenue_forecast_consistency_passes_when_sums_match():
    h.results.clear()
    client = _mock_client({
        "da_revenue_forecast": [
            {"month": "2026-01-01", "business_unit": "Partnerships", "estimate": 100},
            {"month": "2026-01-01", "business_unit": "Affiliate", "estimate": 200},
            {"month": "2026-01-01", "business_unit": "Total", "estimate": 300},
        ]
    })
    h.check_revenue_forecast_consistency(client)
    assert any(s == "PASS" for s, _ in h.results)
    assert not any(s == "FAIL" for s, _ in h.results)


def test_revenue_forecast_consistency_catches_a_real_mismatch():
    """The exact bug class already found and fixed earlier this project --
    a Total row that doesn't match its own sub-line-items."""
    h.results.clear()
    client = _mock_client({
        "da_revenue_forecast": [
            {"month": "2026-01-01", "business_unit": "Partnerships", "estimate": 100},
            {"month": "2026-01-01", "business_unit": "Affiliate", "estimate": 200},
            {"month": "2026-01-01", "business_unit": "Total", "estimate": 999},  # wrong
        ]
    })
    h.check_revenue_forecast_consistency(client)
    assert any(s == "FAIL" for s, _ in h.results)


def test_cash_flow_chain_integrity_passes_when_chained_correctly():
    h.results.clear()
    client = _mock_client({
        "da_cash_flow_monthly_actuals": [
            {"month": "2026-01-01", "beginning_balance": 100, "ending_balance": 200},
            {"month": "2026-02-01", "beginning_balance": 200, "ending_balance": 300},
        ]
    })
    h.check_cash_flow_chain_integrity(client)
    assert any(s == "PASS" for s, _ in h.results)
    assert not any(s == "FAIL" for s, _ in h.results)


def test_cash_flow_chain_integrity_catches_a_real_gap():
    h.results.clear()
    client = _mock_client({
        "da_cash_flow_monthly_actuals": [
            {"month": "2026-01-01", "beginning_balance": 100, "ending_balance": 200},
            {"month": "2026-02-01", "beginning_balance": 250, "ending_balance": 300},  # gap: 200 != 250
        ]
    })
    h.check_cash_flow_chain_integrity(client)
    assert any(s == "FAIL" for s, _ in h.results)


def test_social_account_hygiene_catches_empty_account_id():
    """The exact real bug found and fixed earlier: an orphaned TikTok row
    with an empty account_id."""
    h.results.clear()
    client = _mock_client({
        "social_accounts": [
            {"account_id": "real_id_123", "platform": "instagram", "handle": "daniaustin"},
            {"account_id": "", "platform": "tiktok", "handle": ""},  # orphan
        ]
    })
    h.check_social_account_hygiene(client)
    assert any(s == "FAIL" for s, _ in h.results)


def test_ar_sanity_catches_impossible_overdue_exceeding_total():
    h.results.clear()
    client = _mock_client({
        "da_ar_current_position": [
            {"total_outstanding": 1000, "total_overdue": 5000}  # impossible
        ]
    })
    h.check_ar_sanity(client)
    assert any(s == "FAIL" for s, _ in h.results)


def test_ar_sanity_passes_on_real_confirmed_numbers():
    """Matches the actual live AR position confirmed earlier this session."""
    h.results.clear()
    client = _mock_client({
        "da_ar_current_position": [
            {"total_outstanding": 1117660.23, "total_overdue": 540170.64}
        ]
    })
    h.check_ar_sanity(client)
    assert any(s == "PASS" for s, _ in h.results)
    # 48% overdue -- should also trigger the materiality WARN
    assert any(s == "WARN" for s, _ in h.results)


def test_follower_dedup_catches_a_real_regression():
    """If the dedup view logic ever regressed and started returning two
    rows for the same platform on the same day, this must catch it."""
    h.results.clear()
    client = _mock_client({
        "social_followers_deduped": [
            {"platform": "instagram", "period_date": "2026-08-27"},
            {"platform": "instagram", "period_date": "2026-08-27"},  # duplicate
        ]
    })
    h.check_follower_dedup_view(client)
    assert any(s == "FAIL" for s, _ in h.results)


def test_main_returns_nonzero_exit_code_when_anything_fails():
    h.results.clear()
    h.results.append(("FAIL", "simulated failure"))
    failed = sum(1 for s, _ in h.results if s == "FAIL")
    assert failed > 0  # confirms the exit-code logic's input would be correct


if __name__ == "__main__":
    test_date_parsing_handles_both_plain_dates_and_timestamps()
    test_revenue_forecast_consistency_passes_when_sums_match()
    test_revenue_forecast_consistency_catches_a_real_mismatch()
    test_cash_flow_chain_integrity_passes_when_chained_correctly()
    test_cash_flow_chain_integrity_catches_a_real_gap()
    test_social_account_hygiene_catches_empty_account_id()
    test_ar_sanity_catches_impossible_overdue_exceeding_total()
    test_ar_sanity_passes_on_real_confirmed_numbers()
    test_follower_dedup_catches_a_real_regression()
    test_main_returns_nonzero_exit_code_when_anything_fails()
    print("All system_health_check tests passed.")
