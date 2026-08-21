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
"""

import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

DA_SUPABASE_URL = os.environ["DA_SUPABASE_URL"]
DA_SUPABASE_SERVICE_KEY = os.environ["DA_SUPABASE_SERVICE_KEY"]

_client: Client | None = None


def get_client() -> Client:
    """Returns a cached Supabase client scoped to the Dani Austin project."""
    global _client
    if _client is None:
        _client = create_client(DA_SUPABASE_URL, DA_SUPABASE_SERVICE_KEY)
    return _client
