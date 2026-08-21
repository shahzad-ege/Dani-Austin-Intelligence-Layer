"""
test_post_level.py — Tests per-post metrics across Instagram (feed/Reels),
Instagram Stories, Facebook Page posts, and TikTok videos.
"""

import os
import sys
import requests
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import meta_connector  # noqa: E402
import tiktok_connector  # noqa: E402


# ---------- Instagram feed / Reels ----------

FAKE_IG_MEDIA = {"data": [
    {"id": "m1", "caption": "A post", "media_type": "IMAGE",
     "permalink": "https://instagram.com/p/a", "timestamp": "2026-08-10T14:30:00+0000"},
    {"id": "m2", "caption": "A reel", "media_type": "VIDEO",
     "permalink": "https://instagram.com/p/b", "timestamp": "2026-08-12T09:00:00+0000"},
]}

FAKE_IG_POST_INSIGHTS = {"data": [
    {"name": "views", "values": [{"value": 50000}]},
    {"name": "reach", "values": [{"value": 42000}]},
    {"name": "follows", "values": [{"value": 87}]},
    {"name": "profile_visits", "values": [{"value": 310}]},
]}


def test_instagram_posts_capture_follower_attribution():
    """`follows` per post is the metric that attributes audience GROWTH to
    specific content -- the diagnosis for an unexplained follower decline."""
    def side_effect(url, params=None):
        if url.endswith("test_ig_id/media"):
            return MagicMock(status_code=200, json=lambda: FAKE_IG_MEDIA, raise_for_status=lambda: None)
        return MagicMock(status_code=200, json=lambda: FAKE_IG_POST_INSIGHTS, raise_for_status=lambda: None)

    with patch("meta_connector.requests.get", side_effect=side_effect):
        posts, metrics = meta_connector.fetch_instagram_posts()

    assert len(posts) == 2
    follows = [m for m in metrics if m.metric == "follows"]
    assert len(follows) == 2
    assert follows[0].value == 87.0


def test_reel_gets_retention_metrics_image_does_not():
    requested = []

    def side_effect(url, params=None):
        if url.endswith("test_ig_id/media"):
            return MagicMock(status_code=200, json=lambda: FAKE_IG_MEDIA, raise_for_status=lambda: None)
        requested.append((params or {}).get("metric", ""))
        return MagicMock(status_code=200, json=lambda: FAKE_IG_POST_INSIGHTS, raise_for_status=lambda: None)

    with patch("meta_connector.requests.get", side_effect=side_effect):
        meta_connector.fetch_instagram_posts()

    assert any("reels_skip_rate" in r for r in requested)   # the VIDEO
    assert any("reels_skip_rate" not in r for r in requested)  # the IMAGE


# ---------- Instagram Stories ----------

FAKE_STORIES = {"data": [
    {"id": "s1", "media_type": "STORY", "permalink": "https://instagram.com/stories/x",
     "timestamp": "2026-08-19T08:00:00+0000"},
]}

# `navigation` returns a DICT of sub-types, not a scalar.
FAKE_STORY_INSIGHTS = {"data": [
    {"name": "views", "values": [{"value": 120000}]},
    {"name": "replies", "values": [{"value": 45}]},
    {"name": "navigation", "values": [{"value": {"taps_forward": 8000, "taps_back": 300, "exits": 1200}}]},
]}


def test_stories_marked_ephemeral_and_navigation_dict_is_flattened():
    """Stories must be flagged ephemeral (insights vanish permanently at
    24h), and `navigation`'s dict-of-subtypes must be flattened into
    separate metrics rather than dropped for not being a scalar."""
    def side_effect(url, params=None):
        if url.endswith("test_ig_id/stories"):
            return MagicMock(status_code=200, json=lambda: FAKE_STORIES, raise_for_status=lambda: None)
        return MagicMock(status_code=200, json=lambda: FAKE_STORY_INSIGHTS, raise_for_status=lambda: None)

    with patch("meta_connector.requests.get", side_effect=side_effect):
        posts, metrics = meta_connector.fetch_instagram_stories()

    assert len(posts) == 1
    assert posts[0].is_ephemeral is True
    assert posts[0].media_type == "STORY"

    names = {m.metric for m in metrics}
    assert "taps_forward" in names   # flattened from the navigation dict
    assert "taps_back" in names
    assert "exits" in names
    assert "navigation" not in names  # not stored as an unusable dict


def test_stories_absent_is_not_an_error(capsys):
    with patch("meta_connector.requests.get") as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200, json=lambda: {"data": []}, raise_for_status=lambda: None)
        posts, metrics = meta_connector.fetch_instagram_stories()

    assert posts == [] and metrics == []
    assert "No live stories" in capsys.readouterr().out


# ---------- Facebook posts ----------

FAKE_PAGE_TOKEN = {"access_token": "page_tok", "id": "test_page_id"}
FAKE_FB_POSTS = {"data": [
    {"id": "p1", "message": "Latest episode", "permalink_url": "https://facebook.com/p/1",
     "created_time": "2026-08-15T10:00:00+0000"},
]}
FAKE_FB_POST_INSIGHTS = {"data": [
    {"name": "post_reactions_by_type_total", "values": [{"value": {"like": 500, "love": 80}}]},
    {"name": "post_clicks", "values": [{"value": 800}]},
]}


def test_facebook_posts_use_page_token():
    meta_connector._page_access_token = None

    def side_effect(url, params=None):
        params = params or {}
        if url.endswith("test_page_id") and params.get("fields") == "access_token":
            return MagicMock(status_code=200, json=lambda: FAKE_PAGE_TOKEN, raise_for_status=lambda: None)
        if url.endswith("test_page_id/posts"):
            assert params.get("access_token") == "page_tok"
            return MagicMock(status_code=200, json=lambda: FAKE_FB_POSTS, raise_for_status=lambda: None)
        assert params.get("access_token") == "page_tok"
        return MagicMock(status_code=200, json=lambda: FAKE_FB_POST_INSIGHTS, raise_for_status=lambda: None)

    with patch("meta_connector.requests.get", side_effect=side_effect):
        posts, metrics = meta_connector.fetch_facebook_posts()

    assert len(posts) == 1 and posts[0].platform == "facebook"
    # post_reactions_by_type_total flattens into one row per reaction type
    # (like, love) via the dict-value handling, plus post_clicks = 3 total.
    assert len(metrics) == 3
    metric_names = {m.metric for m in metrics}
    assert {"like", "love", "post_clicks"} == metric_names


# ---------- TikTok videos ----------

FAKE_TIKTOK_VIDEOS = {"data": {"videos": [
    {
        "item_id": "v1", "create_time": 1786000000, "caption": "A video",
        "share_url": "https://tiktok.com/@x/video/1",
        "video_views": 250000, "likes": 31000, "comments": 420, "shares": 1800,
        "reach": 198000, "full_video_watched_rate": 0.42,
        "total_time_watched": 1250000, "average_time_watched": 5.0,
        "video_duration": 12,
        "impression_sources": [{"impression_source": "For You", "percentage": 0.87}],
        "audience_countries": [{"country": "US", "percentage": 0.91}],
    },
    {
        # Inactive >7 days: TikTok omits the rich fields entirely.
        "item_id": "v2", "create_time": 1785000000, "caption": "Older video",
        "share_url": "https://tiktok.com/@x/video/2",
        "video_views": 90000, "likes": 5000, "comments": 60, "shares": 200,
    },
]}}


def test_tiktok_captures_completion_rate_and_handles_7day_omissions(capsys):
    """full_video_watched_rate is TikTok's dominant algorithmic signal and
    has no Instagram equivalent. Videos inactive >7 days legitimately omit
    the rich fields -- that must be handled, not treated as an error."""
    with patch("tiktok_connector.refresh_access_token", return_value="tok"), \
         patch("tiktok_connector.requests.get") as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200, json=lambda: FAKE_TIKTOK_VIDEOS, raise_for_status=lambda: None)
        posts, metrics = tiktok_connector.fetch_tiktok_videos("tok")

    assert len(posts) == 2

    v1 = {m.metric: m.value for m in metrics if m.post_id == "v1"}
    assert v1["full_video_watched_rate"] == 0.42
    assert v1["average_time_watched"] == 5.0
    assert v1["reach"] == 198000.0

    # v2 lost its rich fields to the 7-day rule -- basic ones still captured
    v2 = {m.metric: m.value for m in metrics if m.post_id == "v2"}
    assert v2["video_views"] == 90000.0
    assert "full_video_watched_rate" not in v2
    assert "reach" not in v2

    # Dimensional data flagged, not silently dropped
    assert "not stored" in capsys.readouterr().out


def test_tiktok_sync_posts_writes_both_tables():
    with patch("tiktok_connector.refresh_access_token", return_value="tok"), \
         patch("tiktok_connector.requests.get") as mock_get, \
         patch("tiktok_connector.upsert_rows") as mock_upsert:
        mock_get.return_value = MagicMock(
            status_code=200, json=lambda: FAKE_TIKTOK_VIDEOS, raise_for_status=lambda: None)
        mock_upsert.return_value = 1
        tiktok_connector.sync_posts()

    tables = [c[0][0] for c in mock_upsert.call_args_list]
    assert "social_posts" in tables and "social_post_metrics" in tables


# ---------- Combined ----------

def test_meta_sync_posts_isolates_a_failing_source(capsys):
    """One failing fetcher (e.g. Stories needing extra permissions) must not
    cost the others."""
    with patch("meta_connector.fetch_instagram_posts", return_value=([], [])), \
         patch("meta_connector.fetch_instagram_stories", side_effect=RuntimeError("no perms")), \
         patch("meta_connector.fetch_facebook_posts", return_value=([], [])), \
         patch("meta_connector.upsert_rows", return_value=0):
        meta_connector.sync_posts()

    out = capsys.readouterr().out
    assert "FAILED" in out and "others unaffected" in out


if __name__ == "__main__":
    print("Run with pytest.")


# ---------- Efficiency fix: learn-once, don't rediscover per post ----------

def test_unsupported_metrics_are_parsed_from_error_message():
    error_text = ('{"error":{"message":"(#100) The Media Insights API does not '
                  'support the follows, profile_visits metric for this media '
                  'product type."}}')
    result = meta_connector._extract_unsupported_metrics(error_text)
    assert result == {"follows", "profile_visits"}


def test_second_post_of_same_media_type_skips_known_bad_metrics_entirely():
    """
    The actual fix for the real slowness: once Meta tells us follows/
    profile_visits are invalid for REEL, the SECOND reel processed should
    never even attempt those metrics -- not rediscover them via another
    failed batch + per-metric retries. This is what turns O(n) wasted calls
    per post into O(1) total discovery cost.
    """
    meta_connector._unsupported_metrics_cache.clear()
    call_log = []

    def fake_get(url, params=None, headers=None, **kwargs):
        metric_str = (params or {}).get("metric", "")
        call_log.append(metric_str)
        resp = MagicMock()
        if "follows" in metric_str or "profile_visits" in metric_str:
            resp.status_code = 400
            resp.text = ('{"error":{"message":"(#100) The Media Insights API does not '
                        'support the follows, profile_visits metric for this media '
                        'product type."}}')
            resp.raise_for_status.side_effect = requests.HTTPError("400", response=resp)
            return resp
        resp.status_code = 200
        resp.json.return_value = {"data": [{"name": "views", "values": [{"value": 100}]}]}
        resp.raise_for_status.side_effect = None
        return resp

    now = datetime.now(timezone.utc)
    with patch("meta_connector.requests.get", side_effect=fake_get):
        # First REEL: must discover the bad metrics (costs extra calls).
        meta_connector._fetch_post_insights(
            "post_1", ["views", "follows", "profile_visits"], now, media_type="REEL"
        )
        calls_after_first = len(call_log)

        # Second REEL: same media_type -- must NOT re-attempt follows/
        # profile_visits at all.
        call_log.clear()
        meta_connector._fetch_post_insights(
            "post_2", ["views", "follows", "profile_visits"], now, media_type="REEL"
        )

    # Only ONE call for the second post (views alone) -- not a failed batch
    # plus fallback retries for metrics already known to be invalid.
    assert len(call_log) == 1
    assert "follows" not in call_log[0]
    assert "profile_visits" not in call_log[0]
    assert calls_after_first > 1  # confirms the first post DID pay discovery cost


def test_different_media_types_have_independent_caches():
    """A metric invalid for REEL shouldn't be assumed invalid for IMAGE --
    the cache is keyed per media_type, not global."""
    meta_connector._unsupported_metrics_cache.clear()
    meta_connector._unsupported_metrics_cache["REEL"] = {"follows"}

    call_log = []

    def fake_get(url, params=None, headers=None, **kwargs):
        call_log.append((params or {}).get("metric", ""))
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"data": [{"name": "follows", "values": [{"value": 5}]}]}
        resp.raise_for_status.side_effect = None
        return resp

    with patch("meta_connector.requests.get", side_effect=fake_get):
        meta_connector._fetch_post_insights(
            "post_x", ["follows"], datetime.now(timezone.utc), media_type="IMAGE"
        )

    # IMAGE's cache is empty even though REEL's has "follows" -- it should
    # still be attempted for IMAGE, not pre-emptively skipped.
    assert len(call_log) == 1
    assert "follows" in call_log[0]


# ---------- Generic (unnamed) failures: still cache, but not per-post conditions ----------

def test_generic_unnamed_failure_still_gets_cached_and_skipped_on_next_post():
    """
    The real Facebook production case: 'The value must be a valid insights
    metric' names NO specific metric (unlike the Reel error, which does).
    The per-metric fallback must still learn from this and cache the
    failing metric, or every Facebook post repeats the full discovery cost
    forever -- which is exactly what happened.
    """
    meta_connector._unsupported_metrics_cache.clear()
    call_log = []

    def fake_get(url, params=None, headers=None, **kwargs):
        metric_str = (params or {}).get("metric", "")
        call_log.append(metric_str)
        resp = MagicMock()
        if metric_str == "post_clicks":  # the one bad metric, isolated
            resp.status_code = 400
            resp.text = '{"error":{"message":"(#100) The value must be a valid insights metric"}}'
            resp.raise_for_status.side_effect = requests.HTTPError("400", response=resp)
            return resp
        if "," in metric_str:  # the initial combined batch also fails generically
            resp.status_code = 400
            resp.text = '{"error":{"message":"(#100) The value must be a valid insights metric"}}'
            resp.raise_for_status.side_effect = requests.HTTPError("400", response=resp)
            return resp
        resp.status_code = 200
        resp.json.return_value = {"data": [{"name": metric_str, "values": [{"value": 10}]}]}
        resp.raise_for_status.side_effect = None
        return resp

    now = datetime.now(timezone.utc)
    with patch("meta_connector.requests.get", side_effect=fake_get):
        meta_connector._fetch_post_insights(
            "fb_post_1", ["post_engaged_users", "post_clicks"], now, media_type="FB_POST"
        )
        first_post_calls = len(call_log)

        call_log.clear()
        meta_connector._fetch_post_insights(
            "fb_post_2", ["post_engaged_users", "post_clicks"], now, media_type="FB_POST"
        )

    # Second post: post_clicks learned as bad, must not be re-attempted.
    assert all("post_clicks" not in c for c in call_log)
    assert len(call_log) == 1  # one clean batch call, not a repeat of the whole discovery
    assert first_post_calls > 1  # first post did pay real discovery cost


def test_insufficient_viewers_is_never_cached_as_a_permanent_failure():
    """
    THE CRITICAL DATA-LOSS TRAP: 'Not enough viewers for the media to show
    insights' is a PER-POST condition (this story didn't get enough views),
    not a media-type incompatibility. If this got cached like a structural
    failure, a DIFFERENT story with plenty of views would have that metric
    wrongly skipped forever -- silently losing real, available data.
    """
    meta_connector._unsupported_metrics_cache.clear()

    def low_viewer_story(url, params=None, headers=None, **kwargs):
        metric_str = (params or {}).get("metric", "")
        resp = MagicMock()
        if "," in metric_str or metric_str == "views":
            resp.status_code = 400
            resp.text = '{"error":{"message":"(#10) Not enough viewers for the media to show insights"}}'
            resp.raise_for_status.side_effect = requests.HTTPError("400", response=resp)
            return resp
        resp.status_code = 200
        resp.json.return_value = {"data": [{"name": metric_str, "values": [{"value": 1}]}]}
        resp.raise_for_status.side_effect = None
        return resp

    now = datetime.now(timezone.utc)
    with patch("meta_connector.requests.get", side_effect=low_viewer_story):
        meta_connector._fetch_post_insights("low_view_story", ["views"], now, media_type="STORY")

    # Must NOT be cached -- a low-view story failing must not poison future
    # STORY posts that DO have enough viewers.
    assert "views" not in meta_connector._unsupported_metrics_cache.get("STORY", set())

    # Prove it: a SECOND, high-viewer story requesting the same metric must
    # still be attempted fresh, not pre-emptively skipped.
    call_log = []

    def high_viewer_story(url, params=None, headers=None, **kwargs):
        call_log.append((params or {}).get("metric", ""))
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"data": [{"name": "views", "values": [{"value": 500000}]}]}
        resp.raise_for_status.side_effect = None
        return resp

    with patch("meta_connector.requests.get", side_effect=high_viewer_story):
        result = meta_connector._fetch_post_insights("high_view_story", ["views"], now, media_type="STORY")

    assert len(call_log) == 1
    assert "views" in call_log[0]  # actually attempted, not skipped
    assert len(result) == 1 and result[0].value == 500000.0  # real data NOT lost
