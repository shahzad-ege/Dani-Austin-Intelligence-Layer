"""
check_boost_eligibility_variance.py — Follow-up to
discover_branded_content_fields.py.

The first discovery run found 3 fields that return REAL data
(boost_eligibility_info, media_product_type, shortcode) versus 11 that were
silently accepted-but-empty -- including several field names that were pure
guesses, proving Meta's Media endpoint doesn't validate field names
strictly. That means the "accepted but empty" results are NOT evidence
those are real branded-content fields; only genuinely-populated data counts.

boost_eligibility_info is the most promising real lead (its name directly
matches the "Allow brand partner to boost" permission from Meta's branded-
content workflow). But a single sample showing {'eligible_to_boost': True}
doesn't tell us whether this is a genuine per-post signal or just a
constant that's True for every organic post regardless of branding. This
script checks variance across ALL fetched posts -- if it's uniform, it's
not a useful discriminator for branded content; if it varies, that's real
evidence worth pursuing.
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

META_SYSTEM_USER_TOKEN = os.environ["META_SYSTEM_USER_TOKEN"]
META_IG_USER_ID = os.environ["META_IG_USER_ID"]
GRAPH_BASE_URL = "https://graph.facebook.com/v25.0"


def main() -> None:
    resp = requests.get(
        f"{GRAPH_BASE_URL}/{META_IG_USER_ID}/media",
        params={
            "fields": "id,caption,media_type,boost_eligibility_info",
            "limit": 25,
            "access_token": META_SYSTEM_USER_TOKEN,
        },
    )
    resp.raise_for_status()
    posts = resp.json().get("data", [])

    print(f"Checked {len(posts)} posts for boost_eligibility_info variance:\n")

    values_seen = set()
    for p in posts:
        info = p.get("boost_eligibility_info")
        caption_preview = (p.get("caption") or "")[:40]
        print(f"  {p['id']}  media_type={p.get('media_type'):10} "
              f"boost_info={info}  caption='{caption_preview}...'")
        if info is not None:
            values_seen.add(str(info))

    print(f"\nDistinct boost_eligibility_info values seen: {len(values_seen)}")
    for v in values_seen:
        print(f"  {v}")

    if len(values_seen) <= 1:
        print("\nCONCLUSION: this field is CONSTANT across all posts -- it does")
        print("NOT distinguish branded/partnership posts from ordinary ones.")
        print("Not usable as a branded-content signal.")
    else:
        print("\nCONCLUSION: this field VARIES across posts -- worth investigating")
        print("further as a possible branded-content signal, cross-referenced")
        print("against posts known to be real brand deals.")


if __name__ == "__main__":
    main()
