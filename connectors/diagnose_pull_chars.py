"""
diagnose_pull_chars.py — Prints the exact Unicode codepoint of every
character on the two problem lines in pull.txt, so nothing can hide
behind how a terminal happens to render it.

Run with: python diagnose_pull_chars.py
"""

with open("pull.txt", "r", encoding="utf-8") as f:
    lines = f.readlines()

print("=== Line 29 (top episode) -- chars around the dash ===")
line29 = lines[29]
idx = line29.find('Everything"')
segment = line29[idx:idx + 15]
for ch in segment:
    print(f"{ch!r}  U+{ord(ch):04X}")

print()
print("=== Line 41 (date header) -- every char ===")
line41 = lines[41]
for ch in line41:
    print(f"{ch!r}  U+{ord(ch):04X}")
