"""
diagnose_facebook_post_stall.py — Diagnoses the finding (confirmed by both
DA_Data_Scrub_Report and the more detailed Meta_API_Bug_Report) that
Facebook post-level data stalled at 2026-06-03 while Instagram continued
to 2026-09-01.

Important context: the SAME fetch_facebook_posts() function successfully
backfilled ~7 years of Facebook history in an earlier session, which
proves the connector isn't fundamentally broken (auth/permissions work).
This leaves two real possibilities that look identical from Supabase
alone, and this script exists to tell them apart:

  (a) Genuinely no new Facebook posts have been published since June 3 --
      a content gap, not a bug. The regular sync (max_pages=1, most recent
      25 posts) would correctly find nothing new to add.
  (b) The regular 12-hourly sync IS failing for Facebook specifically
      (token expiry, changed permission, rate limit) while the historical
      backfill call happened to run before whatever broke it.

The Meta API Bug Report adds a genuinely useful, more specific diagnostic
signal worth checking directly in Supabase alongside this script: post
METRICS are still refreshing daily on existing posts (newest metric fetch
= Sep 1) even though no NEW posts are being discovered. That splits the
failure more precisely -- the metrics-fetch call is authenticating fine,
but the feed/publishing DISCOVERY call specifically (the part of
fetch_facebook_posts that lists posts, before per-post metrics are even
requested) is what's not finding anything new. If this script's output
below shows outcome (b), the most likely specific causes, per that
report, are: a broken pagination/cursor on the Page /feed or
/published_posts endpoint, a lapsed permission scope specifically
(pages_read_engagement / pages_read_user_content), or a Page-access-token
issue scoped to that one endpoint rather than the token as a whole.

Run this directly -- it calls fetch_facebook_posts() fresh, right now, and
reports exactly what comes back.
"""

import sys
from datetime import date

sys.path.insert(0, ".")

import meta_connector


def main() -> None:
    print("Calling fetch_facebook_posts() directly, fetching the most recent page...\n")

    try:
        posts, metrics = meta_connector.fetch_facebook_posts(limit=25, max_pages=1)
    except Exception as e:
        print(f"CALL FAILED with an exception: {type(e).__name__}: {e}")
        print("\nThis IS the pipeline bug -- something is actively erroring, not")
        print("silently returning empty. The exception above is the real cause.")
        return

    if not posts:
        print("Call SUCCEEDED but returned ZERO posts.")
        print("\nThis is ambiguous on its own -- could mean no recent posts exist,")
        print("or could mean the API is silently returning an empty page instead")
        print("of erroring. Check the Facebook Page directly in a browser to see")
        print("if there ARE posts newer than 2026-06-03 that this call should")
        print("have found.")
        return

    print(f"Call succeeded, returned {len(posts)} post(s):\n")
    most_recent = None
    for p in sorted(posts, key=lambda x: x.posted_at or date.min, reverse=True):
        print(f"  {p.posted_at}  id={p.post_id}  caption preview: {(p.caption or '')[:50]!r}")
        if most_recent is None:
            most_recent = p.posted_at

    print(f"\nMost recent post found: {most_recent}")

    if most_recent and most_recent.date() > date(2026, 6, 3):
        print("\nThis is NEWER than the 2026-06-03 stall date reported in the")
        print("scrub -- meaning the pipeline works NOW. Whatever caused the stall")
        print("may have been transient (a temporary token issue that has since")
        print("been resolved by a later token refresh). Worth confirming these")
        print("newer posts actually make it into Supabase on the next real sync.")
    else:
        print("\nThis CONFIRMS no post newer than the reported stall date exists")
        print("via this API call. Check the real Facebook Page directly -- if")
        print("newer posts exist there that this call isn't finding, that's a")
        print("real, current pipeline bug. If no newer posts exist on the Page")
        print("either, this is a genuine content gap, not a bug.")


if __name__ == "__main__":
    main()
