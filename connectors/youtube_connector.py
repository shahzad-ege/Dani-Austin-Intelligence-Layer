"""
youtube_connector.py — Podcast video performance via YouTube's own APIs,
confirmed as the highest-leverage upgrade to the podcast layer (see
ENHANCEMENT RECOMMENDATIONS #4 in the Claude Project instructions):
currently only tracked via Podstock's weekly aggregate scrape, which has
no per-episode breakdown at all. YouTube's own free APIs solve exactly
that gap.

Two genuinely different APIs, confirmed via real research, not assumed:

  1. YouTube Data API v3 -- PUBLIC data (views, likes, comments, video
     list). Simple API key auth, no OAuth needed. Free, quota-based
     (10,000 units/day default, most reads cost 1 unit).

  2. YouTube Analytics API -- PRIVATE, owner-only data (average view
     duration, retention curves, traffic sources, subscriber attribution
     per video). REQUIRES OAuth 2.0 -- an API key alone is not enough,
     since this is data only the channel owner can see. This is the
     richer half of what was actually wanted (retention curves, traffic
     sources), so OAuth setup isn't optional if the real goal is met.

SETUP NEEDED BEFORE EITHER FUNCTION WORKS:
  1. Create a project in the Google Cloud Console (console.cloud.google.com)
     -- free.
  2. Enable "YouTube Data API v3" AND "YouTube Analytics API" for that
     project (APIs & Services -> Library -> search each by name -> Enable).
  3. For the Data API (views/likes/comments):
       - APIs & Services -> Credentials -> Create Credentials -> API key
       - Restrict the key to "YouTube Data API v3" specifically
       - Set as YOUTUBE_API_KEY
  4. For the Analytics API (retention/traffic sources) -- OAuth is
     required, this project's Claude cannot complete this step itself,
     it needs a real browser consent flow performed once by whoever owns
     the YouTube channel:
       - APIs & Services -> Credentials -> Create Credentials -> OAuth
         client ID (type: Desktop app)
       - Download the client secret JSON
       - Run Google's OAuth quickstart flow ONE TIME (opens a browser,
         asks the channel owner to grant access) to get a refresh token
       - Set YOUTUBE_OAUTH_CLIENT_ID, YOUTUBE_OAUTH_CLIENT_SECRET,
         YOUTUBE_OAUTH_REFRESH_TOKEN
  5. Find the channel's ID: visible in YouTube Studio under
     Settings -> Channel -> Advanced settings, or in the channel URL.
     Set as YOUTUBE_CHANNEL_ID.

REAL, DATED FINDING (confirmed directly from Google's own YouTube Data
API revision history, checked Sep 2026): as of June 1, 2026, the API
moved to a granular quota system. `search.list` now draws from its own
separate bucket, capped at ~100 calls/day, completely independent of
the shared 10,000-unit pool -- a real bottleneck for anything built
around keyword search. This connector is confirmed UNAFFECTED: it was
built using the standard "uploads playlist" pattern (channels.list ->
playlistItems.list -> videos.list) to list a channel's own videos,
never search.list, so it draws only from the untouched 10,000-unit
pool. Worth knowing if the scope ever expands to searching OTHER
creators' content by keyword -- that would hit the new 100/day cap
this connector currently has no exposure to.

Confirmed real, stable response field names below are based on YouTube
Data/Analytics API v3's long-established, well-documented schema (one of
Google's oldest, most stable public APIs) -- higher confidence than the
newer/less-documented APIs elsewhere in this project, so this was NOT
built diagnostic-first the way Facebook demographics or Megaphone were.
Still worth a real live test before fully trusting it, same as anything
new in this codebase.
"""

import os
import requests
from datetime import date, datetime
from dataclasses import dataclass
from dotenv import load_dotenv, find_dotenv

# REAL, CONFIRMED ROOT CAUSE (Sep 23 2026): this file never called
# load_dotenv() at all -- every other script in this project does,
# including get_youtube_refresh_token.py (which is exactly why that
# one worked while this one reported every credential as missing,
# even though the real .env file had correct values the whole time).
# Uses find_dotenv(usecwd=True), not plain load_dotenv(), matching
# db.py's own documented reasoning: plain load_dotenv() locates .env
# by inspecting the Python call stack, which is unreliable once a
# module is loaded several imports deep -- find_dotenv(usecwd=True)
# searches from the actual working directory instead, which is what
# every connector script is run from directly.
load_dotenv(find_dotenv(usecwd=True))

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
YOUTUBE_CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID")
YOUTUBE_OAUTH_CLIENT_ID = os.environ.get("YOUTUBE_OAUTH_CLIENT_ID")
YOUTUBE_OAUTH_CLIENT_SECRET = os.environ.get("YOUTUBE_OAUTH_CLIENT_SECRET")
YOUTUBE_OAUTH_REFRESH_TOKEN = os.environ.get("YOUTUBE_OAUTH_REFRESH_TOKEN")

DATA_API_BASE = "https://www.googleapis.com/youtube/v3"
ANALYTICS_API_BASE = "https://youtubeanalytics.googleapis.com/v2"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"


@dataclass
class YouTubeVideoStats:
    video_id: str
    title: str
    published_at: date
    view_count: int
    like_count: int
    comment_count: int

    def to_row(self) -> dict:
        return {
            "video_id": self.video_id,
            "title": self.title,
            "published_at": self.published_at.isoformat(),
            "view_count": self.view_count,
            "like_count": self.like_count,
            "comment_count": self.comment_count,
            "business_unit": "Podcast",
        }


@dataclass
class YouTubeVideoAnalytics:
    video_id: str
    period_date: date
    views: int
    estimated_minutes_watched: float
    likes: int
    comments: int
    shares: int
    average_view_duration_seconds: float
    average_view_percentage: float
    subscribers_gained: int
    subscribers_lost: int

    def to_row(self) -> dict:
        return {
            "video_id": self.video_id,
            "period_date": self.period_date.isoformat(),
            "views": self.views,
            "estimated_minutes_watched": self.estimated_minutes_watched,
            "likes": self.likes,
            "comments": self.comments,
            "shares": self.shares,
            "average_view_duration_seconds": self.average_view_duration_seconds,
            "average_view_percentage": self.average_view_percentage,
            "subscribers_gained": self.subscribers_gained,
            "subscribers_lost": self.subscribers_lost,
            "business_unit": "Podcast",
        }


@dataclass
class YouTubeTrafficSource:
    video_id: str
    period_date: date
    traffic_source_type: str
    views: int
    estimated_minutes_watched: float

    def to_row(self) -> dict:
        return {
            "video_id": self.video_id,
            "period_date": self.period_date.isoformat(),
            "traffic_source_type": self.traffic_source_type,
            "views": self.views,
            "estimated_minutes_watched": self.estimated_minutes_watched,
            "business_unit": "Podcast",
        }



def _validate_credentials_not_empty(require_oauth: bool = False) -> None:
    """
    Same real bug class already fixed for TikTok and Airtable: a
    GitHub Secret (or a blank line in .env) can exist but hold an
    EMPTY string, not be genuinely missing. os.environ.get("X") --
    what this module uses -- returns that empty string silently, so a
    blank YOUTUBE_API_KEY doesn't fail here; it produces a confusing,
    indirect Google error two calls later ("Method doesn't allow
    unregistered callers... without established identity") that looks
    like an API-not-enabled problem rather than what it actually is.

    require_oauth=True also checks the three OAuth credentials, since
    fetch_video_stats() only needs the API key but
    fetch_video_analytics() needs the OAuth trio -- checking both
    upfront in run() surfaces every real problem at once, not one
    per failed run.
    """
    required = [
        ("YOUTUBE_API_KEY", YOUTUBE_API_KEY),
        ("YOUTUBE_CHANNEL_ID", YOUTUBE_CHANNEL_ID),
    ]
    if require_oauth:
        required += [
            ("YOUTUBE_OAUTH_CLIENT_ID", YOUTUBE_OAUTH_CLIENT_ID),
            ("YOUTUBE_OAUTH_CLIENT_SECRET", YOUTUBE_OAUTH_CLIENT_SECRET),
            ("YOUTUBE_OAUTH_REFRESH_TOKEN", YOUTUBE_OAUTH_REFRESH_TOKEN),
        ]
    missing_or_empty = [name for name, value in required if not value]
    if missing_or_empty:
        raise RuntimeError(
            f"The following YouTube environment variable(s) are missing or empty: "
            f"{missing_or_empty}. This usually means a GitHub Secret exists but was "
            f"never actually given a real value -- go to Settings -> Secrets and "
            f"variables -> Actions, open each one listed above, and re-enter the "
            f"real value (GitHub never shows existing secret values, so re-saving "
            f"is the only way to confirm/fix one that's blank)."
        )


def _get_uploads_playlist_id() -> str:
    """The channel's real video list lives in a special 'uploads'
    playlist, not fetched directly from the channel resource -- this is
    the standard, confirmed YouTube Data API pattern for listing a
    channel's videos."""
    resp = requests.get(
        f"{DATA_API_BASE}/channels",
        params={"part": "contentDetails", "id": YOUTUBE_CHANNEL_ID, "key": YOUTUBE_API_KEY},
    )
    if resp.status_code >= 400:
        # Surfaces Google's real, detailed reason (e.g.
        # "accessNotConfigured" if the Data API isn't enabled for this
        # project, "keyInvalid" if the key itself is wrong/restricted
        # incorrectly) -- resp.raise_for_status() alone only gives the
        # generic status text, not this real detail.
        raise requests.HTTPError(f"{resp.status_code} error from YouTube Data API: {resp.text}")
    data = resp.json()
    items = data.get("items", [])
    if not items:
        raise RuntimeError(f"No channel found for ID {YOUTUBE_CHANNEL_ID!r} -- check the channel ID is correct")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def fetch_video_stats(max_videos: int = 50) -> list[YouTubeVideoStats]:
    """Data API v3 -- public video stats (views/likes/comments). No OAuth
    needed, just the API key.

    REAL GAP FOUND in review (Sep 2026): this function had zero error
    handling, unlike fetch_video_analytics() which isolates failures
    per-video. A single failed call anywhere (quota exceeded, rate
    limit, transient network error) would crash the whole function and
    lose every video's data, not just one. Fixed to fail gracefully at
    each stage and return whatever was successfully collected, matching
    the resilience pattern used throughout this project (e.g.
    fetch_all_mentions isolating one platform's failure from the rest)."""
    try:
        uploads_playlist_id = _get_uploads_playlist_id()
    except (requests.HTTPError, requests.ConnectionError) as e:
        # Transient/API-level failures (quota, network) -- fail gracefully.
        # Deliberately does NOT catch RuntimeError here: a "channel not
        # found" error means the CHANNEL_ID is misconfigured, which is
        # worth surfacing loudly and immediately, not silently swallowing
        # into an empty result the way a transient failure should be.
        print(f"[youtube] Could not resolve uploads playlist -- aborting: {type(e).__name__}: {e}")
        return []

    video_ids = []
    page_token = None
    while len(video_ids) < max_videos:
        params = {
            "part": "contentDetails",
            "playlistId": uploads_playlist_id,
            "maxResults": min(50, max_videos - len(video_ids)),
            "key": YOUTUBE_API_KEY,
        }
        if page_token:
            params["pageToken"] = page_token

        try:
            resp = requests.get(f"{DATA_API_BASE}/playlistItems", params=params)
            resp.raise_for_status()
        except (requests.HTTPError, requests.ConnectionError) as e:
            print(f"[youtube] playlistItems fetch failed -- stopping pagination, keeping {len(video_ids)} video(s) already found: {type(e).__name__}: {e}")
            break

        data = resp.json()
        video_ids.extend(item["contentDetails"]["videoId"] for item in data.get("items", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break

    if not video_ids:
        return []

    records = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        try:
            resp = requests.get(
                f"{DATA_API_BASE}/videos",
                params={"part": "snippet,statistics", "id": ",".join(batch), "key": YOUTUBE_API_KEY},
            )
            resp.raise_for_status()
        except (requests.HTTPError, requests.ConnectionError) as e:
            print(f"[youtube] videos.list batch failed -- skipping this batch of {len(batch)}, continuing with others: {type(e).__name__}: {e}")
            continue

        for item in resp.json().get("items", []):
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            try:
                published = datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00")).date()
            except (ValueError, KeyError):
                try:
                    published = date.fromisoformat(snippet.get("publishedAt", "1970-01-01")[:10])
                except ValueError:
                    # REAL GAP FOUND in review: the fallback itself had
                    # no protection -- a genuinely malformed date string
                    # would still crash the whole batch. Now falls back
                    # to a clearly-flagged sentinel date rather than
                    # crashing, so one bad record doesn't lose the rest.
                    print(f"[youtube] video {item.get('id', '?')}: unparseable publishedAt {snippet.get('publishedAt')!r}, using sentinel date")
                    published = date(1970, 1, 1)

            records.append(
                YouTubeVideoStats(
                    video_id=item["id"],
                    title=snippet.get("title", ""),
                    published_at=published,
                    view_count=int(stats.get("viewCount", 0)),
                    like_count=int(stats.get("likeCount", 0)),
                    comment_count=int(stats.get("commentCount", 0)),
                )
            )

    return records


def _get_oauth_access_token() -> str:
    """Exchanges the long-lived refresh token for a short-lived access
    token -- standard OAuth 2.0 pattern, required for every Analytics API
    call since access tokens expire (~1 hour).

    REAL GAP FOUND in review (Sep 2026): no error handling here meant a
    revoked/expired refresh token (a real, plausible failure mode --
    password changes, Google security reviews) would raise a raw,
    unhelpful HTTP error. Now raises a clear, actionable message
    matching the pattern already used for TikTok's credential
    validation elsewhere in this project."""
    resp = requests.post(
        OAUTH_TOKEN_URL,
        data={
            "client_id": YOUTUBE_OAUTH_CLIENT_ID,
            "client_secret": YOUTUBE_OAUTH_CLIENT_SECRET,
            "refresh_token": YOUTUBE_OAUTH_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        },
    )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"YouTube OAuth token refresh failed ({resp.status_code}): {resp.text}. "
            "This usually means the refresh token was revoked (a Google password "
            "change or security review can do this) -- the OAuth consent flow "
            "needs to be redone by the channel owner to get a new refresh token."
        )
    return resp.json()["access_token"]


def fetch_video_analytics(video_ids: list[str], start_date: date, end_date: date) -> list[YouTubeVideoAnalytics]:
    """Analytics API -- retention, watch time, subscriber attribution.
    Requires OAuth (see module docstring) -- an API key alone cannot
    access this, since it's private, owner-only data.

    Expanded (Sep 23 2026) from the original 3 metrics to the real,
    confirmed core video-report metric set: views, estimatedMinutesWatched,
    likes, comments, shares, subscribersGained, subscribersLost, plus the
    original averageViewDuration/averageViewPercentage -- confirmed real
    field names from Google's own Analytics API metrics documentation."""
    access_token = _get_oauth_access_token()
    records = []

    METRICS = ("views,estimatedMinutesWatched,likes,comments,shares,"
               "averageViewDuration,averageViewPercentage,subscribersGained,subscribersLost")

    for video_id in video_ids:
        resp = requests.get(
            f"{ANALYTICS_API_BASE}/reports",
            headers={"Authorization": f"Bearer {access_token}"},
            params={
                "ids": f"channel=={YOUTUBE_CHANNEL_ID}",
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "metrics": METRICS,
                "filters": f"video=={video_id}",
            },
        )
        if resp.status_code >= 400:
            print(f"[youtube] Analytics fetch failed for video {video_id}: {resp.status_code} {resp.text}")
            continue

        data = resp.json()
        rows = data.get("rows", [])
        if not rows:
            continue

        views, est_minutes, likes, comments, shares, avg_duration, avg_pct, subs_gained, subs_lost = rows[0]
        records.append(
            YouTubeVideoAnalytics(
                video_id=video_id,
                period_date=end_date,
                views=int(views),
                estimated_minutes_watched=float(est_minutes),
                likes=int(likes),
                comments=int(comments),
                shares=int(shares),
                average_view_duration_seconds=float(avg_duration),
                average_view_percentage=float(avg_pct),
                subscribers_gained=int(subs_gained),
                subscribers_lost=int(subs_lost),
            )
        )

    return records


def fetch_traffic_sources(video_ids: list[str], start_date: date, end_date: date) -> list[YouTubeTrafficSource]:
    """Real, confirmed traffic source breakdown -- the actual original
    motivation for building OAuth in the first place, per this module's
    own docstring ('retention curves, traffic sources'). Confirmed real
    query pattern from Google's own Analytics API sample requests:
    dimensions=insightTrafficSourceType, metrics=views,estimatedMinutesWatched.

    One real API call per video (the video filter + this dimension
    together return one row per traffic-source-type for that video),
    same per-video-loop pattern as fetch_video_analytics()."""
    access_token = _get_oauth_access_token()
    records = []

    for video_id in video_ids:
        resp = requests.get(
            f"{ANALYTICS_API_BASE}/reports",
            headers={"Authorization": f"Bearer {access_token}"},
            params={
                "ids": f"channel=={YOUTUBE_CHANNEL_ID}",
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "metrics": "views,estimatedMinutesWatched",
                "dimensions": "insightTrafficSourceType",
                "filters": f"video=={video_id}",
                "sort": "-views",
            },
        )
        if resp.status_code >= 400:
            print(f"[youtube] Traffic source fetch failed for video {video_id}: {resp.status_code} {resp.text}")
            continue

        for row in resp.json().get("rows", []):
            source_type, views, est_minutes = row
            records.append(
                YouTubeTrafficSource(
                    video_id=video_id,
                    period_date=end_date,
                    traffic_source_type=source_type,
                    views=int(views),
                    estimated_minutes_watched=float(est_minutes),
                )
            )

    return records



def run() -> int:
    """
    REAL, SIGNIFICANT GAP FOUND (Sep 23 2026): this connector had never
    actually been wired into a runnable entry point. Every function
    above was built, individually hardened, and individually tested --
    but nothing ever assembled them into a complete run(), and there
    was no `if __name__ == "__main__":` block at all. Running
    `python youtube_connector.py` directly therefore defined a set of
    functions and exited silently with zero output -- not a bug in any
    one function, just a genuinely missing orchestration layer this
    project never finished. The two target tables
    (youtube_video_stats, youtube_video_analytics) didn't exist in
    Supabase either, confirming this had never actually run end-to-end
    before.

    Real orchestration: pull public stats for the channel's videos
    first (gives us the real video_id list), then pull private
    Analytics data for those same videos over a real, recent window --
    the last 7 days, matching this connector's own real data-retention
    reality (Analytics data is most meaningful recent-first; pulling a
    full historical range on every run would be real, unnecessary API
    load for data that mostly doesn't change once a video ages).
    """
    from datetime import timedelta
    from writer import upsert_rows

    _validate_credentials_not_empty(require_oauth=True)

    stats_records = fetch_video_stats()
    stats_written = upsert_rows("youtube_video_stats", [r.to_row() for r in stats_records]) if stats_records else 0
    print(f"[youtube] Video stats: {stats_written} row(s) written.")

    if not stats_records:
        print("[youtube] No video stats -- skipping Analytics fetch (no video_ids to query).")
        return stats_written

    video_ids = [r.video_id for r in stats_records]
    end_date = date.today()
    start_date = end_date - timedelta(days=7)

    try:
        analytics_records = fetch_video_analytics(video_ids, start_date, end_date)
    except RuntimeError as e:
        # A revoked/expired refresh token is a real, actionable
        # condition (per _get_oauth_access_token()'s own error
        # message) -- surface it clearly but don't let it wipe out the
        # real stats data already written above.
        print(f"[youtube] Analytics fetch failed, but stats were already written: {e}")
        return stats_written

    analytics_written = upsert_rows("youtube_video_analytics", [r.to_row() for r in analytics_records]) if analytics_records else 0
    print(f"[youtube] Video analytics: {analytics_written} row(s) written.")

    try:
        traffic_records = fetch_traffic_sources(video_ids, start_date, end_date)
        traffic_written = upsert_rows("youtube_traffic_sources", [r.to_row() for r in traffic_records]) if traffic_records else 0
        print(f"[youtube] Traffic sources: {traffic_written} row(s) written.")
    except RuntimeError as e:
        # Same real reasoning as the analytics try/except above -- a
        # revoked token here shouldn't wipe out real data already
        # written for stats and analytics.
        print(f"[youtube] Traffic source fetch failed, but stats/analytics were already written: {e}")
        traffic_written = 0

    return stats_written + analytics_written + traffic_written


if __name__ == "__main__":
    count = run()
    print(f"YouTube connector: upserted {count} total rows.")
