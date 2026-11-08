#!/usr/bin/env bash
# Pull the latest Tiny Chef from GitHub, run the tests, and restart.
# If the tests fail, it rolls back and keeps the working version running.
# Runs nightly as root (systemd timer) or via `tiny-chef update`.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
OWNER="$(stat -c %U "$APP_DIR")"
as_owner() { if [ "$(whoami)" = "$OWNER" ]; then "$@"; else runuser -u "$OWNER" -- "$@"; fi; }
as_root()  { if [ "$(id -u)" = 0 ]; then "$@"; else sudo "$@"; fi; }

cd "$APP_DIR"
OLD_REV="$(as_owner git rev-parse HEAD)"
as_owner git fetch --quiet origin
NEW_REV="$(as_owner git rev-parse '@{u}')"

if [ "$OLD_REV" = "$NEW_REV" ] && [ "${1:-}" != "--force" ]; then
  echo "Tiny Chef is already up to date ($(as_owner git log -1 --format='%h %s'))."
  exit 0
fi

echo "Updating Tiny Chef:"
as_owner git log --oneline "$OLD_REV..$NEW_REV" || true
rollback() {
  echo "$1; rolling back to the previous version. Details: /tmp/tiny-chef-update.log"
  as_owner git reset --hard --quiet "$OLD_REV"
  as_owner ./venv/bin/pip install -q -r requirements.txt >/dev/null 2>&1 || true
  exit 1
}

as_owner git merge --ff-only --quiet "$NEW_REV"
: > /tmp/tiny-chef-update.log
if ! as_owner git diff --quiet "$OLD_REV" "$NEW_REV" -- requirements.txt; then
  as_owner ./venv/bin/pip install -q -r requirements.txt >>/tmp/tiny-chef-update.log 2>&1 \
    || rollback "Installing new packages failed"
fi
as_owner ./venv/bin/python -m pytest -q tests >>/tmp/tiny-chef-update.log 2>&1 \
  || rollback "New version failed its tests"

as_root systemctl restart tiny-chef
echo "Updated to $(as_owner git log -1 --format='%h %s') and restarted."
