#!/usr/bin/env bash
# Check out / publish the `whoop-data` branch (encrypted tokens + data) in ./state.
#   scripts/data-branch.sh checkout   # create ./state from origin/whoop-data (or a new orphan branch)
#   scripts/data-branch.sh push "msg" # commit ./state and push it
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
BRANCH=whoop-data

case "${1:-}" in
  checkout)
    rm -rf state && git worktree prune
    if git fetch --quiet origin "$BRANCH" 2>/dev/null; then
      git worktree add --quiet -B "$BRANCH" state "origin/$BRANCH"
    else
      git worktree add --quiet --orphan -b "$BRANCH" state
    fi
    ;;
  push)
    cd state
    git add -A
    if git diff --cached --quiet; then
      echo "No changes."
      exit 0
    fi
    git -c user.name="whoop-bot" -c user.email="whoop-bot@users.noreply.github.com" \
      commit --quiet -m "${2:-sync}"
    for i in 1 2 3 4; do
      git push --quiet origin "$BRANCH" && exit 0
      sleep $((2 ** i))
    done
    exit 1
    ;;
  *)
    echo "usage: $0 checkout|push [message]" >&2
    exit 2
    ;;
esac
