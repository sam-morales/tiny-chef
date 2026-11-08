"""Core behaviour: the Saturday send, and handling text replies."""
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import channels, messages, planner, store
from .config import Config, load_family

_llm = None


def get_llm():
    global _llm
    if _llm is None:
        _llm = planner.ClaudeClient()
    return _llm


def set_llm(llm):
    global _llm
    _llm = llm


def upcoming_monday(today=None):
    today = today or datetime.now(ZoneInfo(Config.TIMEZONE)).date()
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)


def _skip(family):
    return family.get("pantry_staples_to_skip", [])


def _send_full_plan(plan, week_of, header="Meals for the week of", to=None):
    family = load_family()
    texts = [messages.meals_text(plan, week_of, header), messages.grocery_text(plan, _skip(family))]
    for t in texts:
        if to:
            channels.send(to, t)
        else:
            channels.broadcast(t)


def create_and_send_week(today=None, force=False):
    """Generate next week's plan and text it to everyone. Safe to call repeatedly."""
    week_of = upcoming_monday(today).isoformat()
    if not force and not store.mark_sent(week_of):
        return None  # already sent this week
    family = load_family()
    plan = planner.generate_plan(get_llm(), family, store.learned_prefs(), store.recent_meal_names())
    store.save_plan(week_of, plan, "weekly")
    _send_full_plan(plan, week_of)
    return plan


def handle_reply(sender, text):
    """Process an incoming text. Returns nothing; all responses are sent as texts."""
    store.log_message("in", sender, text)
    if Config.RECIPIENTS and sender not in Config.RECIPIENTS:
        return  # ignore strangers silently

    body = text.strip()
    cmd = body.upper()
    current = store.current_plan()

    if cmd in ("HELP", "?", "INFO"):
        return channels.send(sender, messages.HELP)
    if cmd in ("STOP", "START", "UNSTOP"):
        return  # carrier keywords; Twilio handles opt-out itself
    if cmd == "PREFS":
        prefs = store.learned_prefs()
        return channels.send(sender, "I remember:\n- " + "\n- ".join(prefs) if prefs else "No learned preferences yet.")
    if cmd == "FORGET":
        store.clear_learned_prefs()
        return channels.send(sender, "Cleared learned preferences. Your family profile is unchanged.")
    if cmd in ("NEW", "NEW PLAN", "START OVER"):
        channels.send(sender, "Making a brand new plan, one moment...")
        create_and_send_week(force=True)
        return

    if not current:
        return channels.send(sender, "No plan yet this week. Reply NEW to make one now.")
    plan, week_of = current["plan"], current["week_of"]

    if cmd in ("LIST", "MEALS", "GROCERIES", "GROCERY"):
        return _send_full_plan(plan, week_of, to=sender)
    if cmd == "PREP":
        return channels.send(sender, messages.prep_text(plan))
    m = re.fullmatch(r"(?:RECIPE|R)\s*#?\s*(\d+)", cmd)
    if m:
        return channels.send(sender, messages.recipe_text(plan, int(m.group(1))))

    # Anything else is treated as a swap request in plain English.
    channels.send(sender, "Got it, reworking the plan...")
    family = load_family()
    new_plan, changed, question, remember = planner.revise_plan(
        get_llm(), family, plan, body, store.learned_prefs()
    )
    if question:
        return channels.send(sender, question)
    if not changed:
        return channels.send(sender, "I couldn't tell which meals to change. Try e.g. \"swap 3 for a pasta dish\".")
    if remember:
        store.add_learned_prefs(remember)
    store.save_plan(week_of, new_plan, body)
    nums = ", ".join(str(n) for n in changed)
    _send_full_plan(new_plan, week_of, header=f"Updated (changed {nums}) - week of")
    if remember:
        channels.send(sender, "I'll remember for future weeks: " + "; ".join(remember) + " (reply FORGET to undo)")


def due_now(now=None):
    """True from the scheduled time (Saturday 7:00pm local by default) until 24h later.

    The window means a server restart at 7:00pm doesn't skip the week; mark_sent()
    makes sure it still only goes out once.
    """
    now = now or datetime.now(ZoneInfo(Config.TIMEZONE))
    days_back = (now.weekday() - Config.SEND_WEEKDAY) % 7
    last = (now - timedelta(days=days_back)).replace(
        hour=Config.SEND_HOUR, minute=Config.SEND_MINUTE, second=0, microsecond=0
    )
    if last > now:
        last -= timedelta(days=7)
    return now - last < timedelta(hours=24)
