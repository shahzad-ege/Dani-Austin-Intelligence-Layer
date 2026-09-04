"""
test_xpoz_connector.py — Tests for the Xpoz social listening connector.

Built against the REAL, installed xpoz SDK's confirmed types and
behavior, not a guessed shape -- rebuilt once already after the first
version (hand-rolled REST calls to a guessed URL) failed against the
live API with 404s. The real SDK was inspected directly to confirm the
correct architecture (MCP-based tool calls via XpozClient, not plain
REST).
"""

import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("XPOZ_API_KEY", "test_key")

import xpoz_connector as xp  # noqa: E402


def _mock_client_with_data(data):
    """REAL bug caught while adding pagination: without explicitly
    setting has_next_page.return_value = False, MagicMock's default
    return value is a truthy mock object -- causing the real
    pagination while-loop to call .next_page() forever. Fixed here so
    every test using this helper correctly simulates a single,
    complete page rather than an infinite one."""
    mock_client = MagicMock()
    for platform in xp.TRACKED_PLATFORMS:
        page = MagicMock()
        page.data = data
        page.has_next_page.return_value = False
        getattr(mock_client, platform).search_posts.return_value = page
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    return mock_client


def test_multiword_keyword_wrapped_in_exact_phrase_quotes():
    """REAL bug, confirmed against a live run: an unquoted 'Dani Austin'
    query matched 'Dani' and 'Austin' independently, returning noise
    (unrelated Portuguese tweets about someone else named Dani; posts
    about Austin, Texas). Confirmed fix via Xpoz's own TS SDK docs:
    exact-phrase search requires double-quote wrapping."""
    mock_client = _mock_client_with_data([])
    with patch("xpoz_connector.XpozClient", return_value=mock_client):
        xp.search_mentions("Dani Austin", "twitter")

    sent_query = mock_client.twitter.search_posts.call_args.args[0]
    assert sent_query == '"Dani Austin"'


def test_single_word_keyword_not_wrongly_quoted():
    mock_client = _mock_client_with_data([])
    with patch("xpoz_connector.XpozClient", return_value=mock_client):
        xp.search_mentions("Nike", "twitter")

    sent_query = mock_client.twitter.search_posts.call_args.args[0]
    assert sent_query == "Nike"


def test_already_quoted_keyword_not_double_quoted():
    """If a caller passes their own boolean/quoted query (e.g. '"Dani
    Austin" AND podcast'), don't wrap it again."""
    mock_client = _mock_client_with_data([])
    with patch("xpoz_connector.XpozClient", return_value=mock_client):
        xp.search_mentions('"Dani Austin" AND podcast', "twitter")

    sent_query = mock_client.twitter.search_posts.call_args.args[0]
    assert sent_query == '"Dani Austin" AND podcast'


def test_invalid_platform_rejected():
    try:
        xp.search_mentions("test", "facebook")
        assert False, "should have raised"
    except ValueError as e:
        assert "facebook" in str(e)


def test_one_platform_failure_does_not_kill_the_batch():
    mock_client = MagicMock()
    mock_client.twitter.search_posts.side_effect = Exception("real API error")
    for platform in ["instagram", "tiktok", "reddit"]:
        page = MagicMock()
        page.data = []
        page.has_next_page.return_value = False
        getattr(mock_client, platform).search_posts.return_value = page
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("xpoz_connector.XpozClient", return_value=mock_client):
        results = xp.fetch_all_mentions('"Dani Austin"')

    assert results["twitter"] == []
    assert "instagram" in results and "tiktok" in results and "reddit" in results


if __name__ == "__main__":
    test_multiword_keyword_wrapped_in_exact_phrase_quotes()
    test_single_word_keyword_not_wrongly_quoted()
    test_already_quoted_keyword_not_double_quoted()
    test_invalid_platform_rejected()
    test_one_platform_failure_does_not_kill_the_batch()
    print("All Xpoz connector tests passed.")


# ---------- Normalization layer, built from real confirmed content ----------

def test_normalize_twitter_from_real_confirmed_fields():
    raw = {"id": "t1", "text": "Dani Austin documented her hair loss journey",
           "author_username": "someuser", "like_count": 50, "retweet_count": 10, "reply_count": 3}
    m = xp._normalize_twitter(raw, '"Dani Austin"')
    assert m.platform == "twitter"
    assert m.content_text == "Dani Austin documented her hair loss journey"
    assert m.author == "someuser"
    assert m.like_count == 50
    assert m.share_count == 10  # retweet_count normalized to share_count
    assert m.url == "https://x.com/someuser/status/t1"


def test_normalize_instagram_from_real_confirmed_fields():
    raw = {"id": "i1", "caption": "visited @thewigfairy", "username": "thewigfairy",
           "like_count": 200, "comment_count": 15, "reshare_count": 5, "code_url": "https://instagram.com/p/abc123"}
    m = xp._normalize_instagram(raw, '"Dani Austin"')
    assert m.content_text == "visited @thewigfairy"
    assert m.share_count == 5  # reshare_count normalized
    assert m.url == "https://instagram.com/p/abc123"


def test_normalize_tiktok_url_deliberately_null():
    """Confirmed real: TikTok's video_url is a list of CDN media URLs,
    not a canonical post page -- deliberately left null rather than
    storing a misleading media link under 'url'."""
    raw = {"id": "tk1", "description": "fun event", "username": "someone", "like_count": 300}
    m = xp._normalize_tiktok(raw, '"Dani Austin"')
    assert m.url is None


def test_normalize_reddit_combines_title_and_selftext():
    raw = {"id": "r1", "title": "Dani Austin's new house is massive",
           "selftext": "Did anyone see the tour?", "author_username": "redditor1",
           "score": 45, "comments_count": 12, "permalink": "/r/blogsnark/comments/abc123/"}
    m = xp._normalize_reddit(raw, '"Dani Austin"')
    assert m.content_text == "Dani Austin's new house is massive: Did anyone see the tour?"
    assert m.url == "https://reddit.com/r/blogsnark/comments/abc123/"
    assert m.like_count == 45  # score used as like_count equivalent


def test_normalize_reddit_link_post_with_no_selftext():
    """A link post (no body text) shouldn't produce a trailing ': '."""
    raw = {"id": "r2", "title": "Just a headline", "selftext": "",
           "author_username": "u2", "score": 10}
    m = xp._normalize_reddit(raw, '"Dani Austin"')
    assert m.content_text == "Just a headline"


def test_normalize_mentions_processes_all_platforms_together():
    raw_results = {
        "twitter": [{"id": "t1", "text": "hi", "author_username": "u1"}],
        "instagram": [{"id": "i1", "caption": "hi", "username": "u2"}],
        "tiktok": [{"id": "tk1", "description": "hi", "username": "u3"}],
        "reddit": [{"id": "r1", "title": "hi", "author_username": "u4"}],
    }
    mentions = xp.normalize_mentions(raw_results, '"Dani Austin"')
    assert len(mentions) == 4
    assert {m.platform for m in mentions} == {"twitter", "instagram", "tiktok", "reddit"}


def test_explicit_fields_requested_not_relying_on_unknown_default():
    """REAL bug, confirmed against a live run: every mention came back
    with like_count=0, even genuine high-engagement Forbes coverage.
    Traced to fields=None being passed straight through to the server,
    meaning an unknown server-side default decided what to return.
    Fixed by explicitly requesting exactly what each normalizer needs."""
    mock_client = _mock_client_with_data([])
    with patch("xpoz_connector.XpozClient", return_value=mock_client):
        xp.search_mentions("Nike", "twitter")

    call_kwargs = mock_client.twitter.search_posts.call_args.kwargs
    assert call_kwargs.get("fields") == xp._REQUESTED_FIELDS["twitter"]
    assert "like_count" in call_kwargs["fields"]


def test_each_platform_requests_its_own_correct_field_set():
    mock_client = _mock_client_with_data([])
    for platform in xp.TRACKED_PLATFORMS:
        with patch("xpoz_connector.XpozClient", return_value=mock_client):
            xp.search_mentions("test", platform)
        sent_fields = getattr(mock_client, platform).search_posts.call_args.kwargs.get("fields")
        assert sent_fields == xp._REQUESTED_FIELDS[platform]


def test_run_matches_the_run_all_scheduling_pattern():
    """run() must match (name, run_fn) -> int, the pattern every
    connector in run_all.py's CONNECTORS list follows."""
    mock_client = _mock_client_with_data([])
    with patch("xpoz_connector.XpozClient", return_value=mock_client), \
         patch("writer.upsert_rows", return_value=42) as mock_upsert:
        result = xp.run()

    assert result == 42
    assert mock_upsert.call_args.args[0] == "earned_mentions"


def test_run_all_py_deliberately_excludes_xpoz_from_daily_schedule():
    """Xpoz moved OUT of the daily run_all.py CONNECTORS list to its own
    weekly workflow (xpoz-weekly-sync.yml) -- confirms it's genuinely
    absent, not accidentally still running daily and blowing the
    ~20% monthly budget target."""
    import run_all
    connector_names = [name for name, _ in run_all.CONNECTORS]
    assert "xpoz_earned_mentions" not in connector_names


# ---------- Pagination, confirmed against the real 100/page server cap ----------

def _make_page(items, has_next):
    page = MagicMock()
    page.data = items
    page.has_next_page.return_value = has_next
    return page


def test_pagination_stops_when_server_runs_out_of_real_pages():
    """REAL finding, confirmed via Xpoz's own docs: server caps each
    page at 100 regardless of requested limit. If only 250 real items
    exist across 3 pages, requesting 1000 must not error or hang --
    it should return all 250 and stop cleanly."""
    page1 = _make_page([MagicMock(model_dump=lambda i=i: {"id": f"p{i}"}) for i in range(100)], True)
    page2 = _make_page([MagicMock(model_dump=lambda i=i: {"id": f"p{i}"}) for i in range(100, 200)], True)
    page3 = _make_page([MagicMock(model_dump=lambda i=i: {"id": f"p{i}"}) for i in range(200, 250)], False)
    page1.next_page.return_value = page2
    page2.next_page.return_value = page3

    mock_client = MagicMock()
    mock_client.twitter.search_posts.return_value = page1
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("xpoz_connector.XpozClient", return_value=mock_client):
        results = xp.search_mentions("Nike", "twitter", limit=1000)

    assert len(results) == 250


def test_pagination_stops_exactly_at_requested_limit():
    """Confirms pagination doesn't over-fetch beyond what was asked for,
    even when more real pages are available."""
    page1 = _make_page([MagicMock(model_dump=lambda i=i: {"id": f"p{i}"}) for i in range(100)], True)
    page2 = _make_page([MagicMock(model_dump=lambda i=i: {"id": f"p{i}"}) for i in range(100, 200)], True)
    page1.next_page.return_value = page2

    mock_client = MagicMock()
    mock_client.twitter.search_posts.return_value = page1
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("xpoz_connector.XpozClient", return_value=mock_client):
        results = xp.search_mentions("Nike", "twitter", limit=150)

    assert len(results) == 150


def test_pagination_handles_a_failing_next_page_gracefully():
    """If a later page fails mid-pagination, return what was
    successfully collected rather than losing everything."""
    page1 = _make_page([MagicMock(model_dump=lambda i=i: {"id": f"p{i}"}) for i in range(100)], True)
    page1.next_page.side_effect = Exception("real transient error")

    mock_client = MagicMock()
    mock_client.twitter.search_posts.return_value = page1
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("xpoz_connector.XpozClient", return_value=mock_client):
        results = xp.search_mentions("Nike", "twitter", limit=1000)

    assert len(results) == 100  # kept the first page's results despite page 2 failing


def test_default_limit_is_1000_matching_weekly_budget():
    """1000/platform x 4 platforms x weekly (~4.33-5 runs/month) =
    17,320-20,000/month, confirmed to land at ~17-20% of the
    100,000/month cap -- matching the requested budget target now that
    this runs weekly, not daily. Restored from 800, which was only
    needed as a compromise for the daily-frequency version."""
    import inspect
    sig = inspect.signature(xp.fetch_all_mentions)
    assert sig.parameters["limit_per_platform"].default == 1000
