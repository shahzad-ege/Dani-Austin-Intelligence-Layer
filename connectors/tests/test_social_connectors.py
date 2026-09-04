"""
test_social_connectors.py — Tests Social Blade, Meta, and TikTok connector
parsing logic against fake API responses. No real network/database calls.
"""

import os
import sys
import requests
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
        # Updated count from 1 -> 3 (Sep 2026): fetch_facebook_demographics
        # legitimately adds 2 more Page Insights calls (city + country).
        # Strengthened rather than just relaxed: every one of the 3 calls
        # is checked individually, not just the first -- this is exactly
        # the assertion that caught fetch_facebook_demographics initially
        # shipping without the page token at all.
        page_insights_calls = [
            c for c in mock_get.call_args_list
            if "insights" in c[0][0] and "test_page_id" in c[0][0]
        ]
        assert len(page_insights_calls) == 3
        for call in page_insights_calls:
            assert call[1]["params"]["access_token"] == "fake_page_token_xyz"


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


# ---------- Social Blade daily-history backfill ----------

def test_backfill_uses_daily_array_not_just_totals():
    """The core fix: Social Blade already returns a daily[] array with real
    history in every statistics call, which the regular run() discarded
    entirely except today's single point. This confirms the backfill
    actually parses and writes multiple real historical days, not just
    one."""
    real_shaped_payload = {
        "data": {
            "daily": [
                {"date": "2026-08-11T00:00:00.000Z", "followers": 1100000, "likes": 43100000, "uploads": 1761},
                {"date": "2026-08-12T00:00:00.000Z", "followers": 1100000, "likes": 43200000, "uploads": 1761},
            ]
        }
    }
    tiktok_only = [a for a in social_blade_connector.SEED_ACCOUNTS if a.platform == "tiktok"]

    with patch("social_blade_connector.SEED_ACCOUNTS", tiktok_only), \
         patch("social_blade_connector.fetch_statistics", return_value=real_shaped_payload), \
         patch("social_blade_connector.upsert_rows") as mock_upsert:
        mock_upsert.return_value = 6
        count = social_blade_connector.backfill_from_daily_history()

    rows = mock_upsert.call_args_list[0].args[1]
    dates_written = {r["period_date"] for r in rows}
    assert "2026-08-11" in dates_written
    assert "2026-08-12" in dates_written  # confirms MULTIPLE real days written, not just one


def test_backfill_preserves_real_day_to_day_value_changes():
    """Confirms a genuine value change across two real days (43.1M -> 43.2M
    likes, matching values actually seen in a live diagnostic run) is
    captured correctly, not collapsed to a single repeated value."""
    real_shaped_payload = {
        "data": {
            "daily": [
                {"date": "2026-08-11T00:00:00.000Z", "followers": 1100000, "likes": 43100000, "uploads": 1761},
                {"date": "2026-08-12T00:00:00.000Z", "followers": 1100000, "likes": 43200000, "uploads": 1761},
            ]
        }
    }
    tiktok_only = [a for a in social_blade_connector.SEED_ACCOUNTS if a.platform == "tiktok"]

    with patch("social_blade_connector.SEED_ACCOUNTS", tiktok_only), \
         patch("social_blade_connector.fetch_statistics", return_value=real_shaped_payload), \
         patch("social_blade_connector.upsert_rows") as mock_upsert:
        mock_upsert.return_value = 6
        social_blade_connector.backfill_from_daily_history()

    rows = mock_upsert.call_args_list[0].args[1]
    likes_11 = next(r["value"] for r in rows if r["period_date"] == "2026-08-11" and r["metric"] == "likes")
    likes_12 = next(r["value"] for r in rows if r["period_date"] == "2026-08-12" and r["metric"] == "likes")
    assert likes_11 == 43100000.0
    assert likes_12 == 43200000.0
    assert likes_11 != likes_12  # the actual point: real movement is preserved, not flattened


def test_backfill_isolates_platform_with_missing_daily_array():
    """If one platform's response has no daily[] (unconfirmed shape for
    IG/FB, only TikTok's real structure has been directly verified), that
    platform is skipped with a clear message -- it must not crash the
    whole backfill or silently write nothing for every platform."""
    def fake_fetch(platform, handle):
        if platform == "tiktok":
            return {"data": {"daily": [{"date": "2026-08-12T00:00:00.000Z", "followers": 1100000, "likes": 43200000, "uploads": 1761}]}}
        return {"data": {}}  # no daily[] key at all -- simulates an unconfirmed/different shape

    with patch("social_blade_connector.fetch_statistics", side_effect=fake_fetch), \
         patch("social_blade_connector.upsert_rows") as mock_upsert:
        mock_upsert.return_value = 3
        count = social_blade_connector.backfill_from_daily_history()

    assert count > 0  # tiktok's real data still got written
    written_tables = [c.args[0] for c in mock_upsert.call_args_list]
    assert written_tables.count("social_metrics") == 1  # only one platform actually had data to write


def test_backfill_respects_max_days_limit():
    """max_days lets a caller cap how far back to backfill, rather than
    always writing the full ~30 days Social Blade returns."""
    real_shaped_payload = {
        "data": {
            "daily": [
                {"date": "2026-09-02T00:00:00.000Z", "followers": 1100000, "likes": 43200000, "uploads": 1770},
                {"date": "2026-09-01T00:00:00.000Z", "followers": 1100000, "likes": 43200000, "uploads": 1768},
                {"date": "2026-08-31T00:00:00.000Z", "followers": 1100000, "likes": 43200000, "uploads": 1768},
            ]
        }
    }
    tiktok_only = [a for a in social_blade_connector.SEED_ACCOUNTS if a.platform == "tiktok"]

    with patch("social_blade_connector.SEED_ACCOUNTS", tiktok_only), \
         patch("social_blade_connector.fetch_statistics", return_value=real_shaped_payload), \
         patch("social_blade_connector.upsert_rows") as mock_upsert:
        mock_upsert.return_value = 3
        social_blade_connector.backfill_from_daily_history(max_days=1)

    rows = mock_upsert.call_args_list[0].args[1]
    dates_written = {r["period_date"] for r in rows}
    assert dates_written == {"2026-09-02"}  # only the single most recent day


# ---------- Facebook demographics (BUG-2, confirmed real shape) ----------

def test_fetch_facebook_demographics_parses_real_confirmed_shape():
    """Built directly against a real diagnostic run's output, not a
    guessed shape. period=day (not lifetime) returns city/country as a
    flat {location: count} dict per day, under 'end_time' -- confirmed
    live against the real Facebook API."""
    def fake_get(path, params, token=None):
        if params.get("period") != "day":
            raise AssertionError("period=lifetime was confirmed empty in production -- must use period=day")
        if params.get("metric") == "page_follows_city":
            return {"data": [{"values": [
                {"value": {"New York, NY": 571, "Houston, TX": 544}, "end_time": "2026-07-06T07:00:00+0000"},
            ]}]}
        elif params.get("metric") == "page_follows_country":
            return {"data": [{"values": [
                {"value": {"US": 5000, "EG": 200}, "end_time": "2026-07-06T07:00:00+0000"},
            ]}]}
        return {"data": []}

    with patch("meta_connector.get_page_access_token", return_value="fake_token"), \
         patch("meta_connector._get", side_effect=fake_get):
        records = meta_connector.fetch_facebook_demographics(days_back=30)

    city = [r for r in records if r.dimension == "city"]
    country = [r for r in records if r.dimension == "country"]
    assert len(city) == 2
    assert len(country) == 2
    assert any(r.dimension_value == "New York, NY" and r.value == 571.0 for r in city)
    assert any(r.dimension_value == "US" and r.value == 5000.0 for r in country)


def test_facebook_demographics_cumulative_value_preserved_across_days():
    """Real confirmed finding: the same city's count repeating across
    consecutive days in production means these are cumulative
    totals-to-date, not daily deltas. Confirms a repeated real value is
    stored once per real date, not collapsed or misinterpreted."""
    def fake_get(path, params, token=None):
        if params.get("metric") == "page_follows_city":
            return {"data": [{"values": [
                {"value": {"New York, NY": 571}, "end_time": "2026-07-06T07:00:00+0000"},
                {"value": {"New York, NY": 571}, "end_time": "2026-07-07T07:00:00+0000"},
            ]}]}
        return {"data": []}

    with patch("meta_connector.get_page_access_token", return_value="fake_token"), \
         patch("meta_connector._get", side_effect=fake_get):
        records = meta_connector.fetch_facebook_demographics(days_back=30)

    ny = [(r.period_date, r.value) for r in records if r.dimension_value == "New York, NY"]
    assert len(ny) == 2
    assert ny[0][1] == ny[1][1] == 571.0


def test_facebook_demographics_gender_age_and_locale_never_attempted():
    """confirmed dead (403/invalid metric on every real attempt) --
    the real fetch function must not waste a call retrying them."""
    calls_made = []

    def fake_get(path, params, token=None):
        calls_made.append(params.get("metric"))
        return {"data": []}

    with patch("meta_connector.get_page_access_token", return_value="fake_token"), \
         patch("meta_connector._get", side_effect=fake_get):
        meta_connector.fetch_facebook_demographics(days_back=30)

    assert "page_fans_gender_age" not in calls_made
    assert "page_fans_locale" not in calls_made
    assert set(calls_made) == {"page_follows_city", "page_follows_country"}


def test_facebook_demographics_isolates_a_rejected_dimension():
    """If country gets rejected in the future (scope change, further
    deprecation), city must still be written -- same isolation principle
    used everywhere else in this connector."""
    def fake_get(path, params, token=None):
        if params.get("metric") == "page_follows_country":
            raise requests.HTTPError("rejected")
        return {"data": [{"values": [
            {"value": {"New York, NY": 571}, "end_time": "2026-07-06T07:00:00+0000"},
        ]}]}

    with patch("meta_connector.get_page_access_token", return_value="fake_token"), \
         patch("meta_connector._get", side_effect=fake_get):
        records = meta_connector.fetch_facebook_demographics(days_back=30)

    assert len(records) == 1
    assert records[0].dimension == "city"


def test_facebook_demographics_uses_page_token_not_system_token():
    """Guards against the exact real bug this function shipped with
    initially: calling _get() without an explicit token silently
    defaults to the System User token, which Facebook Page Insights
    rejects with a (#190) error in production. Only caught because an
    existing test asserted on Page Insights call count at the requests.get
    level -- this test asserts on the token explicitly, at the level that
    actually matters, so this class of bug can't silently reappear."""
    with patch("meta_connector.get_page_access_token", return_value="THE_REAL_PAGE_TOKEN") as mock_token, \
         patch("meta_connector._get", return_value={"data": []}) as mock_get:
        meta_connector.fetch_facebook_demographics(days_back=30)

    assert mock_token.called
    for call in mock_get.call_args_list:
        assert call.kwargs.get("token") == "THE_REAL_PAGE_TOKEN"
