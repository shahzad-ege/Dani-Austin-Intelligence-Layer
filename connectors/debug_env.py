"""
debug_env.py — Run this directly to diagnose why .env isn't loading.

    python debug_env.py

Put this in the same connectors/ folder as db.py and run it from there.
"""

import os
import sys

print("=" * 60)
print("1. Current working directory:")
print(" ", os.getcwd())

print("\n2. Files in this directory:")
for f in os.listdir("."):
    print(" ", repr(f))  # repr() reveals hidden extensions like .env.txt

print("\n3. Is python-dotenv installed?")
try:
    import dotenv
    print("  YES —", dotenv.__file__)
except ImportError as e:
    print("  NO —", e)
    print("  FIX: python -m pip install python-dotenv")
    sys.exit(1)

print("\n4. Can dotenv actually FIND a .env file from here?")
found_path = dotenv.find_dotenv(usecwd=True)
if found_path:
    print("  FOUND at:", found_path)
else:
    print("  NOT FOUND. dotenv searched upward from this folder and found nothing named '.env'.")
    print("  This is almost certainly the problem. Check the filename in section 2 above")
    print("  for anything like '.env.txt' — Windows often hides the real extension.")

print("\n5. Loading it now and checking the actual value...")
dotenv.load_dotenv(found_path if found_path else None)
value = os.environ.get("DA_SUPABASE_URL")
if value:
    print("  SUCCESS — DA_SUPABASE_URL =", value)
else:
    print("  STILL MISSING after load_dotenv(). If section 4 found a file, open it and")
    print("  confirm the line reads exactly: DA_SUPABASE_URL=https://... (no quotes, no spaces")
    print("  around the =, no leading 'export', not commented out with a leading #).")

print("=" * 60)
