"""
xpoz_connector.py — Earned-mentions tracking via Xpoz's free tier.

REBUILT (Sep 2026) after the first version failed against the real API --
a real, important lesson worth keeping visible: the first version was
built from marketing pages and SDK usage snippets, and guessed a plain
REST model (GET /v1/{platform}/search). A real run against the live
service returned 404s across all four platforms -- "Cannot GET
/v1/twitter/search", a generic Express 404, confirming the guessed
route didn't exist.

Rather than guess a second time, the actual installed `xpoz` package
(pip install xpoz) was inspected directly -- real source code, not
docs. This revealed the guess was wrong at the architecture level, not
just the URL: the core namespaces (twitter, instagram, tiktok, reddit)
route through an MCP-based tool-call-and-poll transport
(_call_and_maybe_poll), not plain synchronous REST. Only a separate,
narrower feature (instagram_live) uses plain REST. This connector now
uses the real, official XpozClient SDK directly rather than hand-rolled
HTTP calls, so it inherits the correct transport automatically.

Confirmed real facts used below (from actual installed source, not
assumed):
  - `pip install xpoz` is the real package (0.7.9 at time of writing).
  - Auth: XpozClient(api_key=...) or XPOZ_API_KEY env var.
  - All four platforms share a consistent method name: search_posts(query).
  - Returns a PaginatedResult with a real `.data` list of typed Pydantic
    models (e.g. TwitterPost: id, text, author_username, like_count,
    retweet_count, hashtags, mentions, ... — real fields, not guessed).
  - A SEPARATE `tracking` namespace exists (get_tracked_items,
    add_tracked_items) for the dashboard-configured tracked-item
    concept — distinct from the ad-hoc search_posts() used here. Real
    free-tier limit (1 tracked item) applies to `tracking`, not to
    search_posts() calls directly, though real usage limits on
    search_posts() itself haven't been confirmed by a live call yet.

STILL NOT LIVE-VERIFIED: this rebuild is grounded in real source code,
which is much higher confidence than the first attempt, but has not
itself been run against the live API yet. Treat the first real run's
output as the actual confirmation, same as everything else new in this
project.
"""

import os
from dataclasses import dataclass
from datetime import date
from dotenv import load_dotenv, find_dotenv

# REAL BUG, confirmed against a live run on Shahzad's machine: this file
# never loaded the .env at all, so XPOZ_API_KEY read as None even when
# correctly set in .env -- same class of bug already fixed once in
# db.py. find_dotenv(usecwd=True) searches from the actual working
# directory, unlike plain load_dotenv() which can silently fail to find
# .env when called several imports deep.
load_dotenv(find_dotenv(usecwd=True))

try:
    from xpoz import XpozClient
except ImportError:
    raise ImportError(
        "The 'xpoz' package isn't installed. Run: pip install xpoz --break-system-packages"
    )

XPOZ_API_KEY = os.environ.get("XPOZ_API_KEY")

# Confirmed real platforms, each with a real, consistent search_posts()
# method on the official SDK. YouTube deliberately excluded -- already
# covered by youtube_connector.py and Podstock.
TRACKED_PLATFORMS = ["twitter", "instagram", "tiktok", "reddit"]


@dataclass
class EarnedMention:
    """
    Normalized shape across all four platforms -- each has genuinely
    different field names for the same concepts (confirmed via real
    installed Pydantic model source, not guessed):
      - content text: Twitter='text', Instagram='caption',
        TikTok='description', Reddit='title'+'selftext' (combined)
      - author: Twitter/Reddit='author_username', Instagram/TikTok='username'
      - share-equivalent: retweet_count / reshare_count / forward_count /
        crossposts_count -- four different names for a related-but-not-
        identical concept per platform; stored as one normalized field
        since cross-platform comparison needs a common column, with the
        platform-specific nuance accepted as a real, known simplification.
    """
    platform: str
    post_id: str
    author: str
    content_text: str
    url: str | None
    like_count: int
    comment_count: int
    share_count: int
    keyword_matched: str
    fetched_at: date

    def to_row(self) -> dict:
        return {
            "platform": self.platform,
            "post_id": self.post_id,
            "author": self.author,
            "content_text": self.content_text,
            "url": self.url,
            "like_count": self.like_count,
            "comment_count": self.comment_count,
            "share_count": self.share_count,
            "keyword_matched": self.keyword_matched,
            "fetched_at": self.fetched_at.isoformat(),
        }


def _normalize_twitter(raw: dict, keyword: str) -> EarnedMention:
    post_id = raw.get("id") or ""
    return EarnedMention(
        platform="twitter",
        post_id=post_id,
        author=raw.get("author_username") or "",
        content_text=raw.get("text") or "",
        url=f"https://x.com/{raw.get('author_username')}/status/{post_id}" if raw.get("author_username") and post_id else None,
        like_count=raw.get("like_count") or 0,
        comment_count=raw.get("reply_count") or 0,
        share_count=raw.get("retweet_count") or 0,
        keyword_matched=keyword,
        fetched_at=date.today(),
    )


def _normalize_instagram(raw: dict, keyword: str) -> EarnedMention:
    return EarnedMention(
        platform="instagram",
        post_id=raw.get("id") or "",
        author=raw.get("username") or "",
        content_text=raw.get("caption") or "",
        url=raw.get("code_url"),
        like_count=raw.get("like_count") or 0,
        comment_count=raw.get("comment_count") or 0,
        share_count=raw.get("reshare_count") or 0,
        keyword_matched=keyword,
        fetched_at=date.today(),
    )


def _normalize_tiktok(raw: dict, keyword: str) -> EarnedMention:
    return EarnedMention(
        platform="tiktok",
        post_id=raw.get("id") or "",
        author=raw.get("username") or "",
        content_text=raw.get("description") or "",
        url=None,
        like_count=raw.get("like_count") or 0,
        comment_count=raw.get("comment_count") or 0,
        share_count=raw.get("forward_count") or 0,
        keyword_matched=keyword,
        fetched_at=date.today(),
    )


def _normalize_reddit(raw: dict, keyword: str) -> EarnedMention:
    title = raw.get("title") or ""
    selftext = raw.get("selftext") or ""
    combined = f"{title}: {selftext}" if title and selftext else (title or selftext)
    return EarnedMention(
        platform="reddit",
        post_id=raw.get("id") or "",
        author=raw.get("author_username") or "",
        content_text=combined,
        url=f"https://reddit.com{raw['permalink']}" if raw.get("permalink") else raw.get("url"),
        like_count=raw.get("score") or raw.get("upvotes") or 0,
        comment_count=raw.get("comments_count") or 0,
        share_count=raw.get("crossposts_count") or 0,
        keyword_matched=keyword,
        fetched_at=date.today(),
    )


_NORMALIZERS = {
    "twitter": _normalize_twitter,
    "instagram": _normalize_instagram,
    "tiktok": _normalize_tiktok,
    "reddit": _normalize_reddit,
}


def normalize_mentions(raw_results: dict[str, list[dict]], keyword: str) -> list[EarnedMention]:
    """Converts the raw per-platform dicts from fetch_all_mentions() into
    one normalized list ready for Supabase, using the confirmed real
    field mapping per platform above."""
    mentions = []
    for platform, raw_list in raw_results.items():
        normalizer = _NORMALIZERS.get(platform)
        if not normalizer:
            continue
        for raw in raw_list:
            mentions.append(normalizer(raw, keyword))
    return mentions


# REAL FINDING, confirmed against a live run: every mention returned
# like_count=0, even genuine high-engagement content (real Forbes
# coverage). Traced through the actual SDK source: when fields=None
# (the default, used by the first working version), it's passed
# straight through as None to the server -- meaning the SERVER decides
# what fields to return by default, which isn't visible from client
# code. Rather than guess whether that server default excludes
# engagement metrics, explicitly requesting exactly the fields each
# normalizer needs removes the ambiguity entirely. All fields below
# confirmed present in the real installed package's allowed-fields
# lists for each platform's search_posts method.
_REQUESTED_FIELDS = {
    "twitter": ["id", "text", "author_username", "like_count", "retweet_count", "reply_count"],
    "instagram": ["id", "caption", "username", "like_count", "comment_count", "reshare_count", "code_url"],
    "tiktok": ["id", "description", "username", "like_count", "comment_count", "forward_count"],
    "reddit": ["id", "title", "selftext", "author_username", "score", "comments_count", "permalink", "crossposts_count"],
}


def search_mentions(keyword: str, platform: str, limit: int = 100) -> list[dict]:
    """
    Searches one platform for real mentions of a keyword, using the real
    official SDK's confirmed search_posts() method rather than a
    hand-rolled HTTP call. Returns raw dicts (Pydantic .model_dump())
    rather than a typed dataclass, since the exact fields worth keeping
    long-term haven't been decided yet -- easy to narrow down once a
    real response is seen.

    REAL BUG, confirmed against a live run: an unquoted multi-word query
    ("Dani Austin") was NOT treated as a connected phrase -- it matched
    "Dani" and "Austin" independently, returning noise (unrelated posts
    about someone else named Dani, or about Austin the city). Confirmed
    via Xpoz's own TypeScript SDK docs (same backend, same query engine
    as this Python SDK): exact-phrase matching requires wrapping the
    phrase in double quotes, e.g. searchPosts('"artificial
    intelligence" AND ethics', ...). Fixed here by quoting any
    multi-word keyword automatically, rather than relying on the caller
    to remember to do it.

    REAL FINDING, confirmed via Xpoz's own official docs (docs.xpoz.ai):
    "Server-side pagination for large result sets (100 items per page)"
    -- the server caps each page at 100 regardless of what `limit` is
    requested. Passing limit=1000 to a single search_posts() call would
    NOT return 1000 items; it silently returns at most 100 in
    result.data. This function actually paginates (calling
    .next_page() as needed) to reach the real requested total, rather
    than trusting the `limit` parameter alone to do it.
    """
    if platform not in TRACKED_PLATFORMS:
        raise ValueError(f"'{platform}' not a confirmed Xpoz-covered platform. Use one of: {TRACKED_PLATFORMS}")

    query = f'"{keyword}"' if " " in keyword and not keyword.startswith('"') else keyword

    with XpozClient(api_key=XPOZ_API_KEY) as client:
        namespace = getattr(client, platform)
        try:
            result = namespace.search_posts(query, limit=limit, fields=_REQUESTED_FIELDS[platform])
        except Exception as e:
            print(f"[xpoz] '{platform}' search FAILED: {type(e).__name__}: {e}")
            return []

        items = list(result.data)
        page = result
        # Confirmed real cap: 100/page server-side. Keep pulling pages
        # until either the real requested limit is reached or the
        # server reports no more pages -- whichever comes first.
        while len(items) < limit and page.has_next_page():
            try:
                page = page.next_page()
            except Exception as e:
                print(f"[xpoz] '{platform}' pagination stopped early: {type(e).__name__}: {e}")
                break
            items.extend(page.data)

        return [item.model_dump() for item in items[:limit]]


def fetch_all_mentions(keyword: str = "Dani Austin", limit_per_platform: int = 1000) -> dict[str, list[dict]]:
    """
    Searches all four confirmed platforms for one keyword. Isolates
    failures per platform -- same reasoning as everywhere else in this
    project: one platform's API hiccup shouldn't cost the others.
    """
    results = {}
    for platform in TRACKED_PLATFORMS:
        mentions = search_mentions(keyword, platform, limit_per_platform)
        results[platform] = mentions
        print(f"[xpoz] '{platform}': {len(mentions)} mention(s) for {keyword!r}")

    return results


def get_tracked_items() -> list[dict]:
    """
    The SEPARATE dashboard-configured tracking feature (distinct from
    ad-hoc search_posts() above). Useful to confirm what's actually
    configured -- e.g. Shahzad added "Dani Austin" as a Twitter keyword
    directly in the Xpoz dashboard, which this can verify.
    """
    with XpozClient(api_key=XPOZ_API_KEY) as client:
        items = client.tracking.get_tracked_items()
        return [item.model_dump() if hasattr(item, "model_dump") else item for item in items]


# Default keyword tracked for the Dani Austin project.
#
# SCHEDULING NOTE: run() is NOT in run_all.py's daily CONNECTORS list --
# deliberately moved out to its own weekly workflow
# (.github/workflows/xpoz-weekly-sync.yml), matching the same pattern
# post-level-sync.yml already uses for a different-than-daily cadence.
# Real budget math, confirmed: at 1000/platform, a single run uses
# 1000 x 4 = 4,000 of the 100,000/month free-tier budget. Weekly
# (~4.33 runs/month average, up to 5 in months with 5 occurrences of
# that weekday) costs 17,320-20,000/month -- confirmed to land at
# ~17-20% of the monthly cap, hitting the requested "keep usage to
# ~20%" target while restoring the original 1000/platform depth that
# had to be scaled back to 800 when this ran daily.
DEFAULT_KEYWORD = "Dani Austin"


def run() -> int:
    """
    Scheduled entry point, matching the (name, run_fn) -> int pattern
    every other connector in run_all.py follows. Fetches real mentions,
    normalizes them, and writes to Supabase -- same fetch/normalize
    logic as run_xpoz_mentions.py, exposed here so it can run on the
    daily schedule rather than only manually.
    """
    from writer import upsert_rows

    results = fetch_all_mentions(DEFAULT_KEYWORD)
    mentions = normalize_mentions(results, DEFAULT_KEYWORD)
    return upsert_rows("earned_mentions", [m.to_row() for m in mentions])
