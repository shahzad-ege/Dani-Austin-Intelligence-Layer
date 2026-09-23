# Megaphone Historical Backfill — Claude in Chrome Task Prompt

Copy the block below into Claude in Chrome. This is a one-time backfill,
not a recurring task — run it once, verify the export(s), then stop.
Unlike the daily Podstock pull, this does NOT need to become a
scheduled task.

---

## PROMPT

You are logged into Megaphone (cms.megaphone.fm) for the Dani Austin /
De-Influenced podcast. If you are not currently logged in, STOP and
report that a manual login is needed — do not attempt to enter
credentials yourself. Login goes through Spotify ("Continue with
Spotify"), so if you land on a Spotify sign-in screen instead of
Megaphone directly, that's expected — wait for the person to confirm
they're signed in before proceeding, don't attempt it yourself.

### Step 1 — Find the real podcast inception date (do not guess)

Before building any report, find out when this podcast's earliest
episode actually published. Navigate to the Episode Manager (or the
episode list within the podcast's settings) and sort or scroll to find
the OLDEST episode. Record its exact publish date — this is the real
start date for the backfill, not an assumed or rounded date.

If you cannot find a reliable earliest-episode date this way, check
whether the Podcast Performance report's own date-range picker shows
the full available history as a hint, and report clearly whether the
date you're using is confirmed from the episode list or inferred from
the date picker — don't present a guess as a confirmed fact.

### Step 2 — Navigate to Report Builder

From the left sidebar, go to Analytics → Report Builder → Custom
reports (not a quick report template — a custom report gives full
control over the date range).

### Step 3 — Build the delivery (downloads) report

Configure:
- **Report type**: Delivery (consumption data) — not Impressions
- **Metrics**: downloads, plays (add both if both are offered as
  separate metrics; if only one exists, use that one and note which)
- **Dimensions**: Episode, and a date dimension set to Day
- **Date range**: custom range, from the real inception date found in
  Step 1, through today
- **Filter**: scope to this one podcast only (De-Influenced), not all
  shows on the network, if a podcast-level filter is available

### Step 4 — Handle a large date range carefully

A multi-year daily-granularity report may be slow to load, may time
out, or may hit an unstated row/size limit — you have no way to know
in advance which of these will happen. Try running the full range
first. If it loads successfully, proceed to Step 5.

If it fails, times out, or the UI shows a truncation warning: **do not
silently accept a partial result.** Instead, split the request into
separate reports by calendar year (e.g., 2020, 2021, 2022... through
the current year) and run/export each year separately. Report clearly
which approach was actually used.

### Step 5 — Export and save

Once the report loads successfully (whether as one full-range report
or split by year), use the Export CSV button for each report you ran.

Save each file with a clear, predictable name so it can be found
afterward:
- Single full-range export: `megaphone_backfill_full_history.csv`
- Year-split exports: `megaphone_backfill_[YEAR].csv` (e.g.,
  `megaphone_backfill_2021.csv`)

Confirm each download actually completed (check the browser's download
indicator or the downloads folder) before moving to the next one —
don't assume a click succeeded just because no error appeared.

### Step 6 — Report back

Do not attempt to summarize or transcribe the CSV's contents into your
response — the files themselves are the deliverable. Instead, report:

- The confirmed (or inferred, clearly labeled as such) inception date
  used as the start of the range
- Whether one full-range export was used, or the range was split by
  year — and if split, how many separate files
- The exact filename(s) saved and roughly how many rows each contains
  (visible in Megaphone's own UI before export, e.g. "12,400 rows")
- Any error, timeout, or truncation encountered along the way, even if
  you worked around it — don't silently omit a problem just because
  you found a way past it

## Output format

```
MEGAPHONE HISTORICAL BACKFILL — [DATE RUN]

Inception date used: [date] (confirmed from episode list / inferred — say which)
Approach: [single full-range export / split by year]
Files saved:
  - [filename] — approx [N] rows
  - [filename] — approx [N] rows
  ...
Issues encountered: [none / describe clearly]
```
