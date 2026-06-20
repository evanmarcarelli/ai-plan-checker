#!/usr/bin/env bash
#
# ship.sh — take your current changes from a branch all the way into main,
# in one command: branch -> commit -> push -> open PR -> merge -> sync main.
#
# USAGE
#   bash scripts/ship.sh "your commit message"
#   bash scripts/ship.sh --no-merge "message"      # open the PR but stop for review
#   bash scripts/ship.sh --branch my-name "message"
#   bash scripts/ship.sh --help
#
# It commits ALL current changes (tracked + new files). Run it from anywhere
# inside the repo. Requires the GitHub CLI (gh); it borrows your existing git
# login automatically, so you don't need to run `gh auth login`.
#
set -euo pipefail

BASE="main"
BRANCH=""
DO_MERGE=1

# ----- parse arguments -------------------------------------------------------
MSG=""
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help)
      sed -n '2,20p' "$0"; exit 0 ;;
    --no-merge)   DO_MERGE=0; shift ;;
    --branch)     BRANCH="${2:-}"; shift 2 ;;
    --base)       BASE="${2:-}"; shift 2 ;;
    -*)
      echo "Unknown option: $1" >&2; exit 2 ;;
    *)
      MSG="$1"; shift ;;
  esac
done

if [ -z "$MSG" ]; then
  echo "ERROR: you must give a commit message, e.g.:" >&2
  echo "  bash scripts/ship.sh \"fix the login button\"" >&2
  exit 2
fi

# ----- move to the repo root -------------------------------------------------
ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "ERROR: not inside a git repository." >&2; exit 1; }
cd "$ROOT"

# ----- locate gh (PATH first, then the default Windows install) --------------
if command -v gh >/dev/null 2>&1; then
  GH="gh"
elif [ -x "/c/Program Files/GitHub CLI/gh.exe" ]; then
  GH="/c/Program Files/GitHub CLI/gh.exe"
else
  echo "ERROR: GitHub CLI (gh) not found. Install it with: winget install GitHub.cli" >&2
  exit 1
fi

# ----- make sure gh can talk to GitHub ---------------------------------------
# If gh isn't logged in, borrow the token git already uses for this repo.
if ! "$GH" auth status >/dev/null 2>&1; then
  GH_TOKEN="$(printf 'protocol=https\nhost=github.com\n\n' \
              | git credential fill 2>/dev/null | sed -n 's/^password=//p')"
  if [ -z "${GH_TOKEN:-}" ]; then
    echo "ERROR: gh is not logged in and no saved GitHub token was found." >&2
    echo "Fix: run 'gh auth login' once, then re-run this script." >&2
    exit 1
  fi
  export GH_TOKEN
fi

# ----- is there anything to ship? -------------------------------------------
if [ -z "$(git status --porcelain)" ]; then
  echo "Nothing to ship — your working tree is clean (no changed files)." >&2
  exit 0
fi

# ----- decide the branch name ------------------------------------------------
CURRENT="$(git rev-parse --abbrev-ref HEAD)"
if [ -z "$BRANCH" ]; then
  if [ "$CURRENT" != "$BASE" ]; then
    BRANCH="$CURRENT"            # already on a feature branch — reuse it
  else
    # slugify the message into a branch name: lowercase, spaces->dashes, trim
    BRANCH="$(printf '%s' "$MSG" \
      | tr '[:upper:]' '[:lower:]' \
      | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//' \
      | cut -c1-40)"
    [ -z "$BRANCH" ] && BRANCH="change"
  fi
fi

echo "==> Repo:    $ROOT"
echo "==> Base:    $BASE"
echo "==> Branch:  $BRANCH"
echo "==> Message: $MSG"
echo

# ----- create / switch to the branch ----------------------------------------
if [ "$CURRENT" = "$BASE" ]; then
  # refresh base, then branch off it (carries the uncommitted changes along)
  git pull --ff-only origin "$BASE" >/dev/null 2>&1 || true
  if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    git checkout "$BRANCH"
  else
    git checkout -b "$BRANCH"
  fi
fi

# ----- commit ----------------------------------------------------------------
git add -A
git commit -m "$MSG" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"

# ----- push ------------------------------------------------------------------
git push -u origin "$BRANCH"

# ----- open the PR -----------------------------------------------------------
PR_URL="$("$GH" pr create --base "$BASE" --head "$BRANCH" --title "$MSG" --fill 2>/dev/null \
          || "$GH" pr view "$BRANCH" --json url --jq .url)"
echo "==> Pull request: $PR_URL"

# ----- merge (unless --no-merge) --------------------------------------------
if [ "$DO_MERGE" -eq 1 ]; then
  "$GH" pr merge "$BRANCH" --merge --delete-branch
  git checkout "$BASE" >/dev/null 2>&1
  git pull --ff-only origin "$BASE" >/dev/null 2>&1 || true
  echo
  echo "✅ Merged into $BASE and synced locally. $BASE is now live."
else
  echo
  echo "📝 PR opened but NOT merged (--no-merge). Review it, then run:"
  echo "   $GH pr merge $BRANCH --merge --delete-branch"
fi
