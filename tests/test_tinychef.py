import base64
import hashlib
import hmac
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from tinychef import channels, grocery, messages, service, store
from tinychef.config import Config


def meal(name, day, ings):
    return {
        "name": name, "day": day, "summary": f"{name} summary", "active_minutes": 25, "servings": 4,
        "prep_ahead": "chop stuff", "steps": ["cook it", "serve it"],
        "ingredients": [{"item": i, "quantity": q, "unit": u, "section": s} for i, q, u, s in ings],
    }


PLAN = {
    "meals": [
        meal("Chicken Tacos", "Mon", [("chicken thigh", 1.5, "lb", "meat & seafood"), ("yellow onion", 1, "each", "produce"), ("tortillas", 1, "package", "bakery")]),
        meal("Salmon Rice Bowls", "Tue", [("salmon fillet", 1.25, "lb", "meat & seafood"), ("rice", 2, "cups", "pantry")]),
        meal("Pasta Primavera", "Wed", [("penne", 1, "lb", "pantry"), ("yellow onion", 1, "", "produce"), ("olive oil", 2, "tbsp", "pantry")]),
    ],
    "prep_plan": ["Cook rice", "Marinate chicken"],
}


class FakeLLM:
    def __init__(self):
        self.calls = []

    def call_tool(self, system, user, tool):
        self.calls.append((tool["name"], user))
        if tool["name"] == "submit_meal_plan":
            return {"meals": [dict(m) for m in PLAN["meals"]], "prep_plan": list(PLAN["prep_plan"])}
        if "what?" in user:
            return {"replacements": [], "clarifying_question": "Which meal should I change?"}
        return {
            "replacements": [{"meal_number": 2, "meal": meal("Black Bean Bowls", "Tue", [("black beans", 2, "can", "pantry"), ("rice", 1, "cup", "pantry")])}],
            "prep_plan": ["Cook rice", "Marinate chicken", "Rinse beans"],
            "remember": ["no salmon"],
        }


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    # Tests must not depend on the real .env / family.json of the machine running them
    # (the server runs these before every update).
    from pathlib import Path
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(Config, "CHANNEL", "console")
    monkeypatch.setattr(Config, "FAMILY_FILE", str(Path(__file__).parent.parent / "family.example.json"))
    for k in ("ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "TWILIO_AUTH_TOKEN", "PUBLIC_BASE_URL", "CRON_SECRET"):
        monkeypatch.setattr(Config, k, None)
    monkeypatch.setattr(Config, "RECIPIENTS", ["+15551112222", "+15553334444"])
    ch = channels.ConsoleChannel()
    channels.set_channel(ch)
    llm = FakeLLM()
    service.set_llm(llm)
    return ch, llm


def sent_to(ch, who):
    return "\n".join(t for to, t in ch.sent if to == who)


def test_grocery_list_combines_and_skips():
    g = grocery.build_grocery_list(PLAN, skip=["olive oil"])
    assert "yellow onion: 2" in g["produce"]
    assert "rice: 2 cup" in g["pantry"]
    assert not any("olive oil" in i for i in g["pantry"])


def test_weekly_send_goes_to_everyone_once(setup):
    ch, _ = setup
    assert service.create_and_send_week(today=date(2026, 11, 14))  # a Saturday
    assert service.create_and_send_week(today=date(2026, 11, 14)) is None  # no double send
    for who in Config.RECIPIENTS:
        text = sent_to(ch, who)
        assert "week of 2026-11-16" in text and "GROCERY LIST" in text and "Salmon" in text


def test_swap_reply_regenerates_plan_and_groceries(setup):
    ch, llm = setup
    service.create_and_send_week(today=date(2026, 11, 14))
    ch.sent.clear()
    service.handle_reply("+15551112222", "swap 2 for something vegetarian, we're sick of salmon")
    cur = store.current_plan()
    assert cur["revision"] == 2
    names = [m["name"] for m in cur["plan"]["meals"]]
    assert names == ["Chicken Tacos", "Black Bean Bowls", "Pasta Primavera"]  # others untouched
    other = sent_to(ch, "+15553334444")  # spouse sees the update too
    assert "Updated (changed 2)" in other and "black beans: 2 can" in other and "salmon" not in other.lower()
    assert store.learned_prefs() == ["no salmon"]
    assert '"swap 2 for something vegetarian' in llm.calls[-1][1]


def test_clarifying_question(setup):
    ch, _ = setup
    service.create_and_send_week(today=date(2026, 11, 14))
    ch.sent.clear()
    service.handle_reply("+15551112222", "what?")
    assert "Which meal should I change?" in sent_to(ch, "+15551112222")
    assert store.current_plan()["revision"] == 1


def test_commands(setup):
    ch, _ = setup
    service.create_and_send_week(today=date(2026, 11, 14))
    ch.sent.clear()
    service.handle_reply("+15551112222", "recipe 1")
    service.handle_reply("+15551112222", "PREP")
    service.handle_reply("+15551112222", "help")
    t = sent_to(ch, "+15551112222")
    assert "RECIPE 1: Chicken Tacos (Mon, serves 4" in t and "PREP DAY PLAN" in t and "RECIPE 3" in t


def test_sms_strangers_ignored(setup):
    ch, _ = setup
    service.handle_reply("+19998887777", "help")
    assert ch.sent == []


def test_schedule_window():
    tz = ZoneInfo("America/Los_Angeles")
    assert not service.due_now(datetime(2026, 11, 14, 18, 59, tzinfo=tz))
    assert service.due_now(datetime(2026, 11, 14, 19, 0, tzinfo=tz))
    assert service.due_now(datetime(2026, 11, 15, 12, 0, tzinfo=tz))  # missed it? still catches up
    assert not service.due_now(datetime(2026, 11, 15, 19, 1, tzinfo=tz))
    assert service.upcoming_monday(date(2026, 11, 14)) == date(2026, 11, 16)


def test_long_text_splits():
    parts = messages.split("line\n" * 1000)
    assert len(parts) > 1 and all(len(p) <= messages.MAX_LEN for p in parts)
    assert parts[0].startswith("(1/")


def test_twilio_signature():
    url, params, token = "https://x.com/sms", {"Body": "hi", "From": "+1"}, "secret"
    payload = url + "BodyhiFrom+1"
    sig = base64.b64encode(hmac.new(token.encode(), payload.encode(), hashlib.sha1).digest()).decode()
    assert channels.twilio_signature_valid(url, params, sig, token)
    assert not channels.twilio_signature_valid(url, params, "bad", token)


def test_webhook_endpoint(setup, monkeypatch):
    from tinychef import app as appmod
    monkeypatch.setattr(appmod, "_run_async", lambda fn, *a: fn(*a))
    monkeypatch.setattr(Config, "PUBLIC_BASE_URL", None)
    ch, _ = setup
    c = appmod.app.test_client()
    r = c.post("/sms", data={"From": "+15551112222", "Body": "help"})
    assert r.status_code == 200 and "RECIPE 3" in sent_to(ch, "+15551112222")
    assert c.post("/cron/weekly").status_code == 403


def test_telegram_poll_and_whoami(setup, monkeypatch, capsys):
    from tinychef import telegram_poll
    ch, _ = setup
    monkeypatch.setattr(Config, "RECIPIENTS", ["111"])
    updates = [{"update_id": 5, "message": {"text": "help", "chat": {"id": 111, "first_name": "Sam"}}}]
    calls = []

    def fake_api(method, **p):
        calls.append((method, p))
        return updates if method == "getUpdates" else True

    monkeypatch.setattr(telegram_poll, "_api", fake_api)
    monkeypatch.setattr(service, "due_now", lambda: False)
    telegram_poll.run(poll_once=True)
    assert "RECIPE 3" in sent_to(ch, "111")
    telegram_poll.whoami()
    out = capsys.readouterr().out
    assert "Sam: 111" in out and "RECIPIENTS=111" in out


def test_claude_client_falls_back_when_forced_tool_rejected(monkeypatch):
    from tinychef import planner
    sent = []

    class Resp:
        def __init__(self, code, body):
            self.status_code, self._b, self.text = code, body, str(body)

        def json(self):
            return self._b

    def fake_post(url, headers, json, timeout):
        sent.append(json)
        if json["tool_choice"]["type"] == "tool":
            return Resp(400, {"error": {"message": "tool_choice not supported"}})
        return Resp(200, {"content": [{"type": "text", "text": "ok"},
                                      {"type": "tool_use", "input": {"meals": []}}]})

    monkeypatch.setattr(planner.requests, "post", fake_post)
    c = planner.ClaudeClient(api_key="k", model="m")
    assert c.call_tool("sys", "plan", {"name": "submit_meal_plan"}) == {"meals": []}
    assert sent[1]["tool_choice"] == {"type": "auto"} and "submit_meal_plan tool" in sent[1]["messages"][0]["content"]

    def always_401(url, headers, json, timeout):
        return Resp(401, {"error": {"message": "invalid x-api-key"}})

    monkeypatch.setattr(planner.requests, "post", always_401)
    with pytest.raises(planner.ApiError, match="invalid x-api-key"):
        c.call_tool("sys", "plan", {"name": "t"})


def test_weekly_send_includes_all_recipes_and_swap_sends_changed(setup):
    ch, _ = setup
    service.create_and_send_week(today=date(2026, 11, 14))
    t = sent_to(ch, "+15551112222")
    assert "PREP DAY PLAN" in t
    for i, name in enumerate(["Chicken Tacos", "Salmon Rice Bowls", "Pasta Primavera"], 1):
        assert f"RECIPE {i}: {name}" in t
    ch.sent.clear()
    service.handle_reply("+15551112222", "swap 2")
    t = sent_to(ch, "+15553334444")
    assert "RECIPE 2: Black Bean Bowls" in t and "RECIPE 1:" not in t
    ch.sent.clear()
    service.handle_reply("+15551112222", "recipes")
    t = sent_to(ch, "+15551112222")
    assert all(f"RECIPE {i}:" in t for i in (1, 2, 3))


def test_join_approval_flow(setup, monkeypatch):
    ch, _ = setup
    monkeypatch.setattr(Config, "CHANNEL", "telegram")
    monkeypatch.setattr(Config, "RECIPIENTS", ["111"])
    service.create_and_send_week(today=date(2026, 11, 14))
    ch.sent.clear()

    # Wife messages the bot: she gets a holding reply, the family gets a request
    service.handle_reply("222", "hi", name="Maria")
    assert "asked the family" in sent_to(ch, "222")
    assert "Maria wants to join" in sent_to(ch, "111") and "APPROVE 1" in sent_to(ch, "111")
    service.handle_reply("222", "hello?", name="Maria")  # no duplicate request
    assert sent_to(ch, "111").count("wants to join") == 1

    # Approve with a custom name
    ch.sent.clear()
    service.handle_reply("111", "approve 1 Wife", name="Sam")
    assert "Welcome to Tiny Chef, Wife" in sent_to(ch, "222")
    assert "GROCERY LIST" in sent_to(ch, "222")              # gets this week's plan
    assert "Wife joined Tiny Chef (approved by Sam)" in sent_to(ch, "111")
    assert channels.recipients() == ["111", "222"]

    # She's now a full member: swaps go to both, and she can use commands
    ch.sent.clear()
    service.handle_reply("222", "swap 2")
    assert "Updated (changed 2)" in sent_to(ch, "111") and "Updated (changed 2)" in sent_to(ch, "222")
    service.handle_reply("111", "FAMILY")
    assert "- Wife" in sent_to(ch, "111")

    # Remove
    ch.sent.clear()
    service.handle_reply("111", "remove wife")
    assert "Removed Wife" in sent_to(ch, "111") and channels.recipients() == ["111"]


def test_approve_without_number_and_unknown(setup, monkeypatch):
    ch, _ = setup
    monkeypatch.setattr(Config, "CHANNEL", "telegram")
    monkeypatch.setattr(Config, "RECIPIENTS", ["111"])
    service.handle_reply("111", "APPROVE")
    assert "No one is waiting" in sent_to(ch, "111")
    service.handle_reply("333", "hi", name="Kid")
    service.handle_reply("111", "APPROVE")          # only one pending → approves it
    assert "333" in channels.recipients()
    service.handle_reply("111", "APPROVE 99")
    assert "no join request number 99" in sent_to(ch, "111")
