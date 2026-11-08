"""Talks to Claude to create a weekly plan and to apply swap requests.

Claude is forced to answer through a tool call, so the output is always structured JSON.
Swaps only return the replaced meals; untouched meals are kept exactly as they were.
"""
import json
import logging

import requests

log = logging.getLogger("tinychef")

from .config import Config

SECTIONS = ["produce", "meat & seafood", "dairy & eggs", "bakery", "pantry", "frozen", "spices", "other"]
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

INGREDIENT = {
    "type": "object",
    "properties": {
        "item": {"type": "string", "description": "Generic grocery name, singular, lowercase, e.g. 'yellow onion'"},
        "quantity": {"type": "number"},
        "unit": {"type": "string", "description": "e.g. 'lb', 'oz', 'cup', 'tbsp', 'can', 'each'"},
        "section": {"type": "string", "enum": SECTIONS},
    },
    "required": ["item", "quantity", "unit", "section"],
}

MEAL = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "day": {"type": "string", "enum": DAYS},
        "summary": {"type": "string", "description": "One short line, under 80 characters"},
        "active_minutes": {"type": "integer", "description": "Weeknight hands-on time after prep-day work"},
        "servings": {"type": "integer"},
        "prep_ahead": {"type": "string", "description": "What to do for this meal on prep day"},
        "ingredients": {"type": "array", "items": INGREDIENT},
        "steps": {"type": "array", "items": {"type": "string"}, "description": "Weeknight cooking steps, concise"},
    },
    "required": ["name", "day", "summary", "active_minutes", "servings", "prep_ahead", "ingredients", "steps"],
}

PLAN_TOOL = {
    "name": "submit_meal_plan",
    "description": "Submit the week's meal plan.",
    "input_schema": {
        "type": "object",
        "properties": {
            "meals": {"type": "array", "items": MEAL},
            "prep_plan": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Ordered prep-day steps covering all meals, efficient (start slow items first)",
            },
        },
        "required": ["meals", "prep_plan"],
    },
}

REVISE_TOOL = {
    "name": "submit_revision",
    "description": "Apply the family's text reply to the current plan.",
    "input_schema": {
        "type": "object",
        "properties": {
            "replacements": {
                "type": "array",
                "description": "Only the meals that change. meal_number is 1-based, matching the text the family saw.",
                "items": {
                    "type": "object",
                    "properties": {"meal_number": {"type": "integer"}, "meal": MEAL},
                    "required": ["meal_number", "meal"],
                },
            },
            "prep_plan": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Full updated prep-day plan for the resulting week. Required if anything changed.",
            },
            "remember": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Lasting preferences stated in the reply (e.g. 'no salmon'). Empty if the request is only for this week.",
            },
            "clarifying_question": {
                "type": "string",
                "description": "Set ONLY if the request is too unclear to act on; then leave replacements empty.",
            },
        },
        "required": ["replacements"],
    },
}

SYSTEM = (
    "You are a family meal-prep planner. Plan practical, kid-friendly weeknight meals that share "
    "ingredients across the week to cut waste and cost, and lean on one prep day to keep weeknights short. "
    "Quantities are for the whole recipe at the requested servings. Skip the listed pantry staples in "
    "ingredients. Use consistent item names and units across meals so the grocery list combines cleanly."
)


class ClaudeClient:
    """Minimal Messages API client using requests (no SDK dependency)."""

    URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key=None, model=None):
        self.api_key = api_key or Config.ANTHROPIC_API_KEY
        self.model = model or Config.ANTHROPIC_MODEL
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")

    def _post(self, payload):
        resp = requests.post(
            self.URL,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
            timeout=300,
        )
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("error", {}).get("message", resp.text)
            except ValueError:
                detail = resp.text
            raise ApiError(resp.status_code, detail)
        return resp.json()

    def call_tool(self, system, user, tool):
        base = {
            "model": self.model,
            "max_tokens": 16000,
            "system": system,
            "tools": [tool],
        }
        # 1st choice: force the tool. Some models/settings reject forced tool use
        # (400), so fall back to letting Claude choose, with a firm instruction.
        try:
            data = self._post({**base, "tool_choice": {"type": "tool", "name": tool["name"]},
                               "messages": [{"role": "user", "content": user}]})
        except ApiError as e:
            if e.status != 400:
                raise
            log.warning("Forced tool use rejected (%s); retrying with tool_choice=auto", e.detail)
            nudge = f"{user}\n\nRespond only by calling the {tool['name']} tool."
            data = self._post({**base, "tool_choice": {"type": "auto"},
                               "messages": [{"role": "user", "content": nudge}]})
        for block in data.get("content", []):
            if block.get("type") == "tool_use":
                return block["input"]
        if data.get("stop_reason") == "max_tokens":
            raise RuntimeError("Claude ran out of room before finishing the plan (max_tokens)")
        raise RuntimeError("Claude did not return a tool call")


class ApiError(RuntimeError):
    def __init__(self, status, detail):
        super().__init__(f"Anthropic API error {status}: {detail}")
        self.status, self.detail = status, detail


def _profile_text(family, learned, recent):
    return (
        f"Family profile:\n{json.dumps(family, indent=2)}\n\n"
        f"Learned preferences from past replies: {json.dumps(learned) if learned else 'none'}\n"
        f"Meals served in recent weeks (avoid repeating): {json.dumps(recent) if recent else 'none'}\n"
    )


def generate_plan(llm, family, learned=(), recent=()):
    n = family.get("meals_per_week", 5)
    user = (
        _profile_text(family, list(learned), list(recent))
        + f"\nPlan {n} meals for the coming week, one per day starting Monday. "
        f"Each serves {family.get('servings_per_meal', 4)}."
    )
    plan = llm.call_tool(SYSTEM, user, PLAN_TOOL)
    return _validate_plan(plan)


def revise_plan(llm, family, plan, reply_text, learned=()):
    numbered = "\n".join(f"{i}. {m['day']} - {m['name']}" for i, m in enumerate(plan["meals"], 1))
    user = (
        _profile_text(family, list(learned), [])
        + f"\nCurrent plan (as numbered in the text the family received):\n{numbered}\n\n"
        f"Full current plan JSON:\n{json.dumps(plan)}\n\n"
        f'The family replied by text: "{reply_text}"\n\n'
        "Replace only the meals they asked to change (keep the same day unless asked), following any "
        "guidelines they gave. If they ask to swap without naming meals, pick the ones that best fit their "
        "request. New meals should reuse ingredients already being bought where sensible."
    )
    result = llm.call_tool(SYSTEM, user, REVISE_TOOL)

    if result.get("clarifying_question") and not result.get("replacements"):
        return plan, [], result["clarifying_question"], []

    new = json.loads(json.dumps(plan))  # deep copy
    changed = []
    for r in result.get("replacements", []):
        idx = r["meal_number"] - 1
        if 0 <= idx < len(new["meals"]):
            new["meals"][idx] = r["meal"]
            changed.append(r["meal_number"])
    if result.get("prep_plan"):
        new["prep_plan"] = result["prep_plan"]
    return _validate_plan(new), changed, None, result.get("remember", [])


def _validate_plan(plan):
    if not plan.get("meals"):
        raise ValueError("Plan has no meals")
    for m in plan["meals"]:
        for key in ("name", "ingredients", "steps"):
            if key not in m:
                raise ValueError(f"Meal missing {key}: {m}")
    plan.setdefault("prep_plan", [])
    return plan
