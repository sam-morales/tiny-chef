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


def _send_full_plan(plan, week_of, header="Meals for the week of", to=None, recipes=None):
    """Meals + grocery list, then (optionally) the prep plan and a full recipe per meal.

    recipes: None = no recipes, "all" = every meal, or a list of 1-based meal numbers.
    """
    family = load_family()
    texts = [messages.meals_text(plan, week_of, header), messages.grocery_text(plan, _skip(family))]
    if recipes:
        nums = range(1, len(plan["meals"]) + 1) if recipes == "all" else recipes
        texts.append(messages.prep_text(plan))
        texts += [messages.recipe_text(plan, n) for n in nums]
    for t in texts:
        if to:
            channels.send(to, t)
        else:
            channels.broadcast(t)


def _send_recipes_only(plan, to):
    channels.send(to, messages.prep_text(plan))
    for n in range(1, len(plan["meals"]) + 1):
        channels.send(to, messages.recipe_text(plan, n))


def create_and_send_week(today=None, force=False):
    """Generate next week's plan and text it to everyone. Safe to call repeatedly."""
    week_of = upcoming_monday(today).isoformat()
    if not force and not store.mark_sent(week_of):
        return None  # already sent this week
    family = load_family()
    plan = planner.generate_plan(get_llm(), family, store.learned_prefs(), store.recent_meal_names())
    store.save_plan(week_of, plan, "weekly")
    _send_full_plan(plan, week_of, recipes="all")
    return plan


def _handle_stranger(sender, name):
    """Someone not in the family messaged the bot: ask the family to approve them."""
    if Config.CHANNEL != "telegram":
        return  # SMS strangers are ignored (and cost money to answer)
    req = store.add_join_request(sender, name)
    if req is None:
        return channels.send(sender, "Still waiting for the family to approve you. Hang tight!")
    channels.send(sender, f"Hi {name}! Tiny Chef is a private family meal planner. "
                          "I've asked the family to let you in. You'll get a message here once you're approved.")
    channels.broadcast(f"{name} wants to join Tiny Chef.\nReply APPROVE {req} to add them "
                       f"(or APPROVE {req} Wife to save them under a different name).")


def _handle_family_command(sender, body, cmd, name):
    """APPROVE / FAMILY / REMOVE. Returns True if handled."""
    m = re.fullmatch(r"APPROVE\s*#?\s*(\d*)\s*(.*)", body, flags=re.I | re.S)
    if m:
        pending = store.join_requests()
        if m.group(1):
            req_id = int(m.group(1))
        elif len(pending) == 1:
            req_id = pending[0]["id"]
        else:
            channels.send(sender, "No one is waiting to join." if not pending else
                          "Several people are waiting:\n" + "\n".join(f"{p['id']}. {p['name']}" for p in pending)
                          + "\nReply APPROVE and their number.")
            return True
        req = store.pop_join_request(req_id)
        if not req:
            channels.send(sender, f"There's no join request number {req_id}. Reply FAMILY to see who's waiting.")
            return True
        new_name = m.group(2).strip() or req["name"]
        store.add_member(req["chat_id"], new_name)
        channels.send(req["chat_id"], f"Welcome to Tiny Chef, {new_name}! 🍳 You'll get the meal plan, grocery list "
                                      "and recipes every Saturday at 7pm.\n\n" + messages.HELP)
        current = store.current_plan()
        if current:
            _send_full_plan(current["plan"], current["week_of"], header="This week's plan, week of", to=req["chat_id"])
        channels.broadcast(f"{new_name} joined Tiny Chef (approved by {name}).", exclude=(req["chat_id"],))
        return True

    if cmd == "FAMILY":
        lines = ["TINY CHEF FAMILY"]
        lines += [f"- Set up on server (id {r})" for r in Config.RECIPIENTS]
        lines += [f"- {m['name']}" for m in store.members()]
        pending = store.join_requests()
        if pending:
            lines += ["", "Waiting to join:"] + [f"{p['id']}. {p['name']} (reply APPROVE {p['id']})" for p in pending]
        lines += ["", "To add someone: they message this bot, then you reply APPROVE.",
                  "To remove: REMOVE and their name."]
        channels.send(sender, "\n".join(lines))
        return True

    m = re.fullmatch(r"REMOVE\s+(.+)", body, flags=re.I | re.S)
    if m:
        target = m.group(1).strip().lower()
        match = [x for x in store.members() if x["name"].lower() == target]
        if not match:
            channels.send(sender, f"No one named {m.group(1).strip()} was added in chat. Reply FAMILY to see the list. "
                                  "(People set up on the server are removed there with: tiny-chef settings)")
            return True
        store.remove_member(match[0]["chat_id"])
        channels.send(match[0]["chat_id"], "You've been removed from Tiny Chef. Message me again if you want back in.")
        channels.send(sender, f"Removed {match[0]['name']}.")
        return True
    return False


def handle_reply(sender, text, name=None):
    """Process an incoming message. Returns nothing; all responses are sent as messages."""
    store.log_message("in", sender, text)
    name = name or "Someone"
    family = channels.recipients()
    if family and sender not in family:
        return _handle_stranger(sender, name)

    body = text.strip()
    cmd = body.upper()
    if _handle_family_command(sender, body, cmd, name):
        return
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
    if cmd in ("RECIPES", "ALL RECIPES"):
        return _send_recipes_only(plan, sender)
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
    _send_full_plan(new_plan, week_of, header=f"Updated (changed {nums}) - week of", recipes=changed)
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
