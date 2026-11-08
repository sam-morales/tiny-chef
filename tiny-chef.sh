#!/usr/bin/env bash
# The `tiny-chef` command (installed to /usr/local/bin by install.sh).
set -euo pipefail
APP_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$APP_DIR"

case "${1:-help}" in
  update)   sudo bash "$APP_DIR/update.sh" "${@:2}" ;;
  test|send-now) ./venv/bin/python -m tinychef send-now && echo "Sent. Check Telegram." ;;
  logs)     journalctl -u tiny-chef -f ;;
  status)   systemctl --no-pager status tiny-chef; echo; git log -1 --format='Version: %h %s (%cr)' ;;
  restart)  sudo systemctl restart tiny-chef && echo "Restarted." ;;
  family)   nano family.json && sudo systemctl restart tiny-chef && echo "Saved and restarted." ;;
  settings) nano .env && sudo systemctl restart tiny-chef && echo "Saved and restarted." ;;
  stop)     sudo systemctl stop tiny-chef && echo "Stopped (run 'tiny-chef restart' to start again)." ;;
  *) cat <<'EOF'
tiny-chef commands:
  test       send a meal plan right now
  update     get the latest version from GitHub (also happens nightly)
  logs       watch what it's doing (Ctrl-C to stop)
  status     is it running, and which version
  family     edit your family profile (family.json)
  settings   edit keys and family list (.env)
  restart    restart the bot
  stop       stop the bot
EOF
  ;;
esac
