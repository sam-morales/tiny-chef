"""Command line:

  python -m tinychef serve          run the web server + weekly scheduler
  python -m tinychef send-now       generate and text a plan right now (ignores schedule)
  python -m tinychef simulate       chat with the bot in your terminal (no texting needed)
  python -m tinychef telegram-whoami list chat ids of people who messaged the bot
  python -m tinychef telegram-poll  run the Telegram bot + scheduler with no public server
  python -m tinychef telegram-setup register the Telegram webhook (only for `serve` hosting)
"""
import logging
import os
import sys


def main():
    logging.basicConfig(level=logging.INFO)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"

    from . import service
    from .config import Config

    if cmd == "serve":
        from .app import app, start_scheduler

        start_scheduler()
        app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))

    elif cmd == "send-now":
        service.create_and_send_week(force=True)

    elif cmd == "simulate":
        from . import channels

        channels.set_channel(channels.ConsoleChannel())
        me = Config.RECIPIENTS[0] if Config.RECIPIENTS else "+15550000000"
        Config.RECIPIENTS = [me]
        print("Generating this week's plan (as if it were Saturday 7pm)...")
        service.create_and_send_week(force=True)
        print("\nType replies as if texting. Ctrl-C to quit.")
        while True:
            try:
                text = input("\nyou> ")
            except (EOFError, KeyboardInterrupt):
                break
            if text.strip():
                service.handle_reply(me, text)

    elif cmd == "telegram-whoami":
        from . import telegram_poll

        telegram_poll.whoami()

    elif cmd == "telegram-poll":
        from . import telegram_poll

        Config.CHANNEL = "telegram"
        telegram_poll.run()

    elif cmd == "telegram-setup":
        import requests

        r = requests.post(
            f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/setWebhook",
            json={"url": Config.PUBLIC_BASE_URL.rstrip("/") + "/telegram",
                  "secret_token": Config.TELEGRAM_WEBHOOK_SECRET},
            timeout=30,
        )
        print(r.json())

    else:
        print(__doc__)


if __name__ == "__main__":
    main()
