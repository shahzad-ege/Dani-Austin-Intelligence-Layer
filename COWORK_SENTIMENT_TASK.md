SCHEDULED TASK: Score unscored earned_mentions sentiment + topic

PREREQUISITE (set up once, before scheduling): connect your Supabase
project as a tool/connector in Cowork, scoped to project
yfzczndtafmqvajrjzzv (Dani Austin).

RECOMMENDED CADENCE: Weekly, shortly after the Xpoz sync runs
(Mondays, 06:00 UTC) -- e.g. Monday 08:00 UTC / whatever your local
equivalent is, to give the sync time to finish first.

CHANGE LOG: originally only scored sentiment. Two real gaps found and
fixed here:
  1. is_substantive was never mentioned in the original task, so
     anything Cowork scored silently defaulted to true (the column's
     default) -- including moderator messages and bare thread titles,
     which quietly eroded a real, confirmed correction (Reddit's true
     negative share is 61% among substantive content, not the 46% the
     unfiltered data shows).
  2. topic tagging added -- sentiment alone doesn't say WHICH real
     narrative is driving a negative reading (appropriation
     accusations vs. parenting criticism vs. wealth envy are very
     different signals to act on).

---

TASK DESCRIPTION (paste this into the scheduled task prompt):

Check the Supabase table `earned_mentions` (project yfzczndtafmqvajrjzzv)
for rows where the `sentiment` column is null. If there are none, stop
here -- nothing else to do.

For each unscored row, read the `content_text` and `platform` columns
and classify THREE things: sentiment, is_substantive, and topic.

=== SENTIMENT ===
Classify the sentiment of the mention toward Dani Austin (a lifestyle
influencer, podcaster, and founder of the haircare brand Divi). Use
real judgment based on meaning, not keyword matching -- critical or
accusatory content doesn't always contain obviously negative words
(e.g. an accusation of appropriating someone else's business idea "for
profit and self-preservation" is negative even though it contains no
words like "hate" or "bad"). Some Reddit content in particular is drawn
from an influencer-commentary/snark community and should be read for
its real critical or mocking tone, not just its surface politeness.

Classify into exactly one of these four values (matching the
database's check constraint -- no other value will be accepted):
- "positive"
- "negative"
- "neutral" -- for factual, promotional-neutral, or unrelated content
- "mixed" -- for content that is explicitly both critical and
  sympathetic, or ambiguous/sarcastic in a way that doesn't clearly
  land as positive or negative

=== IS_SUBSTANTIVE (true/false) ===
Set to false for content that carries no real signal about her, even
though it matched the search:
- Moderator/rules messages, or bare scheduling text with zero added
  commentary (e.g. just "Dani Austin // March 20-26" with nothing else)
- Photo-credit-only posts with no commentary
- Bare name mentions with zero surrounding context
- Name collisions -- a DIFFERENT person also named Dani, Austin, or
  Dani Austin (this is common: a researcher, a soccer player, unrelated
  Instagram accounts, etc. -- read for whether the content actually
  matches the known facts about this Dani Austin specifically: Nashville,
  Divi, Dallas origin, husband tagged @influencerhusband, multiple young
  children)
Set to true for everything else, including neutral factual content
that's genuinely about her (e.g. a Forbes list mention) -- neutral
sentiment and non-substantive are different things; don't conflate them.

=== TOPIC ===
Pick exactly one, the closest fit:
- "press_coverage" -- professional media features (Forbes, Under30Summit, etc.)
- "business_brand" -- Divi/brand content, sponsored posts, product features
- "personal_family" -- her own lifestyle/family content, not clearly any other category
- "birth_parenting_criticism" -- criticism of birth choices, parenting, or her kids
- "authenticity_accusations" -- fake/performative/non-apology criticism
- "appropriation_business_ethics" -- accusations of stealing ideas or exploiting for profit
- "political_labeling" -- political characterization of her
- "wealth_lifestyle_envy" -- criticism or commentary about her house, money, spending
- "routine_administrative" -- moderator messages, bare thread titles (should usually pair with is_substantive=false)
- "name_collision" -- not actually about her (should usually pair with is_substantive=false)
- "other" -- doesn't fit any of the above cleanly

=== WRITING RESULTS BACK ===
Update each scored row's `sentiment`, `sentiment_reasoning`,
`is_substantive`, and `topic` columns, matched by its `id`. Write a
real, specific reasoning string (under 15 words) for the sentiment --
not a generic label repeated across rows. Do not modify any other
columns. Do not touch rows that already have a non-null `sentiment`
value.

If there are more than 50 unscored rows, process all of them in this
same run rather than stopping partway.

At the end, report how many rows were scored, a sentiment breakdown
(count of positive/negative/neutral/mixed), and a topic breakdown for
this run.
