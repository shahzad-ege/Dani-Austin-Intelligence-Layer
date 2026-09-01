"""
test_writer_registration.py — Guards against the exact class of bug found
during a full-system regression check: tables written via real
upsert_rows() calls but never registered in CONFLICT_KEYS, which only
fails at actual runtime (unit tests that mock upsert_rows entirely never
catch it). Three tables (podcast_ad_bookings, podcast_audience_demographics,
podcast_top_episode_snapshots) and two more (affiliate_commission_deals,
da_cash_flow_recurring_assumptions -- the latter two only ever written via
direct SQL, never through the real connector code path) were found
missing this way. This test statically scans every connector .py file for
upsert_rows("table_name", ...) calls and confirms each literal table name
found is registered.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import writer  # noqa: E402

CONNECTORS_DIR = os.path.dirname(os.path.dirname(__file__))


def _find_literal_table_names_in_upsert_calls() -> set[str]:
    """
    Scans every .py file in connectors/ for upsert_rows("literal_name", ...)
    calls. Only catches LITERAL string table names (not ones built from a
    variable) -- a static, best-effort check, not a substitute for actually
    running the code, but it catches exactly the class of bug found here.
    """
    found = set()
    for filename in os.listdir(CONNECTORS_DIR):
        if not filename.endswith(".py"):
            continue
        filepath = os.path.join(CONNECTORS_DIR, filename)
        with open(filepath) as f:
            content = f.read()
        for match in re.finditer(r'upsert_rows\(\s*["\']([a-zA-Z_]+)["\']', content):
            found.add(match.group(1))
    return found


def test_every_table_written_via_upsert_rows_is_registered():
    used_tables = _find_literal_table_names_in_upsert_calls()
    registered_tables = set(writer.CONFLICT_KEYS.keys())

    missing = used_tables - registered_tables
    assert not missing, (
        f"These tables are written via upsert_rows() but have NO entry in "
        f"writer.py's CONFLICT_KEYS -- this WILL crash with a ValueError the "
        f"first time real code (not a mocked test) tries to write to them: "
        f"{sorted(missing)}"
    )


if __name__ == "__main__":
    test_every_table_written_via_upsert_rows_is_registered()
    print("Writer registration check passed.")
