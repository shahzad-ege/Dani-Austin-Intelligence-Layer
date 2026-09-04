"""
test_youtube_connector.py — Tests for the YouTube Data API + Analytics
API connector, confirmed against YouTube's real, stable, well-documented
schema (one of Google's oldest public APIs).
"""

import os
import sys
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
    private, owner-only data."""
    def fake_post(url, data=None):
        assert data["grant_type"] == "refresh_token"
        return MagicMock(status_code=200, json=lambda: {"access_token": "fake_token"}, raise_for_status=lambda: None)

    def fake_get(url, headers=None, params=None):
        assert headers["Authorization"] == "Bearer fake_token"
        return MagicMock(status_code=200, json=lambda: {"rows": [[245.5, 62.3, 18]]})

    with patch("requests.post", side_effect=fake_post), patch("requests.get", side_effect=fake_get):
        records = yt.fetch_video_analytics(["vid1"], date(2026, 8, 1), date(2026, 8, 31))

    assert len(records) == 1
    assert records[0].average_view_duration_seconds == 245.5
    assert records[0].subscribers_gained == 18


def test_analytics_isolates_one_failing_video_from_the_batch():
    def fake_post(url, data=None):
        return MagicMock(status_code=200, json=lambda: {"access_token": "fake_token"}, raise_for_status=lambda: None)

    def fake_get(url, headers=None, params=None):
        if params.get("filters") == "video==vid_bad":
            return MagicMock(status_code=403, text="quota exceeded")
        return MagicMock(status_code=200, json=lambda: {"rows": [[100.0, 50.0, 5]]})

    with patch("requests.post", side_effect=fake_post), patch("requests.get", side_effect=fake_get):
        records = yt.fetch_video_analytics(["vid_bad", "vid_good"], date(2026, 8, 1), date(2026, 8, 31))

    assert len(records) == 1
    assert records[0].video_id == "vid_good"


if __name__ == "__main__":
    test_fetch_video_stats_parses_real_confirmed_schema()
    test_video_stats_explicitly_tagged_podcast_not_left_to_name_matching()
    test_channel_not_found_raises_clear_error()
    test_fetch_video_analytics_uses_oauth_not_api_key()
    test_analytics_isolates_one_failing_video_from_the_batch()
    print("All YouTube connector tests passed.")
