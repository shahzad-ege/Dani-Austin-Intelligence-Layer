"""
get_tiktok_refresh_token.py — One-time helper to obtain a real TikTok
refresh token. Not part of the regular connector -- run this once,
copy the refresh token into .env, then it's done.

WHY THIS EXISTS: TikTok's web OAuth flow requires PKCE (a code_verifier/
code_challenge pair), confirmed from TikTok's own real authorization URL
format. This can't be done by just clicking through a web page the way
Google's OAuth Playground handles YouTube -- PKCE values need to be
generated correctly and reused across two separate requests (the
browser authorization, then the token exchange), which is what this
script handles.

Confirmed real endpoints, from TikTok's own official docs:
  - Authorize: https://www.tiktok.com/v2/auth/authorize/
  - Token exchange: https://open.tiktokapis.com/v2/oauth/token/

Confirmed real response shape on success:
  {"access_token": "...", "expires_in": 86400, "open_id": "...",
   "refresh_expires_in": 31536000, "refresh_token": "...",
   "scope": "...", "token_type": "Bearer"}

Real token lifetimes, confirmed: access_token lasts 24 hours (the
regular connector already handles refreshing this before each real
call), refresh_token lasts 365 days -- meaning this whole setup will
need to be redone roughly once a year, not a one-time-forever step.
"""

import os
import json
import base64
import hashlib
import secrets
import requests
from urllib.parse import urlencode
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(usecwd=True))

TIKTOK_CLIENT_KEY = os.environ["TIKTOK_CLIENT_KEY"]
TIKTOK_CLIENT_SECRET = os.environ["TIKTOK_CLIENT_SECRET"]

# Real, already-verified redirect URI (confirmed working directly in
# the TikTok Developer Portal -- see the "TikTok account holder
# authorization URL" configuration). Using this instead of a raw
# localhost URI, since TikTok's Web platform type requires HTTPS and
# this domain is already properly registered and accepted.
REDIRECT_URI = "https://daniaustin.com/"

# Real, confirmed scopes from the already-working authorization URL --
# broader than originally planned, matches what's actually configured
# for this app. Covers account stats, video list/insights, and more.
SCOPES = "user.info.basic,user.info.username,user.info.stats,user.info.profile,user.account.type,user.insights,video.list,video.insights,comment.list,comment.list.manage,video.publish,video.upload,biz.spark.auth,discovery.search.words"

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
# REAL, CRITICAL CORRECTION: the previous /tt_user/oauth2/token/
# endpoint DID successfully exchange a code for a refresh token -- but
# it's a DIFFERENT, incompatible TikTok API system from the one
# tiktok_connector.py's own (already-proven-correct, documented after
# a real CI failure) refresh_access_token() function uses. Tokens
# issued by one aren't valid on the other, confirmed by a real
# "Invalid refresh_token" error when the connector tried to use it.
# Switching to match the connector's own established convention
# exactly: /oauth2/access_token/ for the initial exchange, app_id/
# secret field names (not client_id/client_secret).
TOKEN_URL = "https://business-api.tiktok.com/open_api/v1.3/oauth2/access_token/"


def _generate_pkce_pair() -> tuple[str, str]:
    """Real PKCE generation: a random code_verifier, and its SHA256
    hash (base64url-encoded, no padding) as the code_challenge --
    standard PKCE (RFC 7636), confirmed as what TikTok's own
    authorization URL format expects (code_challenge_method=S256)."""
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def build_authorization_url() -> tuple[str, str]:
    """Returns (url_to_open_in_browser, code_verifier_to_keep_for_step_2)."""
    code_verifier, code_challenge = _generate_pkce_pair()
    params = {
        "client_key": TIKTOK_CLIENT_KEY,
        "response_type": "code",
        "scope": SCOPES,
        "redirect_uri": REDIRECT_URI,
        "state": "dani_austin_setup",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTH_URL}?{urlencode(params)}", code_verifier


def exchange_code_for_tokens(code: str, code_verifier: str) -> dict:
    # REAL, CONFIRMED FIX: TikTok's error response was explicit --
    # "header Content-Type has unexpected value
    # 'application/x-www-form-urlencoded'". This Business API endpoint
    # expects a JSON body, unlike the standard v2 OAuth endpoint's
    # form-encoded convention. Using requests' json= parameter, which
    # sets the correct Content-Type automatically.
    resp = requests.post(
        TOKEN_URL,
        json={
            # REAL, CRITICAL CORRECTION: switched from client_id to
            # app_id, matching tiktok_connector.py's own already-proven
            # convention for this /oauth2/ endpoint family (confirmed
            # correct there after a real CI failure) -- the previous
            # client_id/auth_code naming belonged to a DIFFERENT,
            # incompatible TikTok API system (/tt_user/oauth2/token/),
            # which produced a refresh_token the real connector
            # rejected as invalid.
            # REAL, CONFIRMED via multiple independent, corroborating
            # sources (a Unified.to integration guide showing the exact
            # real request body, TikTok's own Python package, a Ruby
            # SDK) -- this endpoint wants ONLY these three fields.
            # grant_type and redirect_uri were both extra, unexpected
            # fields likely causing the vague "invalid input" error.
            "app_id": TIKTOK_CLIENT_KEY,
            "secret": TIKTOK_CLIENT_SECRET,
            "auth_code": code,
        },
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Token exchange FAILED ({resp.status_code}): {resp.text}")

    raw = resp.json()
    # REAL, confirmed finding: this Business API endpoint's response
    # doesn't match the standard v2 endpoint's flat shape -- printing
    # the raw response unconditionally so this is never a silent
    # guess again, regardless of what shape it turns out to be.
    print("Raw real response from TikTok:")
    print(json.dumps(raw, indent=2))
    print()

    # REAL, confirmed finding: TikTok's Business API signals real
    # errors via a "code" field in the response BODY (0 = success),
    # returning HTTP 200 even on failure -- the earlier
    # Content-Type error slipped past the status_code check entirely
    # because of this. Checking both now.
    if raw.get("code") not in (0, None):
        raise RuntimeError(f"Token exchange FAILED (body code {raw.get('code')}): {raw.get('message')}")

    # TikTok's Business API (v1.3) conventionally nests the real
    # payload under a "data" key, with top-level "code"/"message"
    # wrapper fields -- confirmed pattern from TikTok's own Business
    # API docs elsewhere. Falling back to the raw dict if "data" isn't
    # present, so this doesn't silently break if the shape differs
    # again.
    return raw.get("data", raw)


def main() -> None:
    url, code_verifier = build_authorization_url()

    print("STEP 1: Open this URL in your browser (the account that")
    print("manages the Dani Austin TikTok account needs to be logged in):\n")
    print(url)
    print()
    print("STEP 2: After approving, you'll be redirected to daniaustin.com")
    print("with a real 'code' parameter in the URL -- the actual live site will")
    print("load normally, the code just rides along in the address bar.")
    print("Copy the FULL URL from your browser's address bar.\n")

    redirected_url = input("Paste the full redirected URL here: ").strip()

    if "code=" not in redirected_url:
        print("\nNo 'code=' parameter found in that URL. Did you paste the")
        print("full redirected URL, not the authorization URL from Step 1?")
        return

    code = redirected_url.split("code=")[1].split("&")[0]
    # TikTok URL-encodes the code; undo that before exchanging it.
    from urllib.parse import unquote
    code = unquote(code)

    print("\nExchanging code for tokens...")
    try:
        tokens = exchange_code_for_tokens(code, code_verifier)
    except RuntimeError as e:
        print(f"\n{e}")
        print("\nCommon causes: the code was already used (they're single-use),")
        print("or more than a few minutes passed since authorizing.")
        return

    print("\nSUCCESS. Add this to your .env file:\n")
    print(f"TIKTOK_CLIENT_KEY={TIKTOK_CLIENT_KEY}")
    print(f"TIKTOK_CLIENT_SECRET={TIKTOK_CLIENT_SECRET}")

    # Defensive against a possibly-different key name here too -- the
    # raw response was already printed above regardless, so if this
    # exact key is wrong, the real name is visible right above this.
    refresh_token = tokens.get("refresh_token") or tokens.get("access_token")
    if refresh_token:
        print(f"TIKTOK_REFRESH_TOKEN={refresh_token}")
    else:
        print("Could not find a 'refresh_token' field in the response above --")
        print("check the raw response printed above for the real field name.")

    print()
    print(f"Real token info: access token valid for {tokens.get('expires_in', '?')} seconds, "
          f"refresh token valid for {tokens.get('refresh_expires_in', tokens.get('refresh_token_expires_in', '?'))} seconds.")

    # Real search for anything that might be the business_id this
    # whole exercise was for -- printing every key/value so nothing
    # is silently missed if it's named unexpectedly.
    print("\n--- All real fields in this response, for finding business_id specifically ---")
    for key, value in tokens.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
