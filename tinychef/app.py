"""Web server: Twilio + Telegram webhooks, a cron endpoint, and a built-in weekly scheduler."""
import hmac
import logging
import threading
import time

from flask import Flask, abort, request

from . import channels, service, telegram_poll
from .config import Config

log = logging.getLogger("tinychef")
app = Flask(__name__)


def _run_async(fn, *args):
    # Claude can take a while; reply to the webhook right away and do the work in the background.
    def wrapped():
        try:
            fn(*args)
        except Exception:
            log.exception("background task failed")
            if args:
                try:
                    channels.send(args[0], "Sorry, something went wrong making that change. Try again in a minute.")
                except Exception:
                    log.exception("could not send error text")

    threading.Thread(target=wrapped, daemon=True).start()


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/sms")
def twilio_inbound():
    if Config.PUBLIC_BASE_URL:  # verify the request really came from Twilio
        url = Config.PUBLIC_BASE_URL.rstrip("/") + "/sms"
        sig = request.headers.get("X-Twilio-Signature", "")
        if not channels.twilio_signature_valid(url, request.form.to_dict(), sig):
            abort(403)
    _run_async(service.handle_reply, request.form.get("From", ""), request.form.get("Body", ""))
    return "<Response></Response>", 200, {"Content-Type": "text/xml"}


@app.post("/telegram")
def telegram_inbound():
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if Config.TELEGRAM_WEBHOOK_SECRET and not hmac.compare_digest(secret, Config.TELEGRAM_WEBHOOK_SECRET):
        abort(403)
    msg = (request.get_json(silent=True) or {}).get("message") or {}
    text, chat = msg.get("text"), (msg.get("chat") or {}).get("id")
    if text and chat is not None:
        _run_async(service.handle_reply, str(chat), text, telegram_poll._name(msg))
    return {"ok": True}


@app.post("/cron/weekly")
def cron_weekly():
    """For hosts with external cron: call this at Saturday 7pm with header X-Cron-Secret."""
    if not Config.CRON_SECRET or not hmac.compare_digest(request.headers.get("X-Cron-Secret", ""), Config.CRON_SECRET):
        abort(403)
    plan = service.create_and_send_week()
    return {"sent": plan is not None}


def start_scheduler(interval=60):
    """Background loop: checks every minute whether the weekly send is due."""

    def loop():
        while True:
            try:
                if service.due_now():
                    if service.create_and_send_week():
                        log.info("weekly plan sent")
            except Exception:
                log.exception("scheduler error")
            time.sleep(interval)

    threading.Thread(target=loop, daemon=True).start()
