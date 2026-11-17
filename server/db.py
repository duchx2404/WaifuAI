"""SQLite: nhân vật, tin nhắn, trí nhớ, lịch sinh hoạt, cài đặt."""
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("WAIFUAI_DATA") or ROOT / "data")
IMAGES = DATA / "images"
DB_PATH = DATA / "waifu.db"

_lock = threading.RLock()
_conn = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    gender TEXT NOT NULL DEFAULT 'Nữ',
    age INTEGER NOT NULL DEFAULT 23,
    personality TEXT NOT NULL DEFAULT '',
    appearance TEXT NOT NULL DEFAULT '',
    appearance_tags TEXT NOT NULL DEFAULT '',
    bio TEXT NOT NULL DEFAULT '',
    extra_notes TEXT NOT NULL DEFAULT '',
    user_profile TEXT NOT NULL DEFAULT '',
    relationship TEXT NOT NULL DEFAULT '',
    pronoun_rule TEXT NOT NULL DEFAULT '',
    sample_messages TEXT NOT NULL DEFAULT '[]',
    model_chat TEXT NOT NULL DEFAULT '',
    explicit_enabled INTEGER NOT NULL DEFAULT 1,
    lora_name TEXT NOT NULL DEFAULT '',
    lora_strength REAL NOT NULL DEFAULT 0.8,
    seed INTEGER NOT NULL DEFAULT 0,
    avatar_path TEXT NOT NULL DEFAULT '',
    avatar_status TEXT NOT NULL DEFAULT '',
    avatar_error TEXT NOT NULL DEFAULT '',
    mood TEXT NOT NULL DEFAULT 'bình thường',
    mood_reason TEXT NOT NULL DEFAULT '',
    proactive_enabled INTEGER NOT NULL DEFAULT 1,
    silence_minutes INTEGER NOT NULL DEFAULT 180,
    explicit_turns INTEGER NOT NULL DEFAULT 0,
    last_user_at TEXT NOT NULL DEFAULT '',
    last_proactive_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    image_path TEXT NOT NULL DEFAULT '',
    image_status TEXT NOT NULL DEFAULT '',
    image_prompt TEXT NOT NULL DEFAULT '',
    proactive INTEGER NOT NULL DEFAULT 0,
    rev INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_messages_char ON messages(character_id, id);
CREATE INDEX IF NOT EXISTS ix_messages_rev ON messages(character_id, rev);
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'auto',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    time TEXT NOT NULL,
    activity TEXT NOT NULL,
    proactive INTEGER NOT NULL DEFAULT 0,
    last_fired_date TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Trường nhân vật được sửa từ giao diện Quản lý, kèm kiểu dữ liệu.
CHAR_FIELDS = {
    "name": str, "gender": str, "age": int, "personality": str, "appearance": str,
    "appearance_tags": str, "bio": str, "extra_notes": str, "user_profile": str,
    "relationship": str, "pronoun_rule": str, "sample_messages": list, "model_chat": str,
    "explicit_enabled": bool, "lora_name": str, "lora_strength": float, "seed": int,
    "mood": str, "mood_reason": str, "proactive_enabled": bool, "silence_minutes": int,
}


def init():
    global _conn
    DATA.mkdir(exist_ok=True)
    IMAGES.mkdir(exist_ok=True)
    _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute("PRAGMA foreign_keys=ON")
    _conn.executescript(SCHEMA)
    _conn.commit()


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def q(sql, args=()):
    with _lock:
        return [dict(r) for r in _conn.execute(sql, args).fetchall()]


def one(sql, args=()):
    rows = q(sql, args)
    return rows[0] if rows else None


def ex(sql, args=()):
    with _lock:
        cur = _conn.execute(sql, args)
        _conn.commit()
        return cur.lastrowid


# ---------- nhân vật ----------

def _char_out(row):
    if not row:
        return None
    try:
        row["sample_messages"] = json.loads(row["sample_messages"] or "[]")
    except ValueError:
        row["sample_messages"] = []
    row["explicit_enabled"] = bool(row["explicit_enabled"])
    row["proactive_enabled"] = bool(row["proactive_enabled"])
    return row


def get_character(cid):
    return _char_out(one("SELECT * FROM characters WHERE id=?", (cid,)))


def list_characters():
    return [_char_out(r) for r in q("SELECT * FROM characters ORDER BY id")]


def coerce_char_fields(data):
    out = {}
    for key, typ in CHAR_FIELDS.items():
        if key not in data:
            continue
        val = data[key]
        if typ is list:
            if isinstance(val, str):
                val = [s.strip() for s in val.splitlines() if s.strip()]
            val = json.dumps([str(s) for s in (val or [])], ensure_ascii=False)
        elif typ is bool:
            val = 1 if val else 0
        elif typ is int:
            val = int(val or 0)
        elif typ is float:
            val = float(val or 0)
        else:
            val = str(val or "").strip()
        out[key] = val
    return out


def create_character(fields):
    fields = dict(fields)
    fields.setdefault("created_at", now())
    cols = ",".join(fields)
    marks = ",".join("?" for _ in fields)
    return ex(f"INSERT INTO characters ({cols}) VALUES ({marks})", tuple(fields.values()))


def update_character(cid, fields):
    if not fields:
        return
    sets = ",".join(f"{k}=?" for k in fields)
    ex(f"UPDATE characters SET {sets} WHERE id=?", (*fields.values(), cid))


def delete_character(cid):
    ex("DELETE FROM characters WHERE id=?", (cid,))


# ---------- tin nhắn ----------
# rev tăng mỗi lần thêm/sửa tin, để giao diện Chat chỉ tải phần thay đổi.

def _next_rev():
    return (one("SELECT COALESCE(MAX(rev),0) AS r FROM messages")["r"]) + 1


def add_message(cid, role, content, image_status="", image_prompt="", proactive=False, image_path="", created_at=None):
    with _lock:
        return ex(
            "INSERT INTO messages (character_id, role, content, image_path, image_status, image_prompt, proactive, rev, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (cid, role, content, image_path, image_status, image_prompt, 1 if proactive else 0, _next_rev(), created_at or now()),
        )


def update_message(mid, **fields):
    with _lock:
        fields["rev"] = _next_rev()
        sets = ",".join(f"{k}=?" for k in fields)
        ex(f"UPDATE messages SET {sets} WHERE id=?", (*fields.values(), mid))


def get_message(mid):
    return one("SELECT * FROM messages WHERE id=?", (mid,))


def recent_messages(cid, limit):
    rows = q("SELECT * FROM messages WHERE character_id=? ORDER BY id DESC LIMIT ?", (cid, limit))
    return list(reversed(rows))


def messages_since(cid, rev, limit=200):
    return q("SELECT * FROM messages WHERE character_id=? AND rev>? ORDER BY id LIMIT ?", (cid, rev, limit))


def max_rev():
    return one("SELECT COALESCE(MAX(rev),0) AS r FROM messages")["r"]


def clear_messages(cid):
    ex("DELETE FROM messages WHERE character_id=?", (cid,))


# ---------- trí nhớ ----------

def list_memories(cid):
    return q("SELECT * FROM memories WHERE character_id=? ORDER BY id", (cid,))


def add_memory(cid, content, source="auto"):
    content = (content or "").strip()
    if not content:
        return None
    norm = content.lower()
    for m in list_memories(cid):
        if m["content"].strip().lower() == norm:
            return None
    return ex("INSERT INTO memories (character_id, content, source, created_at) VALUES (?,?,?,?)",
              (cid, content[:400], source, now()))


# ---------- lịch sinh hoạt ----------

def list_schedule(cid):
    rows = q("SELECT * FROM schedule WHERE character_id=? ORDER BY time", (cid,))
    for r in rows:
        r["proactive"] = bool(r["proactive"])
    return rows


def replace_schedule(cid, items):
    old = {r["time"] + "|" + r["activity"]: r["last_fired_date"] for r in list_schedule(cid)}
    with _lock:
        _conn.execute("DELETE FROM schedule WHERE character_id=?", (cid,))
        for it in items:
            key = it["time"] + "|" + it["activity"]
            _conn.execute(
                "INSERT INTO schedule (character_id, time, activity, proactive, last_fired_date) VALUES (?,?,?,?,?)",
                (cid, it["time"], it["activity"], 1 if it.get("proactive") else 0, old.get(key, "")),
            )
        _conn.commit()


# ---------- cài đặt ----------

def load_settings():
    out = {}
    for r in q("SELECT key, value FROM settings"):
        try:
            out[r["key"]] = json.loads(r["value"])
        except ValueError:
            pass
    return out


def save_setting(key, value):
    ex("INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
       (key, json.dumps(value, ensure_ascii=False)))
