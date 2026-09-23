"""
megaphone_connector.py — Real per-episode metadata from Megaphone,
Dani Austin's actual podcast host. Confirmed working (Sep 2026) against
a real live response after resolving a real 403 permissions error
(the API token belonged to an account without access to this specific
network -- fixed by using a token from an account that actually
administers it).

REAL, IMPORTANT LIMITATION, confirmed by inspecting every field name in
the actual response: this endpoint returns rich episode METADATA
(title, publish date, ad cuepoints, Spotify/RSS status) but NO
download/play/listen counts anywhere. The original motivation for this
connector -- "Megaphone would be the authoritative, clean source for
true per-episode downloads" -- is NOT satisfied by this endpoint alone.
Real per-episode performance numbers likely live behind a separate
Megaphone analytics/metrics endpoint that hasn't been discovered yet.

What IS genuinely valuable here, confirmed from the real response:
real ad cuepoint data (insertion points, ad count, ad sources) --
this is real, structured sponsor-insertion data distinct from anything
Podstock's browser-scrape currently provides, and could meaningfully
improve on `podcast_ad_bookings`'s current manual-pull approach.
"""

import os
from datetime import date, datetime
from dataclasses import dataclass
import requests
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(usecwd=True))

MEGAPHONE_API_TOKEN = os.environ["MEGAPHONE_API_TOKEN"]
MEGAPHONE_NETWORK_ID = os.environ["MEGAPHONE_NETWORK_ID"]
MEGAPHONE_PODCAST_ID = os.environ["MEGAPHONE_PODCAST_ID"]
BASE_URL = "https://cms.megaphone.fm/api"


@dataclass
class MegaphoneEpisode:
    episode_id: str
    title: str
    pubdate: date
    duration_seconds: float
    episode_number: int | None
    season_number: int | None
    status: str
    spotify_status: str
    rss_status: str
    ad_count: int  # real, confirmed from cuepoints -- not download data,
    # but a genuine, structured signal of sponsor insertion volume

    def to_row(self) -> dict:
        return {
            "episode_id": self.episode_id,
            "title": self.title,
            "pubdate": self.pubdate.isoformat(),
            "duration_seconds": self.duration_seconds,
            "episode_number": self.episode_number,
            "season_number": self.season_number,
            "status": self.status,
            "spotify_status": self.spotify_status,
            "rss_status": self.rss_status,
            "ad_count": self.ad_count,
        }


def fetch_episodes(limit: int = 100) -> list[MegaphoneEpisode]:
    """
    Fetches real episode metadata. Confirmed real response shape via a
    live diagnostic run -- fields used below are all confirmed present,
    not guessed.
    """
    url = f"{BASE_URL}/networks/{MEGAPHONE_NETWORK_ID}/podcasts/{MEGAPHONE_PODCAST_ID}/episodes"

    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Token {MEGAPHONE_API_TOKEN}"},
            params={"limit": limit},
            timeout=30,
        )
    except (requests.Timeout, requests.ConnectionError) as e:
        print(f"[megaphone] Request failed: {type(e).__name__}: {e}")
        return []

    if resp.status_code >= 400:
        print(f"[megaphone] Episodes fetch FAILED ({resp.status_code}): {resp.text}")
        return []

    data = resp.json()
    if not isinstance(data, list):
        print(f"[megaphone] Unexpected response shape (expected a list): {type(data)}")
        return []

    episodes = []
    for item in data:
        try:
            # Confirmed real format: "2026-09-03T05:00:00.000Z" -- has a
            # literal Z suffix (unlike Facebook's "+0000" without a colon,
            # a different real bug already fixed elsewhere in this
            # project), so the standard .replace("Z", "+00:00") approach
            # is correct and sufficient here.
            pubdate = datetime.fromisoformat(item["pubdate"].replace("Z", "+00:00")).date()
        except (ValueError, KeyError, AttributeError):
            print(f"[megaphone] Episode {item.get('id', '?')}: unparseable pubdate {item.get('pubdate')!r}, skipping")
            continue

        try:
            duration = float(item.get("duration", 0) or 0)
        except (ValueError, TypeError):
            duration = 0.0

        cuepoints = item.get("cuepoints", []) or []
        ad_count = sum(cp.get("adCount") or 0 for cp in cuepoints)

        episodes.append(
            MegaphoneEpisode(
                episode_id=item["id"],
                title=item.get("title", ""),
                pubdate=pubdate,
                duration_seconds=duration,
                episode_number=item.get("episodeNumber"),
                season_number=item.get("seasonNumber"),
                status=item.get("status", ""),
                spotify_status=item.get("spotifyStatus", ""),
                rss_status=item.get("rssStatus", ""),
                ad_count=ad_count,
            )
        )

    return episodes


def run() -> int:
    """Scheduled entry point, matching the (name, run_fn) -> int pattern
    every other connector in run_all.py follows."""
    from writer import upsert_rows

    episodes = fetch_episodes()
    if not episodes:
        return 0
    return upsert_rows("podcast_episodes_megaphone", [e.to_row() for e in episodes])


if __name__ == "__main__":
    eps = fetch_episodes()
    print(f"\nFetched {len(eps)} real episode(s).")
    for e in eps[:5]:
        print(f"  {e.pubdate}  {e.title[:60]!r}  ads={e.ad_count}  status={e.status}")
