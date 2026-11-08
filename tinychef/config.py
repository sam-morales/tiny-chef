"""Configuration, loaded from environment variables (see .env.example)."""
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path=BASE_DIR / ".env"):
    """Read KEY=value lines from .env (real environment variables win)."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


def _env(name, default=None):
    v = os.environ.get(name)
    return v if v not in (None, "") else default


class Config:
    # --- Claude ---
    ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY")
    ANTHROPIC_MODEL = _env("ANTHROPIC_MODEL", "claude-sonnet-5-5")

    # --- Delivery channel: "twilio", "telegram" or "console" ---
    CHANNEL = _env("CHANNEL", "console")

    # Twilio SMS
    TWILIO_ACCOUNT_SID = _env("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = _env("TWILIO_AUTH_TOKEN")
    TWILIO_FROM_NUMBER = _env("TWILIO_FROM_NUMBER")
    PUBLIC_BASE_URL = _env("PUBLIC_BASE_URL")  # e.g. https://tinychef.example.com (for signature check)

    # Telegram bot
    TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")
    TELEGRAM_WEBHOOK_SECRET = _env("TELEGRAM_WEBHOOK_SECRET")

    # Who receives the weekly plan and who may reply.
    # Phone numbers in E.164 (+15551234567) for Twilio, chat ids for Telegram. Comma-separated.
    RECIPIENTS = [r.strip() for r in _env("RECIPIENTS", "").split(",") if r.strip()]

    # --- Schedule ---
    TIMEZONE = _env("TIMEZONE", "America/Los_Angeles")
    SEND_WEEKDAY = int(_env("SEND_WEEKDAY", "5"))  # Monday=0 ... Saturday=5
    SEND_HOUR = int(_env("SEND_HOUR", "19"))
    SEND_MINUTE = int(_env("SEND_MINUTE", "0"))
    CRON_SECRET = _env("CRON_SECRET")  # protects POST /cron/weekly

    # --- Storage / family profile ---
    DB_PATH = _env("DB_PATH", str(BASE_DIR / "tinychef.db"))
    FAMILY_FILE = _env("FAMILY_FILE", str(BASE_DIR / "family.json"))


def load_family():
    # family.json is your private copy (not in git); fall back to the example.
    path = Path(Config.FAMILY_FILE)
    if not path.exists():
        path = BASE_DIR / "family.example.json"
    with open(path) as f:
        return json.load(f)
