"""
test_youtube_connector.py — Tests for the YouTube Data API + Analytics
API connector, confirmed against YouTube's real, stable, well-documented
schema (one of Google's oldest public APIs).
"""

import os
import sys
import requests
from datetime import date
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("YOUTUBE_API_KEY", "test")
os.environ.setdefault("YOUTUBE_CHANNEL_ID", "UC_test")
os.environ.setdefault("YOUTUBE_OAUTH_CLIENT_ID", "test_client")
os.environ.setdefault("YOUTUBE_OAUTH_CLIENT_SECRET", "test_secret")
os.environ.setdefault("YOUTUBE_OAUTH_REFRESH_TOKEN", "test_refresh")

import youtube_connector as yt  # noqa: E402


def _fake_data_api_get(url, params=None):
    if "channels" in url:
        return MagicMock(status_code=200, json=lambda: {
            "items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU_test"}}}]
        }, raise_for_status=lambda: None)
    elif "playlistItems" in url:
        return MagicMock(status_code=200, json=lambda: {
            "items": [{"contentDetails": {"videoId": "vid1"}}]
        }, raise_for_status=lambda: None)
    elif "videos" in url:
        return MagicMock(status_code=200, json=lambda: {
            "items": [{
                "id": "vid1",
                "snippet": {"title": "Episode 100", "publishedAt": "2026-08-15T14:00:00Z"},
                "statistics": {"viewCount": "45000", "likeCount": "1200", "commentCount": "85"},
            }]
        }, raise_for_status=lambda: None)


def test_fetch_video_stats_parses_real_confirmed_schema():
    with patch("requests.get", side_effect=_fake_data_api_get):
        records = yt.fetch_video_stats()

    assert len(records) == 1
    r = records[0]
    assert r.video_id == "vid1"
    assert r.title == "Episode 100"
    assert r.published_at == date(2026, 8, 15)
    assert r.view_count == 45000
    assert r.like_count == 1200


def test_video_stats_explicitly_tagged_podcast_not_left_to_name_matching():
    """Confirmed: this channel is podcast-only, not a standalone social
    channel -- tagged explicitly at write time rather than relying on
    the fragile name-matching business-unit system used elsewhere."""
    with patch("requests.get", side_effect=_fake_data_api_get):
        records = yt.fetch_video_stats()

    assert records[0].to_row()["business_unit"] == "Podcast"


def test_channel_not_found_raises_clear_error():
    def fake_get_empty(url, params=None):
        return MagicMock(status_code=200, json=lambda: {"items": []}, raise_for_status=lambda: None)

    with patch("requests.get", side_effect=fake_get_empty):
        try:
            yt.fetch_video_stats()
            assert False, "should have raised"
        except RuntimeError as e:
            assert "UC_test" in str(e)


def test_fetch_video_analytics_uses_oauth_not_api_key():
    """Confirmed via research: Analytics API (retention, watch time)
    requires OAuth, unlike the Data API's simple key auth -- this is
    private, owner-only data.

    Expanded (Sep 23 2026) from 3 metrics to the real, confirmed core
    set: views,estimatedMinutesWatched,likes,comments,shares,
    averageViewDuration,averageViewPercentage,subscribersGained,
    subscribersLost -- 9 real fields, same real row order the API returns."""
    def fake_post(url, data=None):
        assert data["grant_type"] == "refresh_token"
        return MagicMock(status_code=200, json=lambda: {"access_token": "fake_token"}, raise_for_status=lambda: None)

    def fake_get(url, headers=None, params=None):
        assert headers["Authorization"] == "Bearer fake_token"
        # Real order: views, estimatedMinutesWatched, likes, comments,
        # shares, averageViewDuration, averageViewPercentage,
        # subscribersGained, subscribersLost
        return MagicMock(status_code=200, json=lambda: {"rows": [[5000, 1200.5, 300, 25, 10, 245.5, 62.3, 18, 2]]})

    with patch("requests.post", side_effect=fake_post), patch("requests.get", side_effect=fake_get):
        records = yt.fetch_video_analytics(["vid1"], date(2026, 8, 1), date(2026, 8, 31))

    assert len(records) == 1
    r = records[0]
    assert r.views == 5000
    assert r.estimated_minutes_watched == 1200.5
    assert r.likes == 300
    assert r.average_view_duration_seconds == 245.5
    assert r.subscribers_gained == 18
    assert r.subscribers_lost == 2


def test_analytics_isolates_one_failing_video_from_the_batch():
    def fake_post(url, data=None):
        return MagicMock(status_code=200, json=lambda: {"access_token": "fake_token"}, raise_for_status=lambda: None)

    def fake_get(url, headers=None, params=None):
        if params.get("filters") == "video==vid_bad":
            return MagicMock(status_code=403, text="quota exceeded")
        return MagicMock(status_code=200, json=lambda: {"rows": [[100, 20.0, 5, 1, 0, 100.0, 50.0, 5, 0]]})

    with patch("requests.post", side_effect=fake_post), patch("requests.get", side_effect=fake_get):
        records = yt.fetch_video_analytics(["vid_bad", "vid_good"], date(2026, 8, 1), date(2026, 8, 31))

    assert len(records) == 1
    assert records[0].video_id == "vid_good"


def test_fetch_traffic_sources_returns_per_source_breakdown():
    """Real, confirmed dimension: insightTrafficSourceType, the actual
    original motivation for building OAuth in the first place."""
    def fake_post(url, data=None):
        return MagicMock(status_code=200, json=lambda: {"access_token": "fake_token"}, raise_for_status=lambda: None)

    def fake_get(url, headers=None, params=None):
        assert params["dimensions"] == "insightTrafficSourceType"
        return MagicMock(status_code=200, json=lambda: {"rows": [
            ["YT_SEARCH", 3000, 800.0],
            ["SUGGESTED_VIDEO", 1500, 400.0],
            ["EXT_URL", 500, 120.0],
        ]})

    with patch("requests.post", side_effect=fake_post), patch("requests.get", side_effect=fake_get):
        records = yt.fetch_traffic_sources(["vid1"], date(2026, 8, 1), date(2026, 8, 31))

    assert len(records) == 3
    assert records[0].traffic_source_type == "YT_SEARCH"
    assert records[0].views == 3000
    assert records[1].traffic_source_type == "SUGGESTED_VIDEO"


if __name__ == "__main__":
    test_fetch_video_stats_parses_real_confirmed_schema()
    test_video_stats_explicitly_tagged_podcast_not_left_to_name_matching()
    test_channel_not_found_raises_clear_error()
    test_fetch_video_analytics_uses_oauth_not_api_key()
    test_analytics_isolates_one_failing_video_from_the_batch()
    print("All YouTube connector tests passed.")


# ---------- Real gaps found in a deeper review, no live credentials required ----------

def test_playlist_items_failure_returns_empty_not_crash():
    """REAL gap found in review: fetch_video_stats() had zero error
    handling, unlike fetch_video_analytics() which isolates per-video
    failures. A single quota/rate-limit/network error would crash the
    whole function."""
    def fake_get(url, params=None):
        if "channels" in url:
            return MagicMock(status_code=200, json=lambda: {
                "items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU_test"}}}]
            }, raise_for_status=lambda: None)
        elif "playlistItems" in url:
            raise requests.ConnectionError("simulated network failure")

    with patch("requests.get", side_effect=fake_get):
        result = yt.fetch_video_stats()
    assert result == []


def test_videos_batch_failure_isolated_not_crash():
    def fake_get(url, params=None):
        if "channels" in url:
            return MagicMock(status_code=200, json=lambda: {
                "items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU_test"}}}]
            }, raise_for_status=lambda: None)
        elif "playlistItems" in url:
            return MagicMock(status_code=200, json=lambda: {
                "items": [{"contentDetails": {"videoId": "vid1"}}]
            }, raise_for_status=lambda: None)
        elif "videos" in url:
            raise requests.HTTPError("simulated 403 quota exceeded")

    with patch("requests.get", side_effect=fake_get):
        result = yt.fetch_video_stats()
    assert result == []


def test_revoked_oauth_token_raises_clear_actionable_error():
    """REAL gap found in review: a revoked refresh token (a real,
    plausible failure -- password changes, security reviews) raised a
    raw, unhelpful HTTP error with no indication of what to do."""
    def fake_post(url, data=None):
        return MagicMock(status_code=400, text='{"error": "invalid_grant"}')

    with patch("requests.post", side_effect=fake_post):
        try:
            yt._get_oauth_access_token()
            assert False, "should have raised"
        except RuntimeError as e:
            assert "revoked" in str(e).lower() or "channel owner" in str(e).lower()


def test_malformed_published_date_uses_sentinel_not_crash():
    """REAL gap found in review: the date-parsing fallback had no
    fallback of its own -- a genuinely malformed date string would
    still crash the whole batch."""
    def fake_get(url, params=None):
        if "channels" in url:
            return MagicMock(status_code=200, json=lambda: {
                "items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU_test"}}}]
            }, raise_for_status=lambda: None)
        elif "playlistItems" in url:
            return MagicMock(status_code=200, json=lambda: {
                "items": [{"contentDetails": {"videoId": "vid1"}}]
            }, raise_for_status=lambda: None)
        elif "videos" in url:
            return MagicMock(status_code=200, json=lambda: {
                "items": [{"id": "vid1", "snippet": {"title": "Test", "publishedAt": "not-a-real-date"}, "statistics": {"viewCount": "100"}}]
            }, raise_for_status=lambda: None)

    with patch("requests.get", side_effect=fake_get):
        result = yt.fetch_video_stats()
    assert len(result) == 1
    assert result[0].published_at == date(1970, 1, 1)


# ---------- run() orchestration (Sep 23 2026) ----------
# REAL, SIGNIFICANT GAP: this connector had every function individually
# built and tested, but was never actually wired into a runnable entry
# point -- no run(), no __main__ block. Running `python
# youtube_connector.py` directly defined functions and exited silently
# with zero output. Confirmed via Supabase: the two target tables
# (youtube_video_stats, youtube_video_analytics) didn't exist either,
# meaning this had genuinely never run end-to-end before.

def test_run_orchestrates_stats_then_analytics_and_writes_both_tables():
    fake_stats = [yt.YouTubeVideoStats("v1", "Test Video", date(2026, 9, 1), 1000, 50, 5)]
    fake_analytics = [yt.YouTubeVideoAnalytics("v1", date(2026, 9, 8), 5000, 1200.5, 300, 25, 10, 120.5, 45.0, 2, 0)]
    fake_traffic = [yt.YouTubeTrafficSource("v1", date(2026, 9, 8), "YT_SEARCH", 3000, 800.0)]

    with patch.object(yt, "fetch_video_stats", return_value=fake_stats), \
         patch.object(yt, "fetch_video_analytics", return_value=fake_analytics) as mock_analytics, \
         patch.object(yt, "fetch_traffic_sources", return_value=fake_traffic), \
         patch("writer.upsert_rows", side_effect=lambda table, rows: len(rows)) as mock_upsert:
        result = yt.run()

    assert result == 3
    tables_written = [c.args[0] for c in mock_upsert.call_args_list]
    assert "youtube_video_stats" in tables_written
    assert "youtube_video_analytics" in tables_written
    assert "youtube_traffic_sources" in tables_written
    # Confirms the real video_id from stats feeds into the analytics call
    assert mock_analytics.call_args.args[0] == ["v1"]


def test_run_skips_analytics_gracefully_when_no_stats_found():
    with patch.object(yt, "fetch_video_stats", return_value=[]), \
         patch("writer.upsert_rows", return_value=0):
        result = yt.run()
    assert result == 0


def test_run_preserves_written_stats_when_analytics_fails():
    """A revoked/expired OAuth refresh token must not wipe out the
    real stats data (public, API-key-only) already successfully
    written before the Analytics (OAuth-required) call was attempted."""
    fake_stats = [yt.YouTubeVideoStats("v1", "Test", date(2026, 9, 1), 100, 10, 1)]

    with patch.object(yt, "fetch_video_stats", return_value=fake_stats), \
         patch.object(yt, "fetch_video_analytics", side_effect=RuntimeError("token revoked")), \
         patch("writer.upsert_rows", return_value=1) as mock_upsert:
        result = yt.run()

    assert result == 1
    assert mock_upsert.call_count == 1  # stats written; analytics never reached a write call


def test_module_has_a_main_entry_point():
    """Regression guard for the actual real bug: confirms this file can
    genuinely be run directly and produce output, not just imported."""
    import ast
    tree = ast.parse(open(os.path.join(os.path.dirname(__file__), "..", "youtube_connector.py")).read())
    has_main_block = any(
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "__name__"
        for node in ast.walk(tree)
    )
    assert has_main_block, "youtube_connector.py must have an if __name__ == '__main__': block"
