#!/usr/bin/env bash
# Tiny Chef setup for a Debian/Ubuntu server (e.g. Google Cloud e2-micro).
# Run from inside the cloned tiny-chef folder:   bash install.sh
# Safe to re-run. Keeps your .env, family.json and history.
# If an old ~/mealbot install exists, its settings and history are moved over.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"
ENV_FILE="$APP_DIR/.env"
PY="$APP_DIR/venv/bin/python"
ME="$(whoami)"

say() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }

set_env() {  # set_env KEY VALUE  (adds or replaces a line in .env)
  local key="$1" val="$2"
  touch "$ENV_FILE"
  grep -v "^${key}=" "$ENV_FILE" > "$ENV_FILE.tmp" || true
  echo "${key}=${val}" >> "$ENV_FILE.tmp"
  mv "$ENV_FILE.tmp" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
}

get_env() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- || true; }

# --- Move over an old Mealbot install -------------------------------------
OLD="$HOME/mealbot"
if [ -d "$OLD" ] && [ "$OLD" != "$APP_DIR" ]; then
  say "Found old Mealbot install in $OLD, moving your settings and history"
  [ -f "$ENV_FILE" ] || { [ -f "$OLD/.env" ] && cp "$OLD/.env" "$ENV_FILE"; } || true
  [ -f family.json ] || { [ -f "$OLD/family.json" ] && cp "$OLD/family.json" family.json; } || true
  [ -f tinychef.db ] || { [ -f "$OLD/mealbot.db" ] && cp "$OLD/mealbot.db" tinychef.db; } || true
  if systemctl list-unit-files mealbot.service >/dev/null 2>&1; then
    sudo systemctl disable --now mealbot 2>/dev/null || true
    sudo rm -f /etc/systemd/system/mealbot.service
  fi
  mv "$OLD" "$HOME/mealbot-old-backup"
  echo "Old folder kept as ~/mealbot-old-backup (delete it whenever you like)."
fi

say "Installing system tools (needs sudo)"
sudo apt-get update -qq
sudo apt-get install -y -qq git python3 python3-venv python3-pip tzdata >/dev/null

say "Creating Python environment"
[ -d venv ] || python3 -m venv venv
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q -r requirements.txt

[ -f family.json ] || { cp family.example.json family.json; echo "Created family.json from the example. Edit it with: tiny-chef family"; }

say "Settings"
set_env CHANNEL telegram
if [ -z "$(get_env ANTHROPIC_API_KEY)" ]; then
  read -rsp "Paste your Anthropic API key (starts with sk-ant-, hidden as you paste): " k; echo
  set_env ANTHROPIC_API_KEY "$k"
fi
if [ -z "$(get_env TELEGRAM_BOT_TOKEN)" ]; then
  read -rsp "Paste your Telegram bot token from BotFather (hidden): " t; echo
  set_env TELEGRAM_BOT_TOKEN "$t"
fi
[ -n "$(get_env TIMEZONE)" ] || set_env TIMEZONE America/Los_Angeles

say "Checking the bot token"
if ! "$PY" - <<'EOF'
import requests, sys
from tinychef.config import Config
r = requests.get(f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/getMe", timeout=20).json()
if not r.get("ok"):
    print("Telegram rejected the token:", r.get("description")); sys.exit(1)
print("Connected to bot @" + r["result"]["username"])
EOF
then
  echo "Fix TELEGRAM_BOT_TOKEN with: tiny-chef settings   (or nano .env), then re-run: bash install.sh"; exit 1
fi

if [ -z "$(get_env RECIPIENTS)" ]; then
  say "Add your family"
  echo "Everyone who should get the meal plan: open your bot in Telegram, tap Start, and send 'hi'."
  read -rp "Press Enter once everyone has sent a message... " _
  OUT="$("$PY" -m tinychef telegram-whoami)"
  echo "$OUT"
  IDS="$(echo "$OUT" | grep '^RECIPIENTS=' | cut -d= -f2- || true)"
  if [ -z "$IDS" ]; then
    echo "No messages found yet. Re-run 'bash install.sh' after everyone has messaged the bot."; exit 1
  fi
  read -rp "Use these people? [Y/n] " ok
  if [[ "${ok:-Y}" =~ ^[Yy]$ ]]; then set_env RECIPIENTS "$IDS"; else
    echo "Edit RECIPIENTS in .env yourself, then re-run: bash install.sh"; exit 1
  fi
fi

say "Installing the tiny-chef command"
sudo tee /usr/local/bin/tiny-chef >/dev/null <<EOF
#!/usr/bin/env bash
exec bash "$APP_DIR/tiny-chef.sh" "\$@"
EOF
sudo chmod +x /usr/local/bin/tiny-chef

say "Installing background service (starts on boot, restarts if it crashes)"
sudo tee /etc/systemd/system/tiny-chef.service >/dev/null <<EOF
[Unit]
Description=Tiny Chef family meal planner
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$APP_DIR
ExecStart=$PY -m tinychef telegram-poll
Restart=always
RestartSec=10
User=$ME

[Install]
WantedBy=multi-user.target
EOF

say "Installing nightly auto-update (3:30am)"
sudo tee /etc/systemd/system/tiny-chef-update.service >/dev/null <<EOF
[Unit]
Description=Update Tiny Chef from GitHub

[Service]
Type=oneshot
ExecStart=/bin/bash $APP_DIR/update.sh
EOF
sudo tee /etc/systemd/system/tiny-chef-update.timer >/dev/null <<EOF
[Unit]
Description=Nightly Tiny Chef update

[Timer]
OnCalendar=*-*-* 03:30:00 America/Los_Angeles
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now tiny-chef-update.timer
sudo systemctl enable tiny-chef
sudo systemctl restart tiny-chef
sleep 3
systemctl --no-pager --lines=5 status tiny-chef || true

say "Done! Tiny Chef is running."
cat <<'EOF'
It sends the plan every Saturday at 7pm Pacific and updates itself every night.

  tiny-chef test       send a plan right now
  tiny-chef update     pull the latest version now
  tiny-chef logs       watch what it's doing (Ctrl-C to stop)
  tiny-chef help       all commands
EOF
