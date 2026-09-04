-- ============================================================
-- Migration 020: Sentiment scoring for earned_mentions
-- ============================================================
--
-- Closes the sentiment gap accepted when Xpoz (free, raw mentions) was
-- chosen over paid tools like Brand24/Awario that include sentiment
-- built in. Scored via sentiment_scorer.py, batching mentions into
-- Claude calls rather than one call per mention.
alter table earned_mentions add column if not exists sentiment text;
alter table earned_mentions add column if not exists sentiment_reasoning text;
alter table earned_mentions add constraint earned_mentions_sentiment_check
  check (sentiment is null or sentiment in ('positive', 'negative', 'neutral', 'mixed'));
