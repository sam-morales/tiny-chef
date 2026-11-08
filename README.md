# Tiny Chef 🍳 — weekly family meal prep over Telegram

Every Saturday at 7pm, Tiny Chef messages your family 5 meals for the coming week
plus one combined grocery list. Reply in plain English to swap meals ("swap 2 and 4
for something vegetarian", "no fish this week") and it rewrites just those meals and
re-sends the updated plan and grocery list to everyone.

## How it works

```
Saturday 7pm ──► Claude plans the week (family.json + learned preferences,
                 avoiding the last 4 weeks of meals)
             ──► grocery list built in code from every meal's ingredients
             ──► sent to everyone in RECIPIENTS

You reply ──► commands (RECIPE 3, PREP, LIST, NEW, HELP) answered directly
          ──► anything else = swap request → only the named meals change
          ──► grocery list rebuilt → updated plan sent to the whole family
          ──► lasting likes/dislikes ("we're sick of salmon") remembered
```

## Chat commands

| Reply | What happens |
|---|---|
| any sentence | swap/adjust meals, e.g. "swap 3 for a slow cooker meal" |
| `RECIPE 2` | full ingredients and steps for meal 2 |
| `PREP` | prep-day plan covering all meals |
| `LIST` | resend meals + grocery list |
| `NEW` | a completely new plan |
| `PREFS` / `FORGET` | see / clear what it has learned |
| `HELP` | this list |

## Server commands

Setup: see **SETUP-GOOGLE-CLOUD.md** (free Google Cloud server + `bash install.sh`).
After that, on the server:

| Command | What it does |
|---|---|
| `tiny-chef test` | send a meal plan right now |
| `tiny-chef update` | pull the latest version from GitHub now |
| `tiny-chef logs` | watch what it's doing (Ctrl-C to stop) |
| `tiny-chef status` | is it running, and which version |
| `tiny-chef family` | edit your family profile |
| `tiny-chef settings` | edit API keys and family list (.env) |
| `tiny-chef restart` / `stop` | restart / stop the bot |

## Updates

The server checks GitHub every night at 3:30am Pacific. When there's a new version
it pulls it, runs the tests, and restarts. If the tests or package install fail, it
rolls back automatically and keeps the working version running. To update right
away: `tiny-chef update`.

Your private files are never in git and are never touched by updates: `.env` (keys,
family chat ids), `family.json` (your profile; `family.example.json` is the template)
and `tinychef.db` (history and learned preferences).

## Code layout

`tinychef/service.py` core logic · `planner.py` Claude prompts + JSON schemas ·
`grocery.py` list merging · `messages.py` text formatting · `channels.py`
Telegram / Twilio / console · `telegram_poll.py` Telegram without a public server ·
`app.py` webhook server (optional) · `store.py` SQLite history ·
`install.sh` / `update.sh` / `tiny-chef.sh` server scripts.

## Developing locally

```bash
pip install -r requirements.txt
cp .env.example .env            # add ANTHROPIC_API_KEY
python -m tinychef simulate     # your terminal plays the phone
pytest -q
```

## Notes

- **Why Telegram, not SMS:** US carriers require registration for app-sent texts, and
  Twilio rejects registrations for personal/family use (error 30532). Twilio SMS is
  still supported (`CHANNEL=twilio`, run `python -m tinychef serve`, point the
  number's webhook at `/sms`) if this ever becomes a registered business.
- **Cost:** a few cents of Claude API per week. Telegram and the Google Cloud
  e2-micro server are free.
