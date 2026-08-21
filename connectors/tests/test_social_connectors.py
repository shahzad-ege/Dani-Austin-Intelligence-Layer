"""
test_social_connectors.py — Tests Social Blade, Meta, and TikTok connector
parsing logic against fake API responses. No real network/database calls.
"""

import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("SOCIALBLADE_CLIENT_ID", "test")
os.environ.setdefault("SOCIALBLADE_TOKEN", "test")
os.environ.setdefault("META_SYSTEM_USER_TOKEN", "test")
os.environ.setdefault("META_IG_USER_ID", "test_ig_id")
os.environ.setdefault("META_PAGE_ID", "test_page_id")
os.environ.setdefault("TIKTOK_CLIENT_KEY", "test")
os.environ.setdefault("TIKTOK_CLIENT_SECRET", "test")
os.environ.setdefault("TIKTOK_REFRESH_TOKEN", "test")
os.environ.setdefault("TIKTOK_BUSINESS_ID", "test_biz_id")

import social_blade_connector  # noqa: E402
import meta_connector  # noqa: E402
import tiktok_connector  # noqa: E402


# ---------- Social Blade ----------

FAKE_SB_RESPONSE = {
    "info": {"credits": {"available": 500}},
    "data": {
        "statistics": {
            "total": {"followers": 125000, "media": 842, "engagement_rate": 3.2}
        }
    }
}


def test_social_blade_one_bad_handle_does_not_kill_others():
    """Regression test for a real bug: Facebook returned a 404 (wrong
    handle -- Facebook Pages often use a different vanity slug than
    Instagram/TikTok) and it silently aborted the WHOLE run before this
    fix, so Instagram/TikTok data was lost too even though it succeeded."""
    import requests as _requests

    def side_effect(url, headers=None, params=None):
        if "/facebook/" in url:
            resp = MagicMock(status_code=404)
            resp.raise_for_status.side_effect = _requests.HTTPError("404 Not Found")
            return resp
        return MagicMock(status_code=200, json=lambda: FAKE_SB_RESPONSE, raise_for_status=lambda: None)

    with patch("social_blade_connector.requests.get", side_effect=side_effect), \
         patch("social_blade_connector.upsert_rows") as mock_upsert:
        mock_upsert.return_value = 6
        social_blade_connector.run()

        written_rows = mock_upsert.call_args[0][1]
        # Instagram + TikTok metrics still landed despite Facebook failing
        account_ids = {r["account_id"] for r in written_rows}
        assert "daniaustin_fb" not in account_ids
        assert "daniaustin_ig" in account_ids
        assert "daniaustin_tiktok" in account_ids


def test_social_blade_run_produces_metrics():
    with patch("social_blade_connector.requests.get") as mock_get, \
         patch("social_blade_connector.upsert_rows") as mock_upsert:

        mock_get.return_value = MagicMock(
            status_code=200, json=lambda: FAKE_SB_RESPONSE, raise_for_status=lambda: None
        )
        mock_upsert.return_value = 9  # 3 accounts x 3 metrics (rough)

        social_blade_connector.run()

        # Called once per seeded account (3 accounts)
        assert mock_get.call_count == 3
        written_rows = mock_upsert.call_args[0][1]
        assert any(r["metric"] == "followers" and r["value"] == 125000.0 for r in written_rows)


# ---------- Meta ----------

FAKE_IG_PROFILE = {"followers_count": 98000, "media_count": 512}
# Real shape when metric_type=total_value is passed (which Instagram
# account-level insights require) -- note `total_value`, NOT `values`.
# The earlier version of this fixture used the `values` shape, which is
# why a parser that only handled `values` passed its tests while silently
# dropping every real Instagram insight in production.
FAKE_IG_INSIGHTS = {
    "data": [
        {"name": "reach", "period": "day", "total_value": {"value": 40000}},
        {"name": "views", "period": "day", "total_value": {"value": 61000}},
    ]
}
FAKE_FB_PROFILE = {"followers_count": 21000}
FAKE_FB_INSIGHTS = {
    "data": [
        {"name": "page_follows", "values": [{"value": 21000}]},
        {"name": "page_media_view", "values": [{"value": 8000}]},
    ]
}


FAKE_PAGE_TOKEN_RESPONSE = {"access_token": "fake_page_token_xyz", "id": "test_page_id"}


def test_parse_insights_handles_total_value_shape():
    """Regression test: metric_type=total_value returns `total_value`, not
    `values`. A parser handling only `values` silently dropped every
    Instagram insight in production while its tests still passed."""
    from datetime import date as _date

    payload = {"data": [{"name": "reach", "period": "day", "total_value": {"value": 40000}}]}
    records = meta_connector._parse_insights(payload, "acct_1", _date(2026, 8, 16))

    assert len(records) == 1
    assert records[0].metric == "reach"
    assert records[0].value == 40000.0


def test_parse_insights_handles_values_timeseries_shape():
    from datetime import date as _date

    payload = {
        "data": [
            {"name": "page_follows", "values": [{"value": 100}, {"value": 21000}]},
        ]
    }
    records = meta_connector._parse_insights(payload, "acct_1", _date(2026, 8, 16))

    assert len(records) == 1
    # takes the most recent point, not the first
    assert records[0].value == 21000.0


def test_parse_insights_warns_rather_than_silently_dropping(capsys):
    from datetime import date as _date

    payload = {"data": [{"name": "mystery_metric"}]}  # neither shape present
    records = meta_connector._parse_insights(payload, "acct_1", _date(2026, 8, 16))

    assert records == []
    output = capsys.readouterr().out
    assert "mystery_metric" in output  # made visible, not silently skipped


def test_fetch_metrics_resilient_isolates_a_bad_metric(capsys):
    """The core resilience guarantee: if one metric name is rejected by
    Meta, the OTHER valid metrics must still land. Previously a single bad
    name failed the whole batch, taking every valid metric down with it."""
    import requests as _requests
    from datetime import date as _date

    def fake_get(url, params=None):
        metric = (params or {}).get("metric", "")
        # The batched call (comma-joined) fails, as it would if any one
        # metric in it were invalid.
        if "," in metric or metric == "bad_metric":
            resp = MagicMock(status_code=400)
            resp.raise_for_status.side_effect = _requests.HTTPError("400")
            resp.text = '{"error":{"message":"(#100) invalid metric"}}'
            return resp
        return MagicMock(
            status_code=200,
            json=lambda: {"data": [{"name": metric, "total_value": {"value": 42}}]},
            raise_for_status=lambda: None,
        )

    with patch("meta_connector.requests.get", side_effect=fake_get):
        records = meta_connector._fetch_metrics_resilient(
            "acct/insights",
            ["good_metric_a", "bad_metric", "good_metric_b"],
            {"period": "day"},
            "acct_1",
            _date(2026, 8, 16),
        )

    landed = {r.metric for r in records}
    assert landed == {"good_metric_a", "good_metric_b"}  # bad one skipped, others survived

    output = capsys.readouterr().out
    assert "bad_metric" in output  # explicitly named, not silently lost


def test_meta_run_parses_ig_and_fb_metrics():
    with patch("meta_connector.requests.get") as mock_get, \
         patch("meta_connector.upsert_rows") as mock_upsert:

        # Reset the module-level page token cache so this test doesn't
        # depend on whether another test ran first.
        meta_connector._page_access_token = None

        def side_effect(url, params=None):
            params = params or {}
            if url.endswith("test_ig_id") and "insights" not in url:
                return MagicMock(status_code=200, json=lambda: FAKE_IG_PROFILE, raise_for_status=lambda: None)
            if "insights" in url and "test_ig_id" in url:
                return MagicMock(status_code=200, json=lambda: FAKE_IG_INSIGHTS, raise_for_status=lambda: None)
            # The page-token fetch and the page-profile fetch hit the SAME
            # url and differ only by the `fields` param -- distinguish them.
            if url.endswith("test_page_id") and params.get("fields") == "access_token":
                return MagicMock(status_code=200, json=lambda: FAKE_PAGE_TOKEN_RESPONSE, raise_for_status=lambda: None)
            if url.endswith("test_page_id") and "insights" not in url:
                return MagicMock(status_code=200, json=lambda: FAKE_FB_PROFILE, raise_for_status=lambda: None)
            if "insights" in url and "test_page_id" in url:
                return MagicMock(status_code=200, json=lambda: FAKE_FB_INSIGHTS, raise_for_status=lambda: None)
            raise AssertionError(f"Unexpected URL in test: {url}")

        mock_get.side_effect = side_effect
        mock_upsert.side_effect = [1, len([1, 1])]  # seed_accounts call, then metrics call

        meta_connector.run()

        # last call to upsert_rows is the metrics write
        written_rows = mock_upsert.call_args[0][1]
        metric_names = {r["metric"] for r in written_rows}
        assert "followers" in metric_names
        assert "reach" in metric_names
        assert "page_follows" in metric_names

        # Critical: Page Insights MUST be called with the Page token, not
        # the System User token -- Meta rejects the latter with a (#190).
        page_insights_calls = [
            c for c in mock_get.call_args_list
            if "insights" in c[0][0] and "test_page_id" in c[0][0]
        ]
        assert len(page_insights_calls) == 1
        assert page_insights_calls[0][1]["params"]["access_token"] == "fake_page_token_xyz"


# ---------- TikTok ----------

FAKE_TOKEN_RESPONSE = {"data": {"access_token": "fake_access_token"}}
FAKE_PROFILE_RESPONSE = {"data": {"followers_count": 44000, "profile_views": 9000}}
FAKE_VIDEO_RESPONSE = {
    "data": {
        "videos": [
            {"video_views": 10000, "likes": 800, "comments": 40, "shares": 12},
            {"video_views": 5000, "likes": 300, "comments": 10, "shares": 5},
        ]
    }
}


def test_tiktok_run_aggregates_video_metrics():
    with patch("tiktok_connector.requests.post") as mock_post, \
         patch("tiktok_connector.requests.get") as mock_get, \
         patch("tiktok_connector.upsert_rows") as mock_upsert:

        mock_post.return_value = MagicMock(
            status_code=200, json=lambda: FAKE_TOKEN_RESPONSE, raise_for_status=lambda: None
        )

        def get_side_effect(url, headers=None, params=None):
            if "business/get" in url:
                return MagicMock(status_code=200, json=lambda: FAKE_PROFILE_RESPONSE, raise_for_status=lambda: None)
            if "video/list" in url:
                return MagicMock(status_code=200, json=lambda: FAKE_VIDEO_RESPONSE, raise_for_status=lambda: None)
            raise AssertionError(f"Unexpected URL: {url}")

        mock_get.side_effect = get_side_effect
        mock_upsert.return_value = 6

        tiktok_connector.run()

        written_rows = mock_upsert.call_args[0][1]
        views_row = next(r for r in written_rows if r["metric"] == "views")
        assert views_row["value"] == 15000.0  # 10000 + 5000, aggregated correctly

        likes_row = next(r for r in written_rows if r["metric"] == "likes")
        assert likes_row["value"] == 1100.0  # 800 + 300


if __name__ == "__main__":
    test_social_blade_run_produces_metrics()
    test_meta_run_parses_ig_and_fb_metrics()
    test_tiktok_run_aggregates_video_metrics()
    print("All social connector tests passed.")


# ---------- Item 1 & 3: partial-day detection and demographics ----------

FAKE_DEMOGRAPHICS_RESPONSE = {
    "data": [
        {
            "name": "follower_demographics",
            "total_value": {
                "breakdowns": [
                    {
                        "dimension_keys": ["age"],
                        "results": [
                            {"dimension_values": ["25-34"], "value": 1257000},
                            {"dimension_values": ["35-44"], "value": 688000},
                        ],
                    }
                ]
            },
        }
    ]
}


def test_fetch_instagram_demographics_parses_nested_breakdown_shape():
    """Demographics use a different response shape from ordinary insights --
    values nest under total_value.breakdowns[].results[] with a
    dimension_values list, not a flat value."""
    with patch("meta_connector.requests.get") as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200, json=lambda: FAKE_DEMOGRAPHICS_RESPONSE, raise_for_status=lambda: None
        )
        records = meta_connector.fetch_instagram_demographics()

    # 4 dimensions requested x 2 results each from the same fake payload
    assert len(records) == 8
    age_records = [r for r in records if r.dimension == "age"]
    assert age_records[0].dimension_value == "25-34"
    assert age_records[0].value == 1257000.0


def test_fetch_instagram_demographics_isolates_a_failing_dimension(capsys):
    """One rejected breakdown must not cost the other three."""
    import requests as _requests

    def side_effect(url, params=None):
        if (params or {}).get("breakdown") == "city":
            resp = MagicMock(status_code=400)
            resp.raise_for_status.side_effect = _requests.HTTPError("400")
            resp.text = "{}"
            return resp
        return MagicMock(
            status_code=200, json=lambda: FAKE_DEMOGRAPHICS_RESPONSE, raise_for_status=lambda: None
        )

    with patch("meta_connector.requests.get", side_effect=side_effect):
        records = meta_connector.fetch_instagram_demographics()

    dimensions = {r.dimension for r in records}
    assert "city" not in dimensions       # the failing one skipped
    assert "age" in dimensions            # the others survived
    assert "gender" in dimensions
    assert "REJECTED" in capsys.readouterr().out


def test_batch_response_flags_silently_omitted_metrics(capsys):
    """Meta drops metrics it won't serve rather than erroring. Without this
    detection, a requested metric vanishes with no trace -- exactly how
    follows_and_unfollows was requested for weeks while never appearing in
    the database and never producing a warning."""
    from datetime import date as _date

    def fake_get(url, params=None):
        # Returns only ONE of the two requested metrics.
        return MagicMock(
            status_code=200,
            json=lambda: {"data": [{"name": "reach", "total_value": {"value": 100}}]},
            raise_for_status=lambda: None,
        )

    with patch("meta_connector.requests.get", side_effect=fake_get):
        records = meta_connector._fetch_metrics_resilient(
            "acct/insights",
            ["reach", "follows_and_unfollows"],
            {"period": "day"},
            "acct_1",
            _date(2026, 8, 19),
        )

    assert len(records) == 1  # only reach came back
    output = capsys.readouterr().out
    assert "silently omitted" in output
    assert "follows_and_unfollows" in output
