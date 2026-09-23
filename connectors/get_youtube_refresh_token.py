"""
get_youtube_refresh_token.py — One-time helper to obtain a real YouTube
Analytics OAuth refresh token, matching exactly what youtube_connector.py
expects (confirmed from its own code: OAUTH_TOKEN_URL =
"https://oauth2.googleapis.com/token", client_id/client_secret/
refresh_token field names).

WHY A DEDICATED SCRIPT INSTEAD OF GOOGLE'S OAUTH PLAYGROUND: credentials
never leave this machine -- worth doing given the recent real lesson
from the git push-protection incident (a Google OAuth client secret was
caught in a commit). Also fully repeatable with clear diagnostic output,
rather than a manual multi-tab browser walkthrough.

Confirmed real, standard endpoints (Google's OAuth 2.0 is industry-
standard and consistently documented, unlike the TikTok situation this
project worked through earlier):
  - Authorization: https://accounts.google.com/o/oauth2/v2/auth
  - Token exchange: https://oauth2.googleapis.com/token (same URL the
    connector's own refresh call already uses successfully)

The connector's setup instructions specify a "Desktop app" OAuth client
type -- Google requires PKCE for this client type, reused here from the
same, already-proven logic built for the TikTok refresh token script.
"""

import os
import base64
import hashlib
import secrets
import requests
from urllib.parse import urlencode
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(usecwd=True))

YOUTUBE_OAUTH_CLIENT_ID = os.environ["YOUTUBE_OAUTH_CLIENT_ID"]
YOUTUBE_OAUTH_CLIENT_SECRET = os.environ["YOUTUBE_OAUTH_CLIENT_SECRET"]

# Real, standard Google OAuth endpoints -- confirmed consistent with
# youtube_connector.py's own already-working OAUTH_TOKEN_URL.
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"

# Desktop app clients use a loopback redirect -- confirmed valid per
# Google's own OAuth docs for this client type, and matches the
# connector's own setup instructions ("Desktop app" client type).
REDIRECT_URI = "http://localhost:8080/callback"

# Real, confirmed scope for YouTube Analytics (retention/traffic
# sources) -- the specific API this OAuth flow exists for, per the
# connector's own comment ("For the Analytics API... OAuth is required").
SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"


def _generate_pkce_pair() -> tuple[str, str]:
    """Same proven PKCE generation used for the TikTok refresh token
    script -- standard PKCE (RFC 7636), required by Google for
    Desktop app OAuth clients."""
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def build_authorization_url() -> tuple[str, str]:
    code_verifier, code_challenge = _generate_pkce_pair()
    params = {
        "client_id": YOUTUBE_OAUTH_CLIENT_ID,
        "response_type": "code",
        "scope": SCOPE,
        "redirect_uri": REDIRECT_URI,
        "access_type": "offline",  # required to receive a refresh_token, not just an access_token
        "prompt": "consent",  # forces a real refresh_token on every run, even if previously authorized
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTH_URL}?{urlencode(params)}", code_verifier


def exchange_code_for_tokens(code: str, code_verifier: str) -> dict:
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": YOUTUBE_OAUTH_CLIENT_ID,
            "client_secret": YOUTUBE_OAUTH_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
            "code_verifier": code_verifier,
        },
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Token exchange FAILED ({resp.status_code}): {resp.text}")
    return resp.json()


def main() -> None:
    url, code_verifier = build_authorization_url()

    print("STEP 1: Open this URL in your browser (signed in as the account")
    print("that owns/manages the Dani Austin YouTube channel):\n")
    print(url)
    print()
    print("STEP 2: After approving, you'll be redirected to a URL starting")
    print(f"with {REDIRECT_URI} -- it will show an error page (nothing is")
    print("actually running on that port), but the URL itself is what we need.")
    print("Copy the FULL URL from your browser's address bar.\n")

    redirected_url = input("Paste the full redirected URL here: ").strip()

    if "code=" not in redirected_url:
        print("\nNo 'code=' parameter found in that URL. Did you paste the")
        print("full redirected URL, not the authorization URL from Step 1?")
        return

    from urllib.parse import unquote
    code = unquote(redirected_url.split("code=")[1].split("&")[0])

    print("\nExchanging code for tokens...")
    try:
        tokens = exchange_code_for_tokens(code, code_verifier)
    except RuntimeError as e:
        print(f"\n{e}")
        print("\nCommon causes: the code was already used (they're single-use),")
        print("more than a few minutes passed since authorizing, or the")
        print(f"redirect URI registered in Google Cloud Console doesn't exactly")
        print(f"match {REDIRECT_URI} (check APIs & Services -> Credentials ->")
        print("your OAuth client -> Authorized redirect URIs).")
        return

    print("\nRaw real response from Google:")
    import json
    print(json.dumps(tokens, indent=2))

    if "refresh_token" not in tokens:
        print("\nNo refresh_token in the response -- this usually means the")
        print("account already authorized this app before, and Google only")
        print("issues a refresh_token on the FIRST consent. Since this script")
        print("already sets prompt=consent to force a fresh one, if this still")
        print("happens, try revoking existing access at")
        print("https://myaccount.google.com/permissions first, then re-run.")
        return

    print("\nSUCCESS. Add this to your .env file:\n")
    print(f"YOUTUBE_OAUTH_CLIENT_ID={YOUTUBE_OAUTH_CLIENT_ID}")
    print(f"YOUTUBE_OAUTH_CLIENT_SECRET={YOUTUBE_OAUTH_CLIENT_SECRET}")
    print(f"YOUTUBE_OAUTH_REFRESH_TOKEN={tokens['refresh_token']}")
    print(f"\nAccess token valid for {tokens.get('expires_in', '?')} seconds "
          f"(refreshed automatically by the connector); Google refresh tokens "
          f"for Desktop app clients don't expire on a fixed schedule the way "
          f"TikTok's does, but can be revoked manually or by inactivity.")


if __name__ == "__main__":
    main()
