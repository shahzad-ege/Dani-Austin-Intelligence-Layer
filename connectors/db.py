"""
db.py — Supabase client for the Dani Austin spoke.

Reused pattern from the EGE build. Uses the service-role (secret) key so
writes bypass RLS by design — this is the intended path for connectors and
run_all.py. The secret key must NEVER be used in a client-facing context.

Credentials are read from environment variables, sourced from the 1Password
vault at deploy/schedule time — never hardcoded, never committed.

For local testing, this loads a .env file if one exists (via python-dotenv).
In GitHub Actions, no .env file exists, so this is a no-op there — real
values come from repo Secrets instead, injected directly as environment
variables by the workflow.

NOTE: this explicitly finds the path via find_dotenv(usecwd=True) rather
than calling plain load_dotenv(). Plain load_dotenv() tries to locate .env
by inspecting the Python call stack, which becomes unreliable when this
module is loaded several imports deep (brex_connector -> writer -> db, as
happens here) -- it can silently fail to find a real .env file sitting
right there. find_dotenv(usecwd=True) instead searches from the actual
current working directory, which is what every connector script is run
from directly. (load_dotenv() itself has no usecwd parameter in this
version of python-dotenv -- only find_dotenv() does.)
"""

import os
from dotenv import load_dotenv, find_dotenv
from supabase import create_client, Client

load_dotenv(find_dotenv(usecwd=True))

DA_SUPABASE_URL = os.environ["DA_SUPABASE_URL"]
DA_SUPABASE_SERVICE_KEY = os.environ["DA_SUPABASE_SERVICE_KEY"]

_client: Client | None = None


def get_client() -> Client:
    """Returns a cached Supabase client scoped to the Dani Austin project."""
    global _client
    if _client is None:
        _client = create_client(DA_SUPABASE_URL, DA_SUPABASE_SERVICE_KEY)
    return _client
