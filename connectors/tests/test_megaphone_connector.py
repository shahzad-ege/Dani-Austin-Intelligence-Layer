"""
test_megaphone_connector.py — Tests built from a REAL confirmed live
Megaphone API response (Sep 2026), not a guessed shape. Confirmed real
limitation: no download/play counts exist anywhere in this response --
this connector captures real episode metadata and ad-cuepoint data only.
"""

import os
import sys
from datetime import date
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("MEGAPHONE_API_TOKEN", "test")
os.environ.setdefault("MEGAPHONE_NETWORK_ID", "test")
os.environ.setdefault("MEGAPHONE_PODCAST_ID", "test")
os.environ.setdefault("DA_SUPABASE_URL", "https://fake.supabase.co")
os.environ.setdefault("DA_SUPABASE_SERVICE_KEY", "fake")

import megaphone_connector as mc  # noqa: E402

REAL_EPISODE = {
    "id": "391ff658-a722-11f1-9c28-db7996c80302",
    "title": "Would You Pay $6,500 to Get Your Baby to Sleep?",
    "pubdate": "2026-09-03T05:00:00.000Z",
    "duration": "5382.67",
    "episodeNumber": None,
    "seasonNumber": None,
    "status": "published",
    "spotifyStatus": "live",
    "rssStatus": "published",
    "cuepoints": [{"cuepointType": "postroll", "adCount": 1, "adSources": ["auto"]}],
}


def test_parses_real_confirmed_response_shape():
    with patch("requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: [REAL_EPISODE])
        episodes = mc.fetch_episodes()

    assert len(episodes) == 1
    e = episodes[0]
    assert e.title == "Would You Pay $6,500 to Get Your Baby to Sleep?"
    assert e.pubdate == date(2026, 9, 3)
    assert e.duration_seconds == 5382.67
    assert e.ad_count == 1
    assert e.status == "published"
    assert e.spotify_status == "live"


def test_malformed_date_skipped_not_crash():
    bad = {**REAL_EPISODE, "id": "bad1", "pubdate": "not-a-real-date"}
    with patch("requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: [REAL_EPISODE, bad])
        episodes = mc.fetch_episodes()
    assert len(episodes) == 1
    assert episodes[0].episode_id == REAL_EPISODE["id"]


def test_missing_duration_defaults_to_zero():
    ep = {**REAL_EPISODE, "id": "ep_no_dur", "duration": None}
    with patch("requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: [ep])
        episodes = mc.fetch_episodes()
    assert episodes[0].duration_seconds == 0.0


def test_multiple_cuepoints_summed_correctly():
    ep = {**REAL_EPISODE, "id": "ep_multi_ads",
          "cuepoints": [{"adCount": 2}, {"adCount": 3}, {"adCount": None}]}
    with patch("requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: [ep])
        episodes = mc.fetch_episodes()
    assert episodes[0].ad_count == 5


def test_no_cuepoints_gives_zero_ad_count():
    ep = {**REAL_EPISODE, "id": "ep_no_ads", "cuepoints": []}
    with patch("requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: [ep])
        episodes = mc.fetch_episodes()
    assert episodes[0].ad_count == 0


def test_http_error_returns_empty_not_crash():
    with patch("requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=403, text='{"error":"forbidden"}')
        episodes = mc.fetch_episodes()
    assert episodes == []


def test_timeout_returns_empty_not_crash():
    import requests
    with patch("requests.get", side_effect=requests.Timeout("simulated")):
        episodes = mc.fetch_episodes()
    assert episodes == []


def test_unexpected_response_shape_handled():
    """If the API ever wraps results in an object instead of a bare
    list, this must not crash -- same defensive pattern used elsewhere
    in this project for uncertain response shapes."""
    with patch("requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {"data": []})
        episodes = mc.fetch_episodes()
    assert episodes == []


def test_run_writes_to_correct_table():
    with patch("megaphone_connector.fetch_episodes", return_value=[
        mc.MegaphoneEpisode("ep1", "Test", date(2026, 1, 1), 100.0, None, None, "published", "live", "published", 2)
    ]), patch("writer.upsert_rows", return_value=1) as mock_upsert:
        result = mc.run()

    assert result == 1
    assert mock_upsert.call_args.args[0] == "podcast_episodes_megaphone"


def test_run_handles_empty_episodes_gracefully():
    with patch("megaphone_connector.fetch_episodes", return_value=[]):
        result = mc.run()
    assert result == 0
