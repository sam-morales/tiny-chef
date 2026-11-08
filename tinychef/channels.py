"""Delivery channels. Each has send(to, text). Pick one with CHANNEL=twilio|telegram|console."""
import base64
import hashlib
import hmac

import requests

from .config import Config
from .messages import split
from . import store


class ConsoleChannel:
    """Prints messages; used for local testing and the `simulate` command."""

    def __init__(self):
        self.sent = []

    def send(self, to, text):
        for part in split(text):
            self.sent.append((to, part))
            print(f"\n--- to {to} ---\n{part}")


class TwilioChannel:
    def send(self, to, text):
        url = f"https://api.twilio.com/2010-04-01/Accounts/{Config.TWILIO_ACCOUNT_SID}/Messages.json"
        for part in split(text):
            r = requests.post(
                url,
                data={"From": Config.TWILIO_FROM_NUMBER, "To": to, "Body": part},
                auth=(Config.TWILIO_ACCOUNT_SID, Config.TWILIO_AUTH_TOKEN),
                timeout=30,
            )
            r.raise_for_status()


def twilio_signature_valid(url, params, signature, auth_token=None):
    """Verify X-Twilio-Signature (HMAC-SHA1 of URL + sorted POST params)."""
    token = auth_token or Config.TWILIO_AUTH_TOKEN
    if not token or not signature:
        return False
    payload = url + "".join(k + params[k] for k in sorted(params))
    digest = hmac.new(token.encode(), payload.encode(), hashlib.sha1).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature)


class TelegramChannel:
    def send(self, to, text):
        url = f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage"
        for part in split(text, limit=4000):
            r = requests.post(url, json={"chat_id": to, "text": part}, timeout=30)
            r.raise_for_status()


_channel = None


def get_channel():
    global _channel
    if _channel is None:
        _channel = {"twilio": TwilioChannel, "telegram": TelegramChannel}.get(Config.CHANNEL, ConsoleChannel)()
    return _channel


def set_channel(ch):
    global _channel
    _channel = ch


def send(to, text):
    get_channel().send(to, text)
    store.log_message("out", to, text)


def broadcast(text):
    for r in Config.RECIPIENTS:
        send(r, text)
