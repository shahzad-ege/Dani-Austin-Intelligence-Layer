"""
git_sync.py — Check and sync this repo's local changes to GitHub.

Built specifically to prevent the exact problem we just hit: a local fix
(Social Blade's handles) got corrected on this machine but never committed,
so GitHub Actions kept running stale code indefinitely with no visible
warning that local and remote had diverged.

USAGE:
    python git_sync.py status   # see what's different, change nothing
    python git_sync.py push     # commit + push, with a confirmation step
    python git_sync.py pull     # pull the latest from GitHub

Run this from anywhere inside the repo (it finds the repo root itself).
Requires git to be installed and already authenticated (same login you
used for your first push).
"""

import subprocess
import sys


def run(cmd: list[str], check: bool = True) -> str:
    """Runs a git command, returns its stdout. Prints stderr on failure."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"[git_sync] Command failed: {' '.join(cmd)}")
        print(result.stderr)
        sys.exit(1)
    return result.stdout.strip()


def run_interactive(cmd: list[str]) -> None:
    """
    For commands that may need to prompt for credentials (push, pull) --
    does NOT capture output. This is the actual fix for a real bug: the
    original version used capture_output=True for every command, including
    push. That redirects stdin/stdout/stderr through Python instead of the
    real terminal, so when git needed to show a credential prompt (e.g. a
    Git Credential Manager popup, or a username/token prompt), it had
    nowhere to display it and failed with a cryptic
    "/dev/tty: No such device or address" error -- even though the commit
    itself had already succeeded. Letting git talk directly to the real
    terminal fixes this.
    """
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"[git_sync] Command failed: {' '.join(cmd)}")
        sys.exit(1)


def get_repo_root() -> str:
    return run(["git", "rev-parse", "--show-toplevel"])


def status() -> None:
    """
    Shows exactly what's different between this machine and what's
    committed -- both uncommitted local changes AND how far ahead/behind
    the remote this branch is. Changes nothing.
    """
    root = get_repo_root()
    print(f"[git_sync] Repo: {root}\n")

    # Uncommitted changes (modified, staged, or untracked files)
    changed = run(["git", "status", "--porcelain"], check=False)
    if changed:
        print("UNCOMMITTED CHANGES (exist locally, not yet committed):")
        for line in changed.splitlines():
            print(f"  {line}")
    else:
        print("No uncommitted changes -- working directory is clean.")

    print()

    # How far ahead/behind the remote
    run(["git", "fetch"], check=False)
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], check=False)
    counts = run(["git", "rev-list", "--left-right", "--count", f"{branch}...origin/{branch}"], check=False)
    if counts:
        ahead, behind = counts.split("\t") if "\t" in counts else (counts, "0")
        if ahead != "0":
            print(f"You have {ahead} commit(s) NOT yet pushed to GitHub.")
        if behind != "0":
            print(f"GitHub has {behind} commit(s) you don't have locally yet -- consider 'pull'.")
        if ahead == "0" and behind == "0":
            print("Local and GitHub are in sync.")


def push() -> None:
    """Stages, commits, and pushes -- with a visible diff and a confirmation
    step before anything is actually sent, since this is the action that
    actually changes what GitHub Actions runs."""
    changed = run(["git", "status", "--porcelain"], check=False)
    if not changed:
        print("[git_sync] Nothing to commit -- working directory is already clean.")
        return

    print("The following files have changed:\n")
    print(changed)
    print()

    confirm = input("Commit and push these changes? [y/N]: ").strip().lower()
    if confirm != "y":
        print("[git_sync] Cancelled -- nothing was committed or pushed.")
        return

    message = input("Commit message (blank = 'Update connectors'): ").strip()
    if not message:
        message = "Update connectors"

    run(["git", "add", "."])
    run(["git", "commit", "-m", message])
    run_interactive(["git", "push"])
    print("\n[git_sync] Pushed successfully.")


def pull() -> None:
    """Pulls the latest from GitHub into this machine."""
    changed = run(["git", "status", "--porcelain"], check=False)
    if changed:
        print("[git_sync] You have uncommitted local changes. Commit or stash them")
        print("           before pulling, or they may conflict with incoming changes:")
        print(changed)
        confirm = input("Continue anyway? [y/N]: ").strip().lower()
        if confirm != "y":
            print("[git_sync] Cancelled.")
            return

    run_interactive(["git", "pull"])


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("status", "push", "pull"):
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]
    if command == "status":
        status()
    elif command == "push":
        push()
    elif command == "pull":
        pull()
