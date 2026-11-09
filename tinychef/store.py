"""SQLite storage: weekly plans (with every revision), learned preferences, message log."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import Config

SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_of TEXT NOT NULL,          -- ISO date of the Monday the plan is for
    revision INTEGER NOT NULL,
    plan_json TEXT NOT NULL,
    reason TEXT,                    -- 'weekly' or the reply text that caused a revision
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learned_prefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pref TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    direction TEXT NOT NULL,        -- 'in' or 'out'
    party TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS members (
    chat_id TEXT PRIMARY KEY,       -- people added from chat (in addition to RECIPIENTS in .env)
    name TEXT NOT NULL,
    added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS join_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    requested_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sends (
    week_of TEXT PRIMARY KEY,       -- guards against double weekly sends
    sent_at TEXT NOT NULL
);
"""


def _now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def db(path=None):
    conn = sqlite3.connect(path or Config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def save_plan(week_of, plan, reason):
    with db() as c:
        row = c.execute("SELECT MAX(revision) r FROM plans WHERE week_of=?", (week_of,)).fetchone()
        rev = (row["r"] or 0) + 1
        c.execute(
            "INSERT INTO plans(week_of, revision, plan_json, reason, created_at) VALUES (?,?,?,?,?)",
            (week_of, rev, json.dumps(plan), reason, _now()),
        )
        return rev


def current_plan():
    """Latest revision of the most recent week, or None."""
    with db() as c:
        row = c.execute("SELECT * FROM plans ORDER BY week_of DESC, revision DESC LIMIT 1").fetchone()
        if not row:
            return None
        return {"week_of": row["week_of"], "revision": row["revision"], "plan": json.loads(row["plan_json"])}


def recent_meal_names(weeks=4):
    """Meal names from the last few weeks' final revisions, so new plans avoid repeats."""
    with db() as c:
        rows = c.execute(
            """SELECT p.plan_json FROM plans p
               JOIN (SELECT week_of, MAX(revision) r FROM plans GROUP BY week_of
                     ORDER BY week_of DESC LIMIT ?) w
               ON p.week_of = w.week_of AND p.revision = w.r""",
            (weeks,),
        ).fetchall()
    names = []
    for r in rows:
        names += [m["name"] for m in json.loads(r["plan_json"]).get("meals", [])]
    return names


def add_learned_prefs(prefs):
    with db() as c:
        for p in prefs:
            c.execute("INSERT OR IGNORE INTO learned_prefs(pref, created_at) VALUES (?,?)", (p.strip(), _now()))


def learned_prefs():
    with db() as c:
        return [r["pref"] for r in c.execute("SELECT pref FROM learned_prefs ORDER BY id")]


def clear_learned_prefs():
    with db() as c:
        c.execute("DELETE FROM learned_prefs")


def log_message(direction, party, body):
    with db() as c:
        c.execute(
            "INSERT INTO messages(direction, party, body, created_at) VALUES (?,?,?,?)",
            (direction, party, body, _now()),
        )


def mark_sent(week_of):
    """Returns True if this call claimed the week (i.e. it had not been sent yet)."""
    with db() as c:
        cur = c.execute("INSERT OR IGNORE INTO sends(week_of, sent_at) VALUES (?,?)", (week_of, _now()))
        return cur.rowcount == 1


# --- Family membership -------------------------------------------------------

def members():
    with db() as c:
        return [dict(r) for r in c.execute("SELECT chat_id, name FROM members ORDER BY added_at")]


def add_member(chat_id, name):
    with db() as c:
        c.execute("INSERT OR REPLACE INTO members(chat_id, name, added_at) VALUES (?,?,?)", (chat_id, name, _now()))
        c.execute("DELETE FROM join_requests WHERE chat_id=?", (chat_id,))


def remove_member(chat_id):
    with db() as c:
        return c.execute("DELETE FROM members WHERE chat_id=?", (chat_id,)).rowcount == 1


def add_join_request(chat_id, name):
    """Returns the request number, or None if this person already asked."""
    with db() as c:
        cur = c.execute("INSERT OR IGNORE INTO join_requests(chat_id, name, requested_at) VALUES (?,?,?)",
                        (chat_id, name, _now()))
        return cur.lastrowid if cur.rowcount == 1 else None


def join_requests():
    with db() as c:
        return [dict(r) for r in c.execute("SELECT id, chat_id, name FROM join_requests ORDER BY id")]


def pop_join_request(req_id):
    with db() as c:
        r = c.execute("SELECT id, chat_id, name FROM join_requests WHERE id=?", (req_id,)).fetchone()
        if r:
            c.execute("DELETE FROM join_requests WHERE id=?", (req_id,))
        return dict(r) if r else None
