"""Turns plans into text messages. Long texts are split into parts under the SMS limit."""
from .grocery import build_grocery_list

MAX_LEN = 1500  # Twilio caps a single message body at 1600 chars

HELP = (
    "Tiny Chef - reply with:\n"
    "- Any swap request, e.g. \"swap 2 and 4 for something vegetarian\" or \"no fish this week\"\n"
    "- RECIPE 3 for full steps of meal 3, RECIPES for all of them\n"
    "- PREP for the prep-day plan\n"
    "- LIST to resend meals + groceries\n"
    "- NEW for a whole new plan\n"
    "- PREFS to see what I've learned, FORGET to clear it\n"
    "- FAMILY to see who's on Tiny Chef (new people: they message this bot, you reply APPROVE)"
)


def meals_text(plan, week_of, header="Meals for the week of"):
    lines = [f"Tiny Chef 🍳 {header} {week_of}:"]
    for i, m in enumerate(plan["meals"], 1):
        lines.append(f"{i}. {m['day']} - {m['name']} ({m['active_minutes']} min)\n   {m['summary']}")
    lines.append("\nReply to swap anything (e.g. \"swap 2 for something with chicken\"). HELP for options.")
    return "\n".join(lines)


def grocery_text(plan, skip=()):
    groups = build_grocery_list(plan, skip)
    lines = ["GROCERY LIST"]
    for section, items in groups.items():
        lines.append(f"\n{section.upper()}")
        lines += [f"- {i}" for i in items]
    if skip:
        lines.append(f"\n(Assumes you have: {', '.join(skip)})")
    return "\n".join(lines)


def recipe_text(plan, n):
    if not 1 <= n <= len(plan["meals"]):
        return f"There's no meal {n}. Meals are numbered 1-{len(plan['meals'])}."
    m = plan["meals"][n - 1]
    lines = [f"RECIPE {n}: {m['name']} ({m['day']}, serves {m['servings']}, {m['active_minutes']} min)", "", "INGREDIENTS"]
    for ing in m["ingredients"]:
        unit = "" if (ing.get("unit") or "").lower() in ("", "each", "whole", "piece") else f" {ing['unit']}"
        lines.append(f"- {ing['quantity']:g}{unit} {ing['item']}")
    lines += ["", f"PREP AHEAD: {m['prep_ahead']}", "", "STEPS"]
    lines += [f"{i}. {s}" for i, s in enumerate(m["steps"], 1)]
    return "\n".join(lines)


def prep_text(plan):
    if not plan.get("prep_plan"):
        return "No prep-day plan for this week."
    return "PREP DAY PLAN\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(plan["prep_plan"], 1))


def split(text, limit=MAX_LEN):
    """Split on line boundaries into chunks no longer than limit, numbered (1/3) when >1."""
    chunks, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:  # pathological long line
            chunks.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) + 1 > limit - 8:
            chunks.append(cur.rstrip("\n"))
            cur = ""
        cur += line + "\n"
    if cur.strip():
        chunks.append(cur.rstrip("\n"))
    if len(chunks) > 1:
        chunks = [f"({i}/{len(chunks)}) {c}" for i, c in enumerate(chunks, 1)]
    return chunks
