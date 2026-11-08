"""Telegram without a public server: long-polling instead of webhooks.

Run on any always-on computer (old laptop, Raspberry Pi, home PC):
    python -m tinychef telegram-poll
"""
import logging
import time

import requests

from . import service
from .config import Config

log = logging.getLogger("tinychef")


def _api(method, **params):
    r = requests.post(
        f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/{method}", json=params, timeout=70
    )
    r.raise_for_status()
    return r.json()["result"]


def whoami():
    """Print chat ids of everyone who has messaged the bot recently."""
    _api("deleteWebhook")  # getUpdates doesn't work while a webhook is set
    seen = {}
    for u in _api("getUpdates"):
        chat = (u.get("message") or {}).get("chat") or {}
        if "id" in chat:
            seen[chat["id"]] = " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")])) or chat.get("title", "")
    if not seen:
        print("No messages found. Have each person open your bot in Telegram, tap Start, and send 'hi'. Then rerun.")
    for cid, name in seen.items():
        print(f"{name}: {cid}")
    if seen:
        print(f"\nPut this in your .env:\nRECIPIENTS={','.join(str(c) for c in seen)}")


def run(poll_once=False):
    """Long-poll for messages and run the weekly scheduler in the same loop."""
    _api("deleteWebhook")
    offset = None
    log.info("Polling Telegram. Weekly send: weekday %s at %02d:%02d %s",
             Config.SEND_WEEKDAY, Config.SEND_HOUR, Config.SEND_MINUTE, Config.TIMEZONE)
    while True:
        try:
            if service.due_now() and service.create_and_send_week():
                log.info("weekly plan sent")
            params = {"timeout": 0 if poll_once else 50, "allowed_updates": ["message"]}
            if offset is not None:
                params["offset"] = offset
            for u in _api("getUpdates", **params):
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                text, chat = msg.get("text"), (msg.get("chat") or {}).get("id")
                if text and chat is not None:
                    try:
                        service.handle_reply(str(chat), text)
                    except Exception:
                        log.exception("failed handling message")
                        service.channels.send(str(chat), "Sorry, something went wrong. Try again in a minute.")
        except requests.RequestException:
            log.exception("network error; retrying shortly")
            time.sleep(10)
        if poll_once:
            return
