"""
test_sentiment_scorer.py — Tests for Claude-based sentiment scoring on
earned_mentions.
"""

import os
import sys
import json
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("DA_SUPABASE_URL", "https://fake.supabase.co")
os.environ.setdefault("DA_SUPABASE_SERVICE_KEY", "fake")

import sentiment_scorer as ss  # noqa: E402


def _fake_response(payload):
    resp = MagicMock()
    resp.content = [MagicMock(text=json.dumps(payload))]
    return resp


def test_batch_scoring_parses_real_response_shape():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _fake_response([
        {"index": 0, "sentiment": "negative", "reasoning": "accusing her of scamming people"},
        {"index": 1, "sentiment": "positive", "reasoning": "genuine celebratory congratulations"},
    ])
    mentions = [
        {"platform": "reddit", "content_text": "Shame on Dani Austin"},
        {"platform": "instagram", "content_text": "Congrats!!"},
    ]
    result = ss._score_batch(mock_client, mentions)
    assert len(result) == 2
    assert result[0]["sentiment"] == "negative"


def test_handles_markdown_wrapped_json():
    """LLMs sometimes wrap JSON in code fences despite explicit
    instructions not to -- a real, common quirk worth guarding
    against rather than assuming perfect compliance."""
    mock_client = MagicMock()
    resp = MagicMock()
    resp.content = [MagicMock(text='```json\n[{"index": 0, "sentiment": "positive", "reasoning": "nice"}]\n```')]
    mock_client.messages.create.return_value = resp

    result = ss._score_batch(mock_client, [{"platform": "x", "content_text": "a"}])
    assert len(result) == 1
    assert result[0]["sentiment"] == "positive"


def test_invalid_sentiment_value_filtered_not_crashed():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _fake_response([
        {"index": 0, "sentiment": "very_positive", "reasoning": "not a real category"},
        {"index": 1, "sentiment": "positive", "reasoning": "valid"},
    ])
    result = ss._score_batch(mock_client, [{"platform": "x", "content_text": "a"}, {"platform": "x", "content_text": "b"}])
    assert len(result) == 1
    assert result[0]["sentiment"] == "positive"


def test_malformed_json_returns_empty_not_crash():
    mock_client = MagicMock()
    resp = MagicMock()
    resp.content = [MagicMock(text="not json at all")]
    mock_client.messages.create.return_value = resp

    result = ss._score_batch(mock_client, [{"platform": "x", "content_text": "a"}])
    assert result == []


def test_run_skips_cleanly_without_api_key():
    with patch("sentiment_scorer.ANTHROPIC_API_KEY", None):
        result = ss.run()
    assert result == 0


def test_run_updates_correct_rows_in_supabase():
    fake_mentions = [
        {"id": 101, "platform": "reddit", "content_text": "Shame on Dani Austin"},
        {"id": 102, "platform": "instagram", "content_text": "Congrats!!"},
    ]
    mock_anthropic_client = MagicMock()
    mock_anthropic_client.messages.create.return_value = _fake_response([
        {"index": 0, "sentiment": "negative", "reasoning": "critical tone"},
        {"index": 1, "sentiment": "positive", "reasoning": "celebratory"},
    ])

    mock_supabase = MagicMock()
    mock_supabase.table.return_value.select.return_value.is_.return_value.limit.return_value.execute.return_value.data = fake_mentions

    with patch("sentiment_scorer.anthropic.Anthropic", return_value=mock_anthropic_client), \
         patch("sentiment_scorer.get_client", return_value=mock_supabase):
        updated = ss.run()

    assert updated == 2


def test_run_returns_zero_when_nothing_unscored():
    mock_supabase = MagicMock()
    mock_supabase.table.return_value.select.return_value.is_.return_value.limit.return_value.execute.return_value.data = []

    with patch("sentiment_scorer.get_client", return_value=mock_supabase):
        updated = ss.run()

    assert updated == 0


def test_one_bad_batch_does_not_kill_a_later_good_batch():
    """If batch 1 fails (malformed response), batch 2 should still be
    attempted and succeed -- same isolation principle used throughout
    this project."""
    fake_mentions = [{"id": i, "platform": "x", "content_text": f"mention {i}"} for i in range(25)]

    responses = [MagicMock(content=[MagicMock(text="broken")])] + \
                [_fake_response([{"index": i, "sentiment": "neutral", "reasoning": "ok"} for i in range(5)])]

    mock_anthropic_client = MagicMock()
    mock_anthropic_client.messages.create.side_effect = responses

    mock_supabase = MagicMock()
    mock_supabase.table.return_value.select.return_value.is_.return_value.limit.return_value.execute.return_value.data = fake_mentions

    with patch("sentiment_scorer.anthropic.Anthropic", return_value=mock_anthropic_client), \
         patch("sentiment_scorer.get_client", return_value=mock_supabase), \
         patch("sentiment_scorer.BATCH_SIZE", 20):
        updated = ss.run()

    assert updated == 5  # second batch succeeded despite first failing


if __name__ == "__main__":
    test_batch_scoring_parses_real_response_shape()
    test_handles_markdown_wrapped_json()
    test_invalid_sentiment_value_filtered_not_crashed()
    test_malformed_json_returns_empty_not_crash()
    test_run_skips_cleanly_without_api_key()
    test_run_updates_correct_rows_in_supabase()
    test_run_returns_zero_when_nothing_unscored()
    test_one_bad_batch_does_not_kill_a_later_good_batch()
    print("All sentiment scorer tests passed.")
