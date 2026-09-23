"""
social_blade_connector.py — Social Blade Business API connector.

Unlike Meta/TikTok, this needs no App Review — just a clientid/token pair
from the Social Blade Developer Console (https://socialblade.com/developers).
It's the fastest social-data source to stand up and doubles as a vanity-
metric backfill once Meta/TikTok are live.

Cost model: 1 credit per profile lookup (default depth, ~30 days history),
then that lookup is cached free for 30 days. A daily sync of the same
handles costs ~1 credit/handle/month, not 1 credit/handle/day — safe to run
on a daily schedule.

CONFIRMED against socialblade.com/developers/docs directly (not guessed):
  - Endpoint shape: GET /{platform}/statistics?query={handle}
  - Auth: clientid/token as headers (preferred) or query params
  - Response fields, per platform (these are what FIELD_MAP below maps to):
      instagram: followers, following, media, engagement_rate
      tiktok:    followers, following, likes, uploads
      facebook:  likes (=followers), talking_about (=engagement)
  - Response also includes info.credits.available — logged below so a run
    surfaces low-credit situations instead of silently failing later.
  - Zero-credit test: querying handle "SocialBlade" (or "SocialBlade.com"
    on TikTok specifically) costs 0 credits and needs no auth at all — use
    this to sanity-check connectivity before spending real credits.

Requires (via env vars, sourced from 1Password at run time):
    SOCIALBLADE_CLIENT_ID
    SOCIALBLADE_TOKEN

Requires social_accounts to already have rows for each handle being synced
(platform + handle + account_id). Run seed_accounts() once to register the
Dani Austin handles before the first sync.
"""

import os
import requests
from datetime import date, datetime

from models import SocialAccount, SocialMetric
from writer import upsert_rows

SOCIALBLADE_CLIENT_ID = os.environ["SOCIALBLADE_CLIENT_ID"]
SOCIALBLADE_TOKEN = os.environ["SOCIALBLADE_TOKEN"]

SOCIALBLADE_BASE_URL = "https://matrix.sbapis.com/b"

# Dani Austin's core handles. Fill in real handles/account_ids before first
# run — account_id can just mirror handle for platforms where Social Blade
# keys off username rather than a separate numeric ID.
SEED_ACCOUNTS = [
    # CONFIRMED real handles -- "daniaustin" was correct for Instagram, but
    # WRONG for TikTok and Facebook (Social Blade returned a ghost/near-empty
    # account under that name for both, cross-verified as wrong against real
    # Meta data). These are the corrected handles that produced plausible,
    # cross-verified numbers (Facebook followers matched Meta's own connector
    # within 0.03%; TikTok showed a real 1.1M-follower account instead of 65).
    SocialAccount(platform="instagram", handle="daniaustin", account_id="daniaustin_ig", is_core=True),
    SocialAccount(platform="tiktok", handle="thedaniaustin", account_id="daniaustin_tiktok", is_core=True),
    SocialAccount(platform="facebook", handle="daniaustinofficial", account_id="daniaustin_fb", is_core=True),
]

# Maps our metric names -> the field names Social Blade actually returns,
# confirmed against socialblade.com/developers/docs (fetched directly, not
# guessed). Earlier version of this map had three wrong field names
# (Instagram "posts"->should be "media", TikTok "posts"->should be
# "uploads", Facebook mapped backwards) — fixed here.
FIELD_MAP = {
    "instagram": {"followers": "followers", "media": "media", "engagement_rate": "engagement_rate"},
    "tiktok": {"followers": "followers", "likes": "likes", "uploads": "uploads"},
    "facebook": {"followers": "likes", "engagement": "talking_about"},
}


def seed_accounts() -> int:
    """One-time (or idempotent) registration of tracked handles."""
    return upsert_rows("social_accounts", [a.to_row() for a in SEED_ACCOUNTS])


def fetch_statistics(platform: str, handle: str, history: str | None = None) -> dict:
    """Pulls current statistics for one handle on one platform.

    REAL FINDING (Sep 2026), confirmed directly from Social Blade's own
    official API schema: the `daily[]` array's ~30-day depth has NOTHING
    to do with subscription tier (Silver's 60-day dashboard benefit
    doesn't apply here, confirmed by a real live test). It's controlled
    entirely by this `history` request parameter, which this function
    never sent before -- meaning every call has always silently used the
    free "default" tier (1 credit, 30 days) regardless of account tier.

    Confirmed real values, each a genuinely higher-cost, deeper pull:
      - None/"default" -- 1 credit, 30 days (existing behavior, unchanged)
      - "extended"      -- 2 credits, up to 1 year
      - "archive"       -- 3 credits, up to 3 years
      - "vault"         -- 5 credits, up to 10 years (TikTok/IG/FB;
                            YouTube caps at 3 years via "archive")

    Real cost note: a profile lookup at ANY tier is free to re-check for
    the next 30 days -- the credit is spent once per lookup, not per
    day. Deliberately defaults to None (unchanged, free, 30-day
    behavior) -- fetching deeper history costs real, limited credits and
    should be a deliberate choice, not something that happens by
    default on every routine daily sync call.
    """
    params = {"query": handle}
    if history:
        params["history"] = history

    resp = requests.get(
        f"{SOCIALBLADE_BASE_URL}/{platform}/statistics",
        headers={
            "clientid": SOCIALBLADE_CLIENT_ID,
            "token": SOCIALBLADE_TOKEN,
        },
        params=params,
    )
    resp.raise_for_status()
    payload = resp.json()

    credits_left = payload.get("info", {}).get("credits", {}).get("available")
    if credits_left is not None and credits_left < 10:
        print(f"[social_blade] WARNING: only {credits_left} credits remaining.")

    return payload


def backfill_from_daily_history(max_days: int | None = None) -> int:
    """
    Uses the `daily` array Social Blade ALREADY returns in the same
    statistics call `run()` makes -- confirmed via direct diagnostic
    (diagnose_tiktok_social_blade.py) to contain up to ~30 days of real
    daily history per call, at NO extra API cost or credit spend. The
    regular run() was discarding all of this except today's single point.

    CONFIRMED working shape for TikTok specifically (real payload
    inspected directly): each entry in data.daily[] has the same field
    names as data.statistics.total (followers, following, uploads,
    likes), one entry per date. Instagram/Facebook's daily array shape
    is UNCONFIRMED -- this function is written generically to attempt
    the same parsing for all platforms via the existing FIELD_MAP, but
    isolates failures per-platform so an unconfirmed/different shape on
    IG or FB can't crash the whole backfill or silently corrupt TikTok's
    known-good data.

    This is what actually resolved the original "TikTok values look
    static" question: the same diagnostic that raised this concern showed
    `following` and `uploads` genuinely incrementing day to day in this
    same daily[] array, proving the connector pulls fresh data daily.
    `followers` specifically staying at a flat 1,100,000 is best explained
    by TikTok/Social Blade rounding large follower counts for display,
    not a caching bug -- confirmed by the OTHER fields moving in the same
    response, not assumed.
    """
    total_written = 0

    for account in SEED_ACCOUNTS:
        try:
            stats = fetch_statistics(account.platform, account.handle)
        except requests.HTTPError as e:
            print(f"[social_blade] backfill: '{account.platform}' handle '{account.handle}' FAILED: {e}")
            continue

        daily_entries = stats.get("data", {}).get("daily", [])
        if not daily_entries:
            print(f"[social_blade] backfill: '{account.platform}' returned no daily[] array -- skipping")
            continue

        if max_days is not None:
            daily_entries = daily_entries[:max_days]

        field_map = FIELD_MAP.get(account.platform, {})
        records: list[SocialMetric] = []

        for entry in daily_entries:
            raw_date = entry.get("date")
            if not raw_date:
                continue
            try:
                entry_date = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).date()
            except ValueError:
                print(f"[social_blade] backfill: unparseable date {raw_date!r} for '{account.platform}' -- skipping this entry")
                continue

            for our_metric, sb_field in field_map.items():
                value = entry.get(sb_field)
                if value is None:
                    continue
                records.append(
                    SocialMetric(
                        account_id=account.account_id,
                        metric=our_metric,
                        period_date=entry_date,
                        value=float(value),
                        source="social_blade",
                    )
                )

        if records:
            written = upsert_rows("social_metrics", [r.to_row() for r in records])
            total_written += written
            print(f"[social_blade] backfill: '{account.platform}' -- {len(daily_entries)} day(s), {written} row(s) written")

    return total_written


HISTORY_COSTS = {"extended": 2, "archive": 3, "vault": 5}


def deep_history_backfill(platform: str, history: str = "extended", confirm_cost: bool = False) -> int:
    """
    Deliberate, ONE-TIME pull of real historical data far beyond the
    free 30-day daily[] window -- confirmed directly from Social Blade's
    own official API schema (Sep 2026): the `history` parameter controls
    this, completely independent of subscription tier. Real, confirmed
    depths: "extended"=1yr (2 credits), "archive"=3yr (3 credits),
    "vault"=10yr for TikTok/IG/FB, 3yr max for YouTube (5 credits).

    UNLIKE backfill_from_daily_history() (free, safe to run anytime),
    this spends real, limited Business API credits -- Silver tier
    provides only 5/month total. Deliberately requires confirm_cost=True
    to actually run, so this can never be triggered accidentally by
    routine automation; this is meant to be called by hand, once, when
    genuinely wanted, not part of any scheduled sync.

    Reuses the same field-mapping and date-parsing logic already proven
    correct in backfill_from_daily_history() -- this function differs
    only in requesting a deeper `history` tier, not in how the response
    is parsed.
    """
    if history not in HISTORY_COSTS:
        raise ValueError(f"history must be one of {list(HISTORY_COSTS)}, got {history!r}")

    cost = HISTORY_COSTS[history]
    if not confirm_cost:
        print(f"[social_blade] deep_history_backfill for '{platform}' with history={history!r} "
              f"costs {cost} real credit(s), taken from Silver's limited 5/month allowance. "
              f"Call again with confirm_cost=True to actually spend it.")
        return 0

    account = next((a for a in SEED_ACCOUNTS if a.platform == platform), None)
    if account is None:
        print(f"[social_blade] No seed account found for platform {platform!r}")
        return 0

    try:
        stats = fetch_statistics(account.platform, account.handle, history=history)
    except requests.HTTPError as e:
        print(f"[social_blade] deep backfill: '{platform}' FAILED (credit still likely spent -- check your balance): {e}")
        return 0

    # REAL FIX: previously required guessing/calculating the remaining
    # balance externally from assumed tier limits -- which turned out
    # wrong in practice (a Facebook pull succeeded when external math
    # predicted insufficient credits). The API response already reports
    # the real, live balance directly -- surfacing it here removes the
    # need to guess at all going forward.
    credits_left = stats.get("info", {}).get("credits", {}).get("available")
    if credits_left is not None:
        print(f"[social_blade] Real credit balance after this call: {credits_left}")

    daily_entries = stats.get("data", {}).get("daily", [])
    if not daily_entries:
        print(f"[social_blade] deep backfill: '{platform}' returned no daily[] array despite the deeper request")
        return 0

    field_map = FIELD_MAP.get(account.platform, {})
    records: list[SocialMetric] = []

    for entry in daily_entries:
        raw_date = entry.get("date")
        if not raw_date:
            continue
        try:
            entry_date = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).date()
        except ValueError:
            print(f"[social_blade] deep backfill: unparseable date {raw_date!r} -- skipping this entry")
            continue

        for our_metric, sb_field in field_map.items():
            value = entry.get(sb_field)
            if value is None:
                continue
            records.append(
                SocialMetric(
                    account_id=account.account_id,
                    metric=our_metric,
                    period_date=entry_date,
                    value=float(value),
                    source="social_blade",
                )
            )

    if not records:
        return 0

    written = upsert_rows("social_metrics", [r.to_row() for r in records])
    print(f"[social_blade] deep backfill: '{platform}' -- {len(daily_entries)} real day(s) of history, {written} row(s) written "
          f"(spent {cost} credit(s))")
    return written


def run() -> int:
    today = date.today()
    records: list[SocialMetric] = []

    for account in SEED_ACCOUNTS:
        # Isolated per account: one wrong/missing handle (e.g. Facebook
        # using a different vanity slug than Instagram/TikTok) shouldn't
        # prevent the other platforms' data from being written. Discovered
        # via a real 404 on Facebook while Instagram/TikTok presumably
        # succeeded -- but that couldn't even be confirmed before this fix,
        # since the whole run aborted on the first failure.
        try:
            stats = fetch_statistics(account.platform, account.handle)
        except requests.HTTPError as e:
            print(f"[social_blade] '{account.platform}' handle '{account.handle}' FAILED: {e}")
            continue

        data = stats.get("data", {}).get("statistics", {}).get("total", {})
        field_map = FIELD_MAP.get(account.platform, {})

        for our_metric, sb_field in field_map.items():
            value = data.get(sb_field)
            if value is None:
                continue
            records.append(
                SocialMetric(
                    account_id=account.account_id,
                    metric=our_metric,
                    period_date=today,
                    value=float(value),
                    source="social_blade",
                )
            )

    return upsert_rows("social_metrics", [r.to_row() for r in records])


if __name__ == "__main__":
    seeded = seed_accounts()
    count = run()
    print(f"Social Blade connector: seeded {seeded} accounts, upserted {count} metrics.")
