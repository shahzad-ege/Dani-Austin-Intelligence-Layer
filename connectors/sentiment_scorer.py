"""
sentiment_scorer.py — Scores earned_mentions rows for sentiment using
Claude, closing the gap accepted when Xpoz (free, raw mentions) was
chosen over paid tools like Brand24/Awario that include sentiment
built in.

SETUP NEEDED:
  - An Anthropic API key: ANTHROPIC_API_KEY environment variable.
  - pip install anthropic

Batches multiple mentions into a single API call rather than one call
per mention, both for cost efficiency and to reduce total call volume.

NOT YET LIVE-TESTED: built against the standard, documented Anthropic
API request/response shape, but this project has repeatedly found real
gaps between documented and live behavior (Facebook demographics,
Xpoz's actual architecture) -- treat the first real run as the actual
confirmation, same discipline as everything else new here.
"""

import os
import json
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(usecwd=True))

import anthropic
from db import get_client

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
MODEL = "claude-haiku-4-5-20251001"  # fast, cheap -- appropriate for a
# short-text classification task, not something that needs a larger model

BATCH_SIZE = 20

VALID_SENTIMENTS = {"positive", "negative", "neutral", "mixed"}


def _build_prompt(mentions: list[dict]) -> str:
    numbered = "\n".join(
        f"{i}. [{m['platform']}] {m['content_text'][:500]}"
        for i, m in enumerate(mentions)
    )
    return f"""Classify the sentiment of each of the following social media mentions of "Dani Austin" (a lifestyle influencer/podcaster). For each, decide whether the mention's tone toward her is positive, negative, neutral, or mixed.

Mentions:
{numbered}

Respond with ONLY a JSON array, one object per mention, in the same order, each with exactly these fields:
- "index": the number shown above
- "sentiment": one of "positive", "negative", "neutral", "mixed"
- "reasoning": a brief (under 15 words) real explanation for that specific mention

No other text before or after the JSON array."""


def _score_batch(client: anthropic.Anthropic, mentions: list[dict]) -> list[dict]:
    """Calls Claude once for a batch of mentions. Returns [] on any
    failure -- isolated per batch so one bad batch doesn't kill the
    whole run, same reasoning used everywhere else in this project."""
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": _build_prompt(mentions)}],
        )
        raw_text = response.content[0].text.strip()
        # Defensive: strip markdown code fences if the model adds them
        # despite being asked not to -- a real, common LLM quirk worth
        # guarding against rather than assuming perfect compliance.
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
            raw_text = raw_text.strip()

        results = json.loads(raw_text)
    except Exception as e:
        print(f"[sentiment] Batch scoring FAILED: {type(e).__name__}: {e}")
        return []

    validated = []
    for r in results:
        sentiment = r.get("sentiment")
        if sentiment not in VALID_SENTIMENTS:
            print(f"[sentiment] Skipping invalid sentiment value {sentiment!r} at index {r.get('index')}")
            continue
        validated.append(r)

    return validated


def run(limit: int = 200) -> int:
    """
    Scores up to `limit` currently-unscored mentions (sentiment IS
    NULL), in batches of BATCH_SIZE. Returns how many rows were
    successfully updated.
    """
    if not ANTHROPIC_API_KEY:
        print("[sentiment] ANTHROPIC_API_KEY not set -- skipping.")
        return 0

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    supabase = get_client()

    unscored = (
        supabase.table("earned_mentions")
        .select("id, platform, content_text")
        .is_("sentiment", "null")
        .limit(limit)
        .execute()
    )
    rows = unscored.data
    if not rows:
        print("[sentiment] No unscored mentions found.")
        return 0

    total_updated = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        results = _score_batch(client, batch)

        for r in results:
            idx = r["index"]
            if idx >= len(batch):
                continue
            row_id = batch[idx]["id"]
            supabase.table("earned_mentions").update({
                "sentiment": r["sentiment"],
                "sentiment_reasoning": r["reasoning"],
            }).eq("id", row_id).execute()
            total_updated += 1

        print(f"[sentiment] Batch {i // BATCH_SIZE + 1}: scored {len(results)}/{len(batch)}")

    return total_updated


if __name__ == "__main__":
    updated = run()
    print(f"\nTotal mentions scored: {updated}")
