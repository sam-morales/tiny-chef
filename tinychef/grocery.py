"""Builds one combined grocery list from every meal's ingredients.

Done in code (not by the model) so the list always matches the meals exactly,
including after swaps.
"""
from collections import OrderedDict

from .planner import SECTIONS

# Simple unit normalisation so "tablespoons" and "tbsp" combine.
UNIT_ALIASES = {
    "tablespoon": "tbsp", "tablespoons": "tbsp", "tbsps": "tbsp", "tbs": "tbsp",
    "teaspoon": "tsp", "teaspoons": "tsp", "tsps": "tsp",
    "cups": "cup", "pounds": "lb", "pound": "lb", "lbs": "lb",
    "ounces": "oz", "ounce": "oz", "cans": "can", "cloves": "clove",
    "pieces": "each", "piece": "each", "whole": "each", "": "each",
    "bunches": "bunch", "heads": "head", "packages": "package", "pkg": "package",
}


def _unit(u):
    u = (u or "").strip().lower().rstrip(".")
    return UNIT_ALIASES.get(u, u)


def _fmt_qty(q):
    q = round(q, 2)
    if q == int(q):
        return str(int(q))
    for frac, s in ((0.25, "1/4"), (0.33, "1/3"), (0.5, "1/2"), (0.67, "2/3"), (0.75, "3/4")):
        whole = int(q)
        if abs(q - whole - frac) < 0.02:
            return f"{whole} {s}" if whole else s
    return f"{q:g}"


def build_grocery_list(plan, skip=()):
    """Returns OrderedDict section -> list of 'item: qty unit' strings."""
    skip = {s.lower() for s in skip}
    # (section, item) -> {unit: qty}
    totals = {}
    for meal in plan["meals"]:
        for ing in meal["ingredients"]:
            item = ing["item"].strip().lower()
            if item in skip:
                continue
            section = ing.get("section", "other")
            if section not in SECTIONS:
                section = "other"
            units = totals.setdefault((section, item), {})
            u = _unit(ing.get("unit"))
            units[u] = units.get(u, 0) + float(ing.get("quantity") or 0)

    out = OrderedDict((s, []) for s in SECTIONS)
    for (section, item), units in sorted(totals.items(), key=lambda kv: kv[0][1]):
        parts = []
        for u, q in units.items():
            parts.append(_fmt_qty(q) if u == "each" else f"{_fmt_qty(q)} {u}")
        out[section].append(f"{item}: {' + '.join(parts)}")
    return OrderedDict((s, items) for s, items in out.items() if items)
