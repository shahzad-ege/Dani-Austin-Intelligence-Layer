"""
conftest.py — Shared test environment.

Test modules previously each called os.environ.setdefault() at import time,
which meant whichever file pytest imported FIRST won, and the others
silently got the wrong values. That's a real cross-file coupling bug: it
caused test_social_connectors.py to fail once test_post_level.py was added,
purely from import order, with nothing wrong in either test itself.

Setting them once here, before any test module is imported, removes the
ordering dependency entirely.
"""

import os

TEST_ENV = {
    "DA_SUPABASE_URL": "https://fake.supabase.co",
    "DA_SUPABASE_SERVICE_KEY": "fake_key",
    "META_SYSTEM_USER_TOKEN": "test",
    "META_IG_USER_ID": "test_ig_id",
    "META_PAGE_ID": "test_page_id",
    "TIKTOK_CLIENT_KEY": "test",
    "TIKTOK_CLIENT_SECRET": "test",
    "TIKTOK_REFRESH_TOKEN": "test",
    "TIKTOK_BUSINESS_ID": "test_biz_id",
    "SOCIALBLADE_CLIENT_ID": "test",
    "SOCIALBLADE_TOKEN": "test",
    "QB_CLIENT_ID": "test",
    "QB_CLIENT_SECRET": "test",
    "QB_REALM_ID": "test_realm",
    "QB_REFRESH_TOKEN": "test_bootstrap_token",
    "PLAID_CLIENT_ID": "test",
    "PLAID_SECRET": "test",
    "PLAID_ACCESS_TOKEN": "test",
    "BREX_API_TOKEN": "test_token",
    "PAYPAL_CLIENT_ID_DANI": "test",
    "PAYPAL_CLIENT_SECRET_DANI": "test",
    "PAYPAL_CLIENT_ID_KATELYN": "test",
    "PAYPAL_CLIENT_SECRET_KATELYN": "test",
}

for key, value in TEST_ENV.items():
    os.environ[key] = value


import pytest


@pytest.fixture(autouse=True)
def _reset_qb_business_unit_cache():
    """
    Prevents a real network call in ANY test that touches QuickBooks
    extraction. extract_business_unit() -> load_account_business_unit_map()
    calls get_client() and hits Supabase for real unless the module-level
    cache is already populated. Without this, tests written before this
    feature existed (and any future ones that don't think to mock it)
    would intermittently try a real network connection depending on test
    execution order and fail with a ConnectError -- exactly what happened
    when this feature was first added.

    Autouse + empty dict here means: by default, every account looks up as
    'needs_review' (safe, doesn't hit the network) unless a specific test
    explicitly overrides qb_connector._account_business_unit_cache itself.
    """
    try:
        import qb_connector
        qb_connector._account_business_unit_cache = {}
    except ImportError:
        pass  # fine for test files that don't import qb_connector at all
    yield
