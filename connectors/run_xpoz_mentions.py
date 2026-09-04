"""
run_xpoz_mentions.py — Manual one-off runner for Xpoz mentions.

For the actual scheduled daily run, this now goes through run_all.py
like every other connector (registered as "xpoz_earned_mentions"). This
script just calls the same xpoz_connector.run() directly, useful for a
manual re-run without triggering every other connector too.

Run with: python run_xpoz_mentions.py
"""

import xpoz_connector

written = xpoz_connector.run()
print(f"\nWritten to Supabase: {written}")
