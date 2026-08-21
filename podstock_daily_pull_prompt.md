# Podstock Daily Data Pull — Claude in Chrome Scheduled Task Prompt

Copy the block below into Claude in Chrome, verify it works correctly by
running it manually once, THEN convert it to a scheduled daily task.

---

## PROMPT

You are logged into Podstock (podstock.io) for the Dani Austin podcast. If
you are not currently logged in, STOP and report that a manual login is
needed — do not attempt to enter credentials yourself.

Navigate through the dashboard and extract the following data exactly as
displayed. Do not round, estimate, or infer any number — if a figure is
not visible or a section fails to load, explicitly say so rather than
guessing or leaving it blank.

Report your findings in the exact structured format below, with today's
date at the top.

### 1. Overview section
- Total delivery (with % change vs. prior period)
- Breakdown by platform: Spotify Streams, Megaphone Downloads, YouTube
  Views, Art19 Downloads (each with their own % change)
- Total hours spent (with % change), broken down by platform: Spotify,
  Apple, YouTube
- Time spent per delivery (with % change)
- New releases vs. back catalog split, for both delivery and hours
- Engagements: total, Likes, Comments, Shares (each with % change)
- Engagement rate, positive reaction rate, sharing rate, comment rate
  (each with % change)

### 2. Episodes section
- Total episode count (all-time)
- Average delivery per episode
- Platform split percentages (Spotify Streams / Downloads / YouTube Views)
- The single top-performing recent episode: its title and total delivery
  number

### 3. Channels section
- Total followers (with % change)
- Per-platform followers/subscribers: Spotify, Apple, YouTube (each with
  % change)
- Number of active channel connections

### 4. Schedule section
- List any ad-slot bookings visible for the NEXT 30 days only (not the
  full calendar) — brand name, slot type (Host Read / Custom Segment /
  etc.), and whether it's booked or still "Available"

### 5. Audience section
- Age breakdown (all age brackets shown, with % of total delivery each)
- Gender breakdown
- Country breakdown (all countries shown, with % each)

## Output format

Present the results as a single clean data block, structured exactly like
this (fill in real numbers, do not use placeholder text):

```
PODSTOCK DAILY PULL — [DATE]

OVERVIEW
Total delivery: [number] ([%change])
  Spotify Streams: [number] ([%change])
  Megaphone Downloads: [number] ([%change])
  YouTube Views: [number] ([%change])
  Art19 Downloads: [number] ([%change])
Total hours: [number] ([%change])
  Spotify: [number] ([%change])
  Apple: [number] ([%change])
  YouTube: [number] ([%change])
Time per delivery: [value] ([%change])
New vs. back catalog — delivery: [new]/[back], hours: [new]/[back]
Engagements total: [number] ([%change])
  Likes: [number] ([%change])
  Comments: [number] ([%change])
  Shares: [number] ([%change])
Engagement rate: [%] ([%change])
Positive reaction rate: [%] ([%change])
Sharing rate: [%] ([%change])
Comment rate: [%] ([%change])

EPISODES
Total episodes: [number]
Avg delivery/episode: [number]
Platform split: Spotify [%]/[number], Downloads [%]/[number], YouTube [%]/[number]
Top recent episode: "[title]" — [number] total delivery

CHANNELS
Total followers: [number] ([%change])
  Spotify: [number] ([%change])
  Apple: [number] ([%change])
  YouTube: [number] ([%change])
Active connections: [number]

SCHEDULE (next 30 days)
[Brand] — [slot type] — [Booked/Available] — [date if shown]
[repeat per booking]

AUDIENCE
Age: [bracket]: [%], [bracket]: [%], ...
Gender: Female [%], Male [%]
Country: [country]: [%], [country]: [%], ...
```

## Critical instructions

- If ANY section fails to load or a login/CAPTCHA/session-expired screen
  appears, STOP immediately and report exactly what you see — do not
  attempt to log in, solve a CAPTCHA, or guess at values.
- If a metric shown today is identical to a previous pull, still report it
  — do not assume it's a stale/cached page and skip it.
- Do not editorialize, summarize trends, or add commentary — output the
  structured data block only. Analysis happens downstream, not here.
- If Podstock's dashboard layout has visibly changed since this prompt was
  written (different section names, moved elements), report the new
  layout you see rather than forcing the old structure onto it.
