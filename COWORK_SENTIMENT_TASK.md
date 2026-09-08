SCHEDULED TASK: Score unscored earned_mentions sentiment

PREREQUISITE (set up once, before scheduling): connect your Supabase
project as a tool/connector in Cowork, scoped to project
yfzczndtafmqvajrjzzv (Dani Austin).

RECOMMENDED CADENCE: Weekly, shortly after the Xpoz sync runs
(Mondays, 06:00 UTC) -- e.g. Monday 08:00 UTC / whatever your local
equivalent is, to give the sync time to finish first.

---

TASK DESCRIPTION (paste this into the scheduled task prompt):

Check the Supabase table `earned_mentions` (project yfzczndtafmqvajrjzzv)
for rows where the `sentiment` column is null. If there are none, stop
here -- nothing else to do.

For each unscored row, read the `content_text` and `platform` columns
and classify the sentiment of that mention toward Dani Austin (a
lifestyle influencer, podcaster, and founder of the haircare brand
Divi). Use real judgment based on meaning, not keyword matching --
critical or accusatory content doesn't always contain obviously
negative words (e.g. an accusation of appropriating someone else's
business idea "for profit and self-preservation" is negative even
though it contains no words like "hate" or "bad"). Some Reddit content
in particular is drawn from an influencer-commentary/snark community
and should be read for its real critical or mocking tone, not just its
surface politeness.

Classify each row into exactly one of these four categories (matching
the database's check constraint -- no other value will be accepted):
- "positive"
- "negative"
- "neutral" -- for factual, promotional-neutral, or unrelated content
  (including name collisions with other people also named Dani, Austin,
  or Dani Austin)
- "mixed" -- for content that is explicitly both critical and
  sympathetic, or ambiguous/sarcastic in a way that doesn't clearly
  land as positive or negative

For each row, also write a real, specific reasoning string (under 15
words) explaining that particular classification -- not a generic
label repeated across rows.

Write the results back to Supabase: update each scored row's
`sentiment` and `sentiment_reasoning` columns, matched by its `id`.
Do not modify any other columns. Do not touch rows that already have a
non-null `sentiment` value.

If there are more than 50 unscored rows, process all of them in this
same run rather than stopping partway -- there's no need to split this
across multiple scheduled runs.

At the end, report how many rows were scored, and give a brief
sentiment breakdown (count of positive/negative/neutral/mixed) for
this run.
