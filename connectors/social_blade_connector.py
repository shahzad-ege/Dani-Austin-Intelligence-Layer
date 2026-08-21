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
from datetime import date

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


def fetch_statistics(platform: str, handle: str) -> dict:
    """Pulls current statistics for one handle on one platform."""
    resp = requests.get(
        f"{SOCIALBLADE_BASE_URL}/{platform}/statistics",
        headers={
            "clientid": SOCIALBLADE_CLIENT_ID,
            "token": SOCIALBLADE_TOKEN,
        },
        params={"query": handle},
    )
    resp.raise_for_status()
    payload = resp.json()

    credits_left = payload.get("info", {}).get("credits", {}).get("available")
    if credits_left is not None and credits_left < 10:
        print(f"[social_blade] WARNING: only {credits_left} credits remaining.")

    return payload


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
