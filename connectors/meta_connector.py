"""
meta_connector.py — Meta Graph API connector (Instagram Business + Facebook Page).

One OAuth integration covers both platforms since Meta manages Instagram
Business accounts through the same Graph API as Facebook Pages.

Requires (via env vars, sourced from 1Password at run time):
    META_SYSTEM_USER_TOKEN   -- long-lived System User token from Meta
                                 Business Manager (does NOT expire every
                                 60 days like a personal user token — this
                                 is the token type to use for a scheduled,
                                 unattended job)
    META_IG_USER_ID          -- Instagram Business Account ID
    META_PAGE_ID             -- Facebook Page ID

Pinned to Graph API v25.0. Meta ships breaking changes roughly quarterly and
retires versions on a ~2-year clock — confirm this is still current before
each quarter's first run.

PERMISSION NAMES (current as of this build): Meta renamed the Instagram
permission set to an "instagram_business_" prefix. Use:
    instagram_business_basic             (was: instagram_basic)
    instagram_business_manage_insights   (was: instagram_manage_insights)
    pages_show_list
    pages_read_engagement
    business_management
If a Meta dashboard ever shows the old names again, or a third naming
scheme, treat that as a signal to re-check their current docs rather than
assuming which one is current — Meta has changed this naming at least once
already.

TWO DIFFERENT TOKENS ARE REQUIRED (non-obvious, easy to get wrong):
  - Instagram insights work with the System User token directly.
  - Facebook PAGE Insights require a *Page* access token -- Meta returns
    "(#190) This method must be called with a Page Access Token"
    otherwise. This connector fetches that Page token automatically at
    run time via the Page node's `access_token` field (using the System
    User token to do so), rather than requiring a second token in .env.
    Page tokens derived from a System User token don't expire, so this is
    safe for an unattended scheduled job.

CONFIRMED MISSING PERMISSION (found via Meta's own docs, not inference):
  developers.facebook.com/docs/platforminsights/page/ lists Page Insights
  as requiring BOTH `pages_read_engagement` AND `read_insights` as
  separate permissions. The System User token in this project's setup was
  generated with pages_read_engagement but NOT read_insights -- which is
  almost certainly why every Facebook Page metric returned a confirmed-
  empty `data: []` across a genuinely correct 30-day window on an active
  Page, with no error at all. Meta does not error on a missing permission
  here; it silently returns empty data, which is a materially different
  (and much harder to diagnose) failure mode than the earlier wrong-
  metric-name and wrong-token-type errors, which at least errored loudly.
  Fix: regenerate the System User token with read_insights added.

KNOWN DEPRECATIONS ALREADY HANDLED:
  - Instagram `impressions` deprecated April 2025 -> use `views`.
  - Facebook `page_fans`/`page_impressions` deprecated Nov 2025 for
    reporting actuals; `page_impressions_unique` additionally confirmed
    "Deprecated above Graph API v25" per Meta's own Page Insights
    reference table -- do not use it on this v25.0-pinned connector.
  - Instagram `profile_views` deprecated in Graph API v22.0 -- removed
    entirely (not renamed to something else).
  - Instagram total-value account-level metrics (e.g. `reach`) require an
    explicit `metric_type=total_value` query parameter. CONFIRMED this
    parameter is Instagram-specific -- Meta's own documented Parameters
    list for the Facebook PAGE Insights endpoint does NOT include
    metric_type at all; including it there was an earlier bug, now fixed.
  - `reach` is NOT a valid Facebook Page-level metric name at all (it
    doesn't appear anywhere in Meta's own Page Insights metric table) --
    an earlier version of this code incorrectly carried over Instagram's
    (valid) `reach` metric onto the Facebook Page call. Confirmed valid
    Page metrics used instead: `page_follows`, `page_media_view` (both
    support period=day per Meta's own reference table).

FLAGGED, NOT YET CONFIRMED: Meta announced (Feb 2026) that Page-level
`reach` is being replaced by a new `page_viewer` metric, effective end of
June 2026. This connector still requests `reach` as a fallback alongside
`views` — check Meta's changelog before this rolls fully into production
and swap in `page_viewer` once it's live and documented.
"""

import re
import os
import requests
from datetime import date, datetime, timezone, timedelta

from models import SocialAccount, SocialMetric, SocialDemographic, SocialPost, SocialPostMetric
from writer import upsert_rows

META_SYSTEM_USER_TOKEN = os.environ["META_SYSTEM_USER_TOKEN"]
META_IG_USER_ID = os.environ["META_IG_USER_ID"]
META_PAGE_ID = os.environ["META_PAGE_ID"]

GRAPH_API_VERSION = "v25.0"
GRAPH_BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


def seed_accounts() -> int:
    """social_metrics.account_id has a foreign key to social_accounts —
    register both accounts before the first metrics write."""
    accounts = [
        SocialAccount(platform="instagram", handle="daniaustin", account_id=META_IG_USER_ID, is_core=True),
        SocialAccount(platform="facebook", handle="daniaustin", account_id=META_PAGE_ID, is_core=True),
    ]
    return upsert_rows("social_accounts", [a.to_row() for a in accounts])


def _get(path: str, params: dict, token: str | None = None) -> dict:
    """
    Calls the Graph API. Defaults to the System User token, but accepts an
    override -- Facebook PAGE Insights specifically requires a *Page*
    access token, not a user/system-user token (per Meta's own Page
    Insights requirements: "A Page access token requested by a person who
    can perform the ANALYZE task on the Page"). Instagram insights, by
    contrast, work fine with the System User token.
    """
    params = {**params, "access_token": token or META_SYSTEM_USER_TOKEN}
    resp = requests.get(f"{GRAPH_BASE_URL}/{path}", params=params)
    if resp.status_code >= 400:
        # Meta's error responses almost always include a specific, useful
        # message here (e.g. exactly which metric/param is invalid) --
        # printing it before raising means we see the REAL reason instead
        # of just "400 Bad Request" with no detail.
        print(f"[meta] API error response body: {resp.text}")
    resp.raise_for_status()
    return resp.json()


_page_access_token: str | None = None


def get_page_access_token() -> str:
    """
    Exchanges the System User token for this Page's own access token.

    Meta issues a distinct token per Page, retrievable via the Page node's
    `access_token` field. Page tokens derived from a System User token do
    not expire (unlike ones derived from a short-lived user token), so
    this is safe for an unattended scheduled job -- but it IS fetched
    fresh on every run rather than stored in .env, so a rotated System
    User token automatically yields a working Page token with no manual
    re-copying step.
    """
    global _page_access_token
    if _page_access_token is None:
        data = _get(META_PAGE_ID, {"fields": "access_token"})
        if "access_token" not in data:
            raise RuntimeError(
                f"Could not retrieve a Page access token for page {META_PAGE_ID}. "
                "This usually means the System User doesn't have the ANALYZE task "
                "assigned on this Page -- check Business Settings -> System Users -> "
                "Assign Assets -> the Page -> enable full control / analyze."
            )
        _page_access_token = data["access_token"]
    return _page_access_token


def _parse_insights(payload: dict, account_id: str, today: date, verbose: bool = True) -> list[SocialMetric]:
    """
    Parses an insights response into SocialMetrics, handling BOTH response
    shapes Meta returns:

      1. metric_type=total_value  ->  {"name": "reach", "total_value": {"value": 123}}
      2. default (time series)    ->  {"name": "reach", "values": [{"value": 123, "end_time": ...}]}

    An earlier version of this code only handled shape 2. Because Instagram
    account-level insights REQUIRE metric_type=total_value (shape 1), every
    Instagram insight was silently skipped -- the API was returning the
    numbers correctly and this parser was discarding them, with no error
    to make that visible. Hence: profile metrics landed, insights didn't.
    """
    records = []
    for item in payload.get("data", []):
        metric_name = item.get("name")

        # Shape 1: metric_type=total_value
        total_value = item.get("total_value")
        if isinstance(total_value, dict) and total_value.get("value") is not None:
            records.append(SocialMetric(account_id, metric_name, today, float(total_value["value"])))
            continue

        # Shape 2: time-series values array -- take the most recent point
        values = item.get("values") or []
        if values and values[-1].get("value") is not None:
            records.append(SocialMetric(account_id, metric_name, today, float(values[-1]["value"])))
            continue

        if verbose:
            print(f"[meta] WARNING: metric '{metric_name}' returned no usable value.")

    return records


def _fetch_metrics_resilient(
    path: str,
    metrics: list[str],
    base_params: dict,
    account_id: str,
    today: date,
    token: str | None = None,
) -> list[SocialMetric]:
    """
    Fetches a list of metrics, tolerating individual metric failures.

    Why this exists: Meta deprecates Page/IG insight metrics on a rolling
    basis (a Page Insights deprecation wave landed June 15, 2026), and a
    single invalid metric name causes the ENTIRE batch request to fail with
    "(#100) The value must be a valid insights metric" -- taking down every
    other valid metric in the same call. That failure mode cost several
    debugging cycles on this connector already.

    Strategy: try the efficient batch call first; if it fails OR returns
    nothing, retry each metric individually so valid metrics still land and
    invalid ones are named explicitly in the logs rather than silently
    taking everything else down with them.
    """
    # Fast path: one batched request.
    try:
        payload = _get(path, {**base_params, "metric": ",".join(metrics)}, token=token)
        records = _parse_insights(payload, account_id, today, verbose=False)
        if records:
            # A successful batch can still SILENTLY OMIT individual metrics --
            # Meta drops metrics it won't serve rather than erroring, exactly
            # like QuickBooks drops unrecognized report columns. Without this
            # check, a requested metric can vanish with no trace at all: it
            # isn't in the data, and the fallback path that logs failures
            # never runs because the batch "succeeded". This is precisely how
            # `follows_and_unfollows` was requested for weeks while never
            # appearing in the database and never producing a warning.
            returned = {r.metric for r in records}
            omitted = [m for m in metrics if m not in returned]
            if omitted:
                print(f"[meta] NOTE: {path} returned data, but silently omitted: {omitted}")
                print(f"[meta]   (requested but absent from an otherwise-successful response -- "
                      f"Meta drops metrics it won't serve rather than erroring)")
            return records
        print(f"[meta] Batch returned no data for {path}; retrying per-metric to isolate.")
    except requests.HTTPError:
        print(f"[meta] Batch request failed for {path}; retrying per-metric to isolate.")

    # Slow path: isolate each metric so one bad name can't kill the rest.
    records = []
    for metric in metrics:
        try:
            payload = _get(path, {**base_params, "metric": metric}, token=token)
            parsed = _parse_insights(payload, account_id, today, verbose=False)
            if parsed:
                records.extend(parsed)
            else:
                # Full raw payload, not a summary -- if a page is genuinely
                # active but this still shows empty, the raw structure is
                # what tells us whether it's really data:[] or something
                # else being missed (e.g. an unexpected key, a permissions
                # note buried in the response, pagination).
                print(f"[meta]   '{metric}': valid, but no data returned. Raw payload: {payload}")
        except requests.HTTPError:
            print(f"[meta]   '{metric}': REJECTED by API (likely deprecated or unavailable for this account).")
    return records


# Instagram account-level insight metrics, confirmed available.
# NOTE: only `reach` supports time-series; every other metric here is
# total_value-only (an Instagram Graph API limitation, not ours) -- which
# is why metric_type=total_value is set for the whole set.
# Deprecated in v22.0 and deliberately NOT included: impressions,
# profile_views, website_clicks, email_contacts, phone_call_clicks,
# text_message_clicks, get_directions_clicks.
IG_INSIGHT_METRICS = [
    "reach",
    "views",
    "accounts_engaged",
    "total_interactions",
    "likes",
    "comments",
    "shares",
    "saves",
    "replies",
    "follows_and_unfollows",
    "profile_links_taps",
]

# Facebook Page metrics. IMPORTANT -- this list is based on what the LIVE
# API actually accepts, which differs from Meta's published reference table.
#
# Meta's docs table (developers.facebook.com/docs/graph-api/reference/
# insights/) still lists page_impressions, page_impressions_unique, and
# page_fans without any deprecation marker. The live API rejects all three
# with "(#100) The value must be a valid insights metric" -- they were
# removed by the Page Insights deprecation wave dated June 15, 2026, and
# the docs table simply hasn't been updated. Empirical behavior wins over
# the published table; they are excluded here and should NOT be re-added
# on the basis of the docs alone.
#
# Also still true: `reach` is NOT a valid Page-level metric name, and
# metric_type is NOT a valid Page Insights parameter (Instagram-only).
#
# The metrics below are all accepted by the live API. An earlier run
# returned EMPTY for all of them, and this file previously concluded the
# Page was likely dormant -- Jordan has since confirmed the Page IS
# actually active, which means that conclusion was probably wrong. Under
# investigation: since/until format (Unix timestamp -> date string, just
# changed) and full raw-payload logging have been added to
# _fetch_metrics_resilient to get a definitive answer rather than guess
# further. Do not re-assume "dormant" until that's actually ruled out.
FB_INSIGHT_METRICS = [
    "page_follows",
    "page_post_engagements",
    "page_views_total",
    "page_daily_follows_unique",
    "page_video_views",
    "page_media_view",
    "page_total_actions",
]


def fetch_instagram_metrics() -> list[SocialMetric]:
    today = date.today()
    records = []

    # Followers + post count (account fields, not insights -- follower_count
    # was removed from the /insights endpoint in v22+, so this is the only
    # reliable source for it).
    profile = _get(META_IG_USER_ID, {"fields": "followers_count,media_count"})
    if "followers_count" in profile:
        records.append(SocialMetric(META_IG_USER_ID, "followers", today, float(profile["followers_count"])))
    if "media_count" in profile:
        records.append(SocialMetric(META_IG_USER_ID, "posts", today, float(profile["media_count"])))

    records.extend(
        _fetch_metrics_resilient(
            f"{META_IG_USER_ID}/insights",
            IG_INSIGHT_METRICS,
            {"period": "day", "metric_type": "total_value"},
            META_IG_USER_ID,
            today,
        )
    )

    return records


def fetch_facebook_metrics() -> list[SocialMetric]:
    today = date.today()
    records = []

    profile = _get(META_PAGE_ID, {"fields": "followers_count"})
    if "followers_count" in profile:
        records.append(SocialMetric(META_PAGE_ID, "followers", today, float(profile["followers_count"])))

    # Page Insights requires a PAGE access token, not the System User token
    # -- Meta returns "(#190) This method must be called with a Page Access
    # Token" otherwise.
    page_token = get_page_access_token()

    # Explicit 30-day window rather than Meta's default. Left to itself,
    # this endpoint queries roughly a 2-day window (confirmed by decoding
    # the paging URLs in an empty response), and Page Insights have a
    # documented ~24h processing delay with once-daily updates -- so a
    # 2-day window can legitimately contain zero settled data points.
    # Meta caps since/until at 90 days per request; 30 is well inside that.
    #
    # CHANGED: since/until now sent as YYYY-MM-DD date strings, not raw
    # Unix timestamps. Both are documented as accepted by Meta in different
    # places, and behavior has been inconsistent across Graph API endpoints
    # historically -- if empty results persist with the Page confirmed
    # active, this format is one of the first things worth re-testing
    # directly in the Graph API Explorer rather than guessing further here.
    until_date = datetime.now(timezone.utc).date()
    since_date = until_date - timedelta(days=30)

    records.extend(
        _fetch_metrics_resilient(
            f"{META_PAGE_ID}/insights",
            FB_INSIGHT_METRICS,
            {"period": "day", "since": since_date.isoformat(), "until": until_date.isoformat()},
            META_PAGE_ID,
            today,
            token=page_token,
        )
    )

    return records


# Instagram audience demographic breakdowns. These use a DIFFERENT request
# shape from ordinary insights: metric_type=total_value plus an explicit
# `breakdown` parameter, and the response nests results under
# total_value.breakdowns[].results[] rather than a flat value.
#
# Requires >=100 followers (DA has ~2.49M, so not a constraint here).
#
# NOTE: `engaged_audience_demographics` is also available and reflects the
# demographics of people who ENGAGED rather than of followers -- arguably
# more useful commercially, but only requested here as `follower_demographics`
# to start. Worth adding once this is confirmed working against real data.
IG_DEMOGRAPHIC_BREAKDOWNS = {
    "age": "age",
    "gender": "gender",
    "country": "country",
    "city": "city",
}


def fetch_instagram_demographics() -> list[SocialDemographic]:
    """
    Fetches follower demographic breakdowns (age, gender, country, city).

    Each breakdown is requested separately rather than batched -- Meta
    returns one breakdown dimension per call for this metric, and batching
    them isn't supported the way it is for ordinary insight metrics.

    Failures are isolated per dimension for the same reason as
    _fetch_metrics_resilient: one unavailable breakdown shouldn't cost us
    the other three.
    """
    today = date.today()
    records: list[SocialDemographic] = []

    for dimension, breakdown_param in IG_DEMOGRAPHIC_BREAKDOWNS.items():
        try:
            payload = _get(
                f"{META_IG_USER_ID}/insights",
                {
                    "metric": "follower_demographics",
                    "period": "lifetime",
                    "metric_type": "total_value",
                    "breakdown": breakdown_param,
                },
            )
        except requests.HTTPError:
            print(f"[meta]   demographics '{dimension}': REJECTED by API -- skipping.")
            continue

        found_any = False
        for item in payload.get("data", []):
            breakdowns = item.get("total_value", {}).get("breakdowns", [])
            for breakdown in breakdowns:
                for result in breakdown.get("results", []):
                    # dimension_values is a list (usually one entry for a
                    # single-dimension breakdown).
                    dim_values = result.get("dimension_values") or []
                    value = result.get("value")
                    if not dim_values or value is None:
                        continue
                    records.append(
                        SocialDemographic(
                            account_id=META_IG_USER_ID,
                            dimension=dimension,
                            dimension_value=str(dim_values[0]),
                            value=float(value),
                            period_date=today,
                        )
                    )
                    found_any = True

        if not found_any:
            print(f"[meta]   demographics '{dimension}': no data returned. Raw payload: {payload}")

    return records


POSTS_PER_PLATFORM_LIMIT = 25

# Per-post metrics, confirmed current (impressions/video_views deprecated
# v22.0 -- do not reintroduce). `follows` and `profile_visits` are the
# highest-value additions: they attribute audience GROWTH to specific posts,
# which is what turns an unexplained follower decline into a diagnosis.
IG_POST_METRICS = ["views", "reach", "likes", "comments", "shares", "saved",
                   "total_interactions", "follows", "profile_visits"]
IG_REEL_EXTRA_METRICS = ["ig_reels_avg_watch_time", "reels_skip_rate"]
# Stories: navigation metrics only exist while the story is live.
IG_STORY_METRICS = ["views", "reach", "replies", "navigation"]

# Facebook post-level. CONFIRMED via a real production run's
# _unsupported_metrics_cache, not speculation: post_impressions_unique and
# post_engaged_users are BOTH rejected at the post level -- consistent with
# post_impressions_unique also being confirmed dead at the account level
# (same pattern, same metric family). Only post_reactions_by_type_total and
# post_clicks actually work. Reduced to just these two so there's no
# per-run discovery cost at all -- not even the one-time cache-learning
# cost, since the in-memory cache resets on every process invocation.
#
# NOTE: post_reactions_by_type_total returns a dict broken out by reaction
# type (like/love/wow/etc), not a scalar -- handled by _parse_post_insights'
# existing dict-flattening logic (the same path built for Stories'
# `navigation`), producing one metric row per reaction type.
FB_POST_METRICS = ["post_reactions_by_type_total", "post_clicks"]


def _parse_post_insights(payload: dict, post_id: str, now: datetime) -> list[SocialPostMetric]:
    """
    Post insights use the time-series `values` shape. `navigation` (Stories)
    returns a dict of sub-types (taps_forward/taps_back/exits) rather than a
    scalar -- those are flattened into separate metrics rather than dropped.
    """
    records = []
    for item in payload.get("data", []):
        name = item.get("name")
        values = item.get("values") or []
        if not values:
            continue
        raw = values[-1].get("value")
        if raw is None:
            continue

        if isinstance(raw, dict):
            # e.g. navigation -> {"taps_forward": 120, "exits": 30}
            for sub_name, sub_value in raw.items():
                if sub_value is not None:
                    records.append(SocialPostMetric(post_id, sub_name, float(sub_value), now))
        else:
            records.append(SocialPostMetric(post_id, name, float(raw), now))
    return records



# Cache of confirmed-unsupported metrics, keyed by media_type. Meta's error
# message names the exact metrics it rejects (e.g. "does not support the
# follows, profile_visits metric for this media product type"). Without
# this cache, EVERY post of a given media type repeats the same doomed
# discovery process from scratch: 1 failed batch call + up to N individual
# fallback calls, even though the answer never changes for that media type.
# This is exactly why a real sync was slow and appeared to "hang" -- not a
# bug, just needless repeated work. Learned once, applied to every
# subsequent post of the same type.
_unsupported_metrics_cache: dict[str, set[str]] = {}


def _extract_unsupported_metrics(error_text: str) -> set[str]:
    """Parses Meta's own error message rather than guessing which metric(s)
    it's complaining about, e.g.:
    '...does not support the follows, profile_visits metric for this...'
    """
    match = re.search(r"does not support the ([\w, ]+?) metric", error_text)
    if not match:
        return set()
    return {m.strip() for m in match.group(1).split(",") if m.strip()}


def _fetch_post_insights(post_id: str, metrics: list[str], now: datetime,
                         token: str | None = None, media_type: str | None = None) -> list[SocialPostMetric]:
    """
    Per-post insights, resilient AND efficient: a metric invalid for this
    media type (common -- Reel-only metrics on an image, say) must not cost
    the others -- but once Meta tells us which metric is invalid for a given
    media type, that's remembered rather than rediscovered on every post.
    """
    cache_key = media_type or "unknown"
    known_bad = _unsupported_metrics_cache.get(cache_key, set())
    effective_metrics = [m for m in metrics if m not in known_bad]
    if not effective_metrics:
        return []

    try:
        payload = _get(f"{post_id}/insights", {"metric": ",".join(effective_metrics)}, token=token)
        return _parse_post_insights(payload, post_id, now)
    except requests.HTTPError as e:
        error_text = e.response.text if e.response is not None else ""
        newly_bad = _extract_unsupported_metrics(error_text)

        if newly_bad:
            _unsupported_metrics_cache.setdefault(cache_key, set()).update(newly_bad)
            remaining = [m for m in effective_metrics if m not in newly_bad]
            if remaining:
                try:
                    payload = _get(f"{post_id}/insights", {"metric": ",".join(remaining)}, token=token)
                    return _parse_post_insights(payload, post_id, now)
                except requests.HTTPError:
                    pass  # fall through to the slower per-metric path below

        # Generic failure that doesn't name the metric (e.g. "The value
        # must be a valid insights metric" -- a real one hit in production,
        # a DIFFERENT message than the one _extract_unsupported_metrics
        # parses). Isolate per metric -- but ALSO cache whichever ones fail
        # here, so this discovery cost is paid only once per media type,
        # same guarantee as the named-error path above, even when Meta
        # doesn't tell us directly which metric was the problem.
        #
        # CRITICAL EXCEPTION: "not enough viewers" (error code 10) is a
        # PER-POST condition (this specific post/story lacks enough views),
        # NOT a media-type-level incompatibility. Caching it would wrongly
        # conclude the metric is broken for every post of this type forever
        # -- silently losing real data on a different post that DOES have
        # enough views. Only structural failures get cached; transient
        # per-post ones are retried fresh on every post.
        records = []
        for metric in effective_metrics:
            try:
                payload = _get(f"{post_id}/insights", {"metric": metric}, token=token)
                records.extend(_parse_post_insights(payload, post_id, now))
            except requests.HTTPError as inner_e:
                inner_text = inner_e.response.text if inner_e.response is not None else ""
                if "not enough viewers" not in inner_text.lower():
                    _unsupported_metrics_cache.setdefault(cache_key, set()).add(metric)
        return records


def _get_next_page(next_url: str) -> dict:
    """
    Follows Meta's own pagination cursor. `paging.next` is a complete,
    ready-to-use URL (already includes the access token), so this bypasses
    _get()'s path+params construction and just requests it directly.
    """
    resp = requests.get(next_url)
    if resp.status_code >= 400:
        print(f"[meta] API error response body: {resp.text}")
    resp.raise_for_status()
    return resp.json()


def fetch_instagram_posts(limit: int = POSTS_PER_PLATFORM_LIMIT, max_pages: int = 1) -> tuple[list[SocialPost], list[SocialPostMetric]]:
    """
    Feed posts and Reels, with per-post insights.

    `max_pages` controls historical depth: the regular daily sync passes 1
    (just the most recent `limit` posts, cheap). A historical backfill
    passes a higher number to page back through older content via Meta's
    own pagination cursor.

    HARD LIMIT, not arbitrary: Instagram media-level insights retain for
    roughly 2 years, not indefinitely (this is a real Meta-documented
    constraint, unlike the 90-day cap on ACCOUNT-level insights, which is
    tighter still and cannot be backfilled at all once missed). Once posts
    age past that window, per-post insight calls will start failing --
    _fetch_post_insights already handles that gracefully (isolates the
    failure per metric, doesn't crash the whole backfill), so an aging-out
    post just ends up with fewer captured metrics, not a hard stop.

    Requests branded-content fields so paid partnerships are identifiable --
    the direct programmatic link between a post and Brand Partnership
    revenue. NOTE: the exact branded-content field names are Meta's newer
    2026 additions and are UNCONFIRMED against a real account; they're
    requested defensively and their absence is handled, not assumed.
    """
    now = datetime.now(timezone.utc)
    fields = "id,caption,media_type,permalink,timestamp,like_count,comments_count"

    posts, metrics = [], []
    page_num = 0
    payload = _get(f"{META_IG_USER_ID}/media", {"fields": fields, "limit": limit})

    while True:
        page_num += 1
        page_items = payload.get("data", [])
        print(f"[meta] Instagram posts, page {page_num}: {len(page_items)} item(s)")

        for item in page_items:
            post_id = item.get("id")
            if not post_id:
                continue
            media_type = item.get("media_type")

            posted_at = None
            if item.get("timestamp"):
                try:
                    posted_at = datetime.fromisoformat(item["timestamp"].replace("+0000", "+00:00"))
                except ValueError:
                    pass

            posts.append(SocialPost(
                account_id=META_IG_USER_ID, post_id=post_id, platform="instagram",
                media_type=media_type, caption=item.get("caption"),
                permalink=item.get("permalink"), posted_at=posted_at,
            ))

            wanted = list(IG_POST_METRICS)
            if media_type in ("VIDEO", "REEL"):
                wanted += IG_REEL_EXTRA_METRICS
            metrics.extend(_fetch_post_insights(post_id, wanted, now, media_type=media_type))

        next_url = payload.get("paging", {}).get("next")
        if not next_url or page_num >= max_pages:
            break
        payload = _get_next_page(next_url)

    return posts, metrics


def fetch_instagram_stories() -> tuple[list[SocialPost], list[SocialPostMetric]]:
    """
    Live Stories only.

    CRITICAL TIMING CONSTRAINT: story insights are retrievable ONLY while
    the story is live (24h), and vanish permanently on expiry with no
    backfill possible. A once-daily sync WILL systematically miss stories
    posted and expired between runs -- this needs its own ~12-hourly
    schedule to guarantee capture. Marked is_ephemeral=True so a missing
    story is understood as unrecoverable rather than retryable.

    Relevant commercially: "IG Stories" is a named deliverable_platform in
    airtable_partnerships, i.e. brand deals are contracted against Story
    delivery -- so uncaptured story performance is unreportable against a
    deliverable that was actually billed.
    """
    now = datetime.now(timezone.utc)
    try:
        resp = _get(f"{META_IG_USER_ID}/stories",
                    {"fields": "id,media_type,permalink,timestamp"})
    except requests.HTTPError as e:
        print(f"[meta] Stories fetch failed (may require additional permissions): {e}")
        return [], []

    posts, metrics = [], []
    for item in resp.get("data", []):
        post_id = item.get("id")
        if not post_id:
            continue

        posted_at = None
        if item.get("timestamp"):
            try:
                posted_at = datetime.fromisoformat(item["timestamp"].replace("+0000", "+00:00"))
            except ValueError:
                pass

        posts.append(SocialPost(
            account_id=META_IG_USER_ID, post_id=post_id, platform="instagram",
            media_type="STORY", permalink=item.get("permalink"),
            posted_at=posted_at, is_ephemeral=True,
        ))
        metrics.extend(_fetch_post_insights(post_id, IG_STORY_METRICS, now, media_type="STORY"))

    if not posts:
        print("[meta] No live stories found (expected if none posted in the last 24h).")
    return posts, metrics


def fetch_facebook_posts(limit: int = POSTS_PER_PLATFORM_LIMIT, max_pages: int = 1) -> tuple[list[SocialPost], list[SocialPostMetric]]:
    """
    Facebook Page posts. Requires the Page token, same as Page insights.

    Same pagination pattern as fetch_instagram_posts -- max_pages=1 for the
    regular daily sync, higher for a historical backfill.

    Worth the effort despite Facebook being only 6.6% of Instagram's
    follower count: measured against real data, FB delivers ~21-26% of the
    engagement Instagram does, at roughly 3x Instagram's per-follower
    engagement rate. It punches well above its audience size.
    """
    now = datetime.now(timezone.utc)
    page_token = get_page_access_token()

    posts, metrics = [], []
    page_num = 0
    payload = _get(f"{META_PAGE_ID}/posts",
                   {"fields": "id,message,permalink_url,created_time", "limit": limit},
                   token=page_token)

    while True:
        page_num += 1
        page_items = payload.get("data", [])
        print(f"[meta] Facebook posts, page {page_num}: {len(page_items)} item(s)")

        for item in page_items:
            post_id = item.get("id")
            if not post_id:
                continue

            posted_at = None
            if item.get("created_time"):
                try:
                    posted_at = datetime.fromisoformat(item["created_time"].replace("+0000", "+00:00"))
                except ValueError:
                    pass

            posts.append(SocialPost(
                account_id=META_PAGE_ID, post_id=post_id, platform="facebook",
                media_type="post", caption=item.get("message"),
                permalink=item.get("permalink_url"), posted_at=posted_at,
            ))
            metrics.extend(_fetch_post_insights(post_id, FB_POST_METRICS, now, token=page_token, media_type="FB_POST"))

        next_url = payload.get("paging", {}).get("next")
        if not next_url or page_num >= max_pages:
            break
        payload = _get_next_page(next_url)

    return posts, metrics


def sync_posts() -> int:
    """
    Post-level sync -- SEPARATE entry point from run().

    Kept separate because it's N+1 in API calls (one insights request per
    post) and doesn't need the same cadence as account metrics. Stories are
    the exception: they need MORE frequent runs than daily, not fewer, or
    they're lost permanently.
    """
    all_posts, all_metrics = [], []

    for label, fetcher in [("instagram posts", fetch_instagram_posts),
                           ("instagram stories", fetch_instagram_stories),
                           ("facebook posts", fetch_facebook_posts)]:
        try:
            posts, metrics = fetcher()
            all_posts.extend(posts)
            all_metrics.extend(metrics)
            print(f"[meta] {label}: {len(posts)} post(s), {len(metrics)} metric(s)")
        except Exception as e:
            print(f"[meta] {label} FAILED (others unaffected): {e}")

    written = 0
    if all_posts:
        written += upsert_rows("social_posts", [p.to_row() for p in all_posts])
    if all_metrics:
        written += upsert_rows("social_post_metrics", [m.to_row() for m in all_metrics])
    return written


def backfill_historical_posts(max_pages: int = 20) -> int:
    """
    One-time (or occasional) historical pull -- NOT part of the regular
    daily sync_posts(). Pages back through older Instagram and Facebook
    posts via Meta's own pagination cursor, rather than just the most
    recent POSTS_PER_PLATFORM_LIMIT.

    REAL LIMIT TO EXPECT, not a bug if hit: Instagram media-level insights
    retain for roughly 2 years. Posts older than that will still be listed
    (caption/permalink/timestamp), but their per-post METRICS will
    increasingly come back empty as they age past the window --
    _fetch_post_insights already isolates that failure per-metric rather
    than crashing, so this shows up as posts with fewer captured metrics,
    not a hard stop partway through.

    Stories are deliberately excluded here -- they're gone after 24h with
    no backfill possible under any circumstances; there's nothing to pull.

    `max_pages` default of 20 (at 25 posts/page = up to 500 posts) is a
    starting point, not a hard technical ceiling -- raise it if the account
    has more history than that and rate limits allow.
    """
    print(f"[meta] Starting historical backfill (up to {max_pages} pages per platform)...")
    all_posts, all_metrics = [], []

    for label, fetcher in [("instagram posts", fetch_instagram_posts),
                           ("facebook posts", fetch_facebook_posts)]:
        try:
            posts, metrics = fetcher(max_pages=max_pages)
            all_posts.extend(posts)
            all_metrics.extend(metrics)
            print(f"[meta] {label} backfill: {len(posts)} post(s), {len(metrics)} metric(s)")
        except Exception as e:
            print(f"[meta] {label} backfill FAILED (others unaffected): {e}")

    written = 0
    if all_posts:
        written += upsert_rows("social_posts", [p.to_row() for p in all_posts])
    if all_metrics:
        written += upsert_rows("social_post_metrics", [m.to_row() for m in all_metrics])
    print(f"[meta] Historical backfill complete: {written} rows written.")
    return written


def run() -> int:
    seed_accounts()
    records = fetch_instagram_metrics() + fetch_facebook_metrics()
    written = upsert_rows("social_metrics", [r.to_row() for r in records])

    # Demographics are isolated from the main metrics write: this is a new,
    # differently-shaped request (breakdown parameter, nested response) and
    # untested against a real account, so a failure here must not cost us
    # the core metrics that are already known to work.
    try:
        demographics = fetch_instagram_demographics()
        if demographics:
            demo_written = upsert_rows(
                "social_audience_demographics", [d.to_row() for d in demographics]
            )
            print(f"[meta] Wrote {demo_written} audience demographic rows.")
        else:
            print("[meta] No audience demographic rows returned.")
    except Exception as e:
        print(f"[meta] Demographics fetch failed (core metrics unaffected): {e}")

    return written


if __name__ == "__main__":
    count = run()
    print(f"Meta connector: upserted {count} social metrics.")
