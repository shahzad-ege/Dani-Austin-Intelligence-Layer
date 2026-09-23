"""
probe_tiktok_token_structure.py — Tests several real, plausible request
structures against TikTok's /oauth2/access_token/ endpoint using a
deliberately fake auth_code -- safe to run repeatedly, no real
authorization needed.

WHY THIS EXISTS: the exact same vague error ("input data is invalid")
occurred with a real code AND an obviously fake one -- proving the
problem is structural, not code-validity. This tests several real
candidate structures in one run, so the tedious real-authorization
cycle only needs to happen once, against whichever structure actually
works here.

HOW TO READ THE RESULTS: the fake auth_code should always fail -- the
question is HOW it fails. The same vague "invalid input for parameter"
error means the structure itself is still wrong. A DIFFERENT, more
specific error (something naming "auth_code" as invalid/expired/not
found specifically) means the structure is now accepted, and only a
real code was missing.
"""

import os
import requests
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(usecwd=True))

TIKTOK_CLIENT_KEY = os.environ["TIKTOK_CLIENT_KEY"]
TIKTOK_CLIENT_SECRET = os.environ["TIKTOK_CLIENT_SECRET"]

TOKEN_URL = "https://business-api.tiktok.com/open_api/v1.3/oauth2/access_token/"
FAKE_CODE = "obviously_fake_test_value_12345"

CANDIDATES = [
    ("app_id as string (what we just tried)", {
        "app_id": TIKTOK_CLIENT_KEY, "secret": TIKTOK_CLIENT_SECRET, "auth_code": FAKE_CODE,
    }),
    ("app_id as integer", {
        "app_id": int(TIKTOK_CLIENT_KEY), "secret": TIKTOK_CLIENT_SECRET, "auth_code": FAKE_CODE,
    }),
    ("with grant_type='auth_code'", {
        "app_id": TIKTOK_CLIENT_KEY, "secret": TIKTOK_CLIENT_SECRET, "auth_code": FAKE_CODE,
        "grant_type": "auth_code",
    }),
    ("field name 'code' instead of 'auth_code'", {
        "app_id": TIKTOK_CLIENT_KEY, "secret": TIKTOK_CLIENT_SECRET, "code": FAKE_CODE,
    }),
    ("app_id as integer + grant_type='auth_code'", {
        "app_id": int(TIKTOK_CLIENT_KEY), "secret": TIKTOK_CLIENT_SECRET, "auth_code": FAKE_CODE,
        "grant_type": "auth_code",
    }),
]


def main() -> None:
    print(f"Testing {len(CANDIDATES)} real, plausible request structures against")
    print(f"{TOKEN_URL}")
    print(f"using a deliberately fake auth_code -- safe, no real authorization used.\n")

    for label, body in CANDIDATES:
        print(f"=== {label} ===")
        print(f"Body sent: {body}")
        try:
            resp = requests.post(TOKEN_URL, json=body, timeout=15)
            data = resp.json()
            print(f"Response: {data}")

            message = str(data.get("message", "")).lower()
            if "invalid input for" in message or "invalid for the associated parameter" in message:
                print("--> Same vague structural error -- this candidate is still wrong.\n")
            elif "auth_code" in message or "code" in message:
                print("--> DIFFERENT, more specific error mentioning the code itself --")
                print("    this structure looks ACCEPTED. This is likely the real fix.\n")
            else:
                print("--> Different error -- worth reading closely, may indicate progress.\n")
        except requests.RequestException as e:
            print(f"Request failed: {e}\n")

    print("--- Next step ---")
    print("Paste this full output back. Whichever candidate gave a DIFFERENT,")
    print("more specific error (not the vague 'invalid input' one) is the real")
    print("structure -- that's the one worth spending a real authorization on.")


if __name__ == "__main__":
    main()
