# Run Tiny Chef free on Google Cloud

About 30 minutes. You'll need a browser, a credit card (Google requires one; you
won't be charged with these settings), and Telegram on your phone.

## Before you start: two keys

1. **Telegram bot token.** In Telegram, message **@BotFather** → `/newbot` → pick
   a name and a username ending in `bot`. Copy the token.
2. **Anthropic API key.** console.anthropic.com → **Billing**: add a few dollars of
   credit (each weekly plan costs a few cents) → **API Keys** → **Create Key**.

## Step 1: Google Cloud account and $1 alert

1. cloud.google.com/free → **Get started for free**.
2. Search **Budgets & alerts** → **Create budget** → Amount **$1** → **Finish**.

## Step 2: Create the free server

**VM instances** → **Create instance**:

| Setting | Value |
|---|---|
| Region | **us-west1 (Oregon)** (us-central1 / us-east1 also free) |
| Machine type | **E2 → e2-micro** |
| Boot disk | **Debian 12**, **Standard persistent disk**, 10–30 GB |
| Data protection | **No backups** (snapshot schedules cost money) |
| Observability | **uncheck Install Ops Agent** |
| Firewall | leave unchecked |
| Networking | default (ephemeral IP, free). Don't reserve a static IP |

The cost panel shows ~$6/month; that's the list price before the free-tier discount.

## Step 3: Connect the server to GitHub (one time)

Click **SSH** next to the server. In the terminal that opens, paste:

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519 -C tiny-chef-server -q <<< y >/dev/null; ssh-keyscan github.com >> ~/.ssh/known_hosts 2>/dev/null; cat ~/.ssh/id_ed25519.pub
```

Copy the line it prints (starts with `ssh-ed25519`). On GitHub, open the
**tiny-chef** repository → **Settings** → **Deploy keys** → **Add deploy key** →
title "Google Cloud server", paste, leave "Allow write access" **unchecked** → **Add key**.

## Step 4: Install

```bash
sudo apt-get install -y git
git clone git@github.com:OWNER/tiny-chef.git
cd tiny-chef && bash install.sh
```
(replace OWNER with your GitHub username)

The installer:
- installs Python and the bot's packages
- moves over your settings and history if an old `mealbot` install exists
- asks for any missing keys and checks the Telegram token works
- has everyone open the bot in Telegram, tap **Start** and send "hi", then saves their chat ids
- runs the bot in the background (starts on boot, restarts if it crashes)
- turns on nightly auto-updates from GitHub
- adds the `tiny-chef` command

## Step 5: Test

```bash
tiny-chef test
```

The plan and grocery list should arrive in Telegram within a minute. Reply with a
swap to try it. You can close the SSH window; Tiny Chef keeps running.

## Day to day

You shouldn't need the server again. New versions arrive overnight on their own.
When you do log in: `tiny-chef help` lists everything (`family`, `logs`, `update`...).

## Troubleshooting

- **Nothing arrives after `tiny-chef test`:** the error prints right there. "credit
  balance is too low" → add credit at console.anthropic.com. Wrong key → `tiny-chef settings`.
- **A family member gets nothing:** their chat id isn't in `RECIPIENTS` (`tiny-chef settings`).
- **`git clone` says "Permission denied (publickey)":** the deploy key from step 3
  isn't added to the repository yet.
- **Budget alert email:** check the server is e2-micro in a free region with a
  standard disk, no snapshots and no static IP.
