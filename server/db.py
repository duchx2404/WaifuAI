"""SQLite: nhân vật, tin nhắn, trí nhớ, lịch sinh hoạt, cài đặt."""
import datetime as dt
import json
import os
import re
import sqlite3
import threading
import time
from pathlib import Path

from . import dates

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
    likes TEXT NOT NULL DEFAULT '',
    dislikes TEXT NOT NULL DEFAULT '',
    quirks TEXT NOT NULL DEFAULT '',
    speech_style TEXT NOT NULL DEFAULT '',
    backstory TEXT NOT NULL DEFAULT '',
    ongoing TEXT NOT NULL DEFAULT '',
    companions TEXT NOT NULL DEFAULT '',
    birthday TEXT NOT NULL DEFAULT '',
    period_start TEXT NOT NULL DEFAULT '',
    cycle_length INTEGER NOT NULL DEFAULT 28,
    period_length INTEGER NOT NULL DEFAULT 5,
    anniversaries TEXT NOT NULL DEFAULT '[]',
    events_fired TEXT NOT NULL DEFAULT '',
    work_days TEXT NOT NULL DEFAULT '0,1,2,3,4',
    photo_rate INTEGER NOT NULL DEFAULT 20,
    photos_max INTEGER NOT NULL DEFAULT 3,
    face_ref TEXT NOT NULL DEFAULT '',
    face_ref_ok INTEGER NOT NULL DEFAULT 0,
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
    avatar_source TEXT NOT NULL DEFAULT '',
    face_lock INTEGER NOT NULL DEFAULT 1,
    mood TEXT NOT NULL DEFAULT 'bình thường',
    mood_reason TEXT NOT NULL DEFAULT '',
    pinned INTEGER NOT NULL DEFAULT 0,
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
CREATE TABLE IF NOT EXISTS day_schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    activity TEXT NOT NULL,
    proactive INTEGER NOT NULL DEFAULT 0,
    fired INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_day_schedule ON day_schedule(character_id, date);
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    character_id INTEGER,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    data TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_logs_char ON logs(character_id, id);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Đặc điểm nhân vật, mỗi mục một ô riêng (mỗi ý một dòng). Nhãn trùng với nhãn file IdolAI / ghi chú cũ.
NOTE_FIELDS = [("likes", "Thích"), ("dislikes", "Không thích"), ("quirks", "Thói quen"),
               ("speech_style", "Cách nhắn tin"), ("backstory", "Quá khứ"), ("ongoing", "Đang diễn ra"),
               ("companions", "Thú cưng / người thân")]

# Trường nhân vật được sửa từ giao diện Quản lý, kèm kiểu dữ liệu.
CHAR_FIELDS = {
    "name": str, "gender": str, "age": int, "personality": str, "appearance": str,
    "appearance_tags": str, "bio": str, "extra_notes": str, "user_profile": str,
    **{k: str for k, _ in NOTE_FIELDS},
    "birthday": "date", "period_start": "date", "cycle_length": int, "period_length": int,
    "anniversaries": "anniversaries", "work_days": "weekdays", "photo_rate": int, "photos_max": int, "face_ref_ok": bool,
    "relationship": str, "pronoun_rule": str, "sample_messages": list, "model_chat": str,
    "explicit_enabled": bool, "lora_name": str, "lora_strength": float, "seed": int, "face_lock": bool,
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
    _nang_cap()


def _nang_cap():
    """Thêm cột mới vào cơ sở dữ liệu đã tạo từ bản cũ."""
    # avatar_source: "gen" = app tự vẽ, "import" = ảnh đi kèm file nhập. Chỉ ảnh "gen" được làm mặt mẫu (PuLID).
    them = {"characters": {"pinned": "INTEGER NOT NULL DEFAULT 0",
                           "avatar_source": "TEXT NOT NULL DEFAULT ''",
                           "face_lock": "INTEGER NOT NULL DEFAULT 1",
                           **{k: "TEXT NOT NULL DEFAULT ''" for k, _ in NOTE_FIELDS},
                           "birthday": "TEXT NOT NULL DEFAULT ''", "period_start": "TEXT NOT NULL DEFAULT ''",
                           "cycle_length": "INTEGER NOT NULL DEFAULT 28", "period_length": "INTEGER NOT NULL DEFAULT 5",
                           "anniversaries": "TEXT NOT NULL DEFAULT '[]'", "events_fired": "TEXT NOT NULL DEFAULT ''",
                           "work_days": "TEXT NOT NULL DEFAULT '0,1,2,3,4'",
                           "photo_rate": "INTEGER NOT NULL DEFAULT 20",
                           "photos_max": "INTEGER NOT NULL DEFAULT 3",
                           # ảnh mặt mẫu PuLID người dùng tải lên — chỉ dùng khi đã xác nhận ảnh AI / hư cấu
                           "face_ref": "TEXT NOT NULL DEFAULT ''", "face_ref_ok": "INTEGER NOT NULL DEFAULT 0"}}
    for bang, cot in them.items():
        co = {r["name"] for r in q(f"PRAGMA table_info({bang})")}
        for ten, kieu in cot.items():
            if ten not in co:
                ex(f"ALTER TABLE {bang} ADD COLUMN {ten} {kieu}")
    # Ghi chú cũ gộp "Thích: a; b\nKhông thích: ..." → tách ra từng ô
    cols = ", ".join(k for k, _ in NOTE_FIELDS)
    for r in q(f"SELECT id, extra_notes, {cols} FROM characters WHERE extra_notes != ''"):
        if any(r[k] for k, _ in NOTE_FIELDS):
            continue
        tach = split_notes(r["extra_notes"])
        if len(tach) > 1 or tach.get("extra_notes") != r["extra_notes"]:
            sets = ", ".join(f"{k}=?" for k in tach)
            ex(f"UPDATE characters SET {sets} WHERE id=?", (*tach.values(), r["id"]))


_NOTE_LABEL = {label.lower(): key for key, label in NOTE_FIELDS}


def split_notes(text):
    """'Thích: a; b' (mỗi mục một dòng) → {"likes": "a\\nb", ..., "extra_notes": <dòng không nhận ra>}."""
    out, rest = {}, []
    for line in str(text or "").splitlines():
        label, sep, val = line.partition(":")
        key = _NOTE_LABEL.get(label.strip().lower()) if sep else None
        if not key:
            if line.strip():
                rest.append(line.rstrip())
            continue
        items = [x.strip() for x in val.split(";") if x.strip()]
        if items:
            out[key] = "\n".join(filter(None, [out.get(key, "")] + items))
    out["extra_notes"] = "\n".join(rest)
    return out


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

MAX_FACE_REFS = 6


def face_refs(row):
    """Các ảnh mặt mẫu PuLID (cột face_ref lưu tên file cách nhau dấu phẩy; tên do app sinh, không chứa dấu phẩy)."""
    return [n.strip() for n in (row.get("face_ref") or "").split(",") if n.strip()]


def _char_out(row):
    if not row:
        return None
    try:
        row["sample_messages"] = json.loads(row["sample_messages"] or "[]")
    except ValueError:
        row["sample_messages"] = []
    row["explicit_enabled"] = bool(row["explicit_enabled"])
    row["proactive_enabled"] = bool(row["proactive_enabled"])
    row["pinned"] = bool(row.get("pinned"))
    row["face_lock"] = bool(row.get("face_lock", 1))
    row["face_ref_ok"] = bool(row.get("face_ref_ok"))
    row["face_refs"] = face_refs(row)
    try:
        row["anniversaries"] = json.loads(row.get("anniversaries") or "[]")
    except ValueError:
        row["anniversaries"] = []
    # có ngày sinh thì tuổi tự tăng theo năm (lúc lưu đã chặn dưới 21)
    tuoi = dates.age_on(row.get("birthday"), dt.date.today())
    if tuoi and tuoi >= 21:
        row["age"] = tuoi
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
        elif typ == "date":
            val = dates.iso(val)
        elif typ == "anniversaries":
            val = json.dumps(dates.clean_anniversaries(val), ensure_ascii=False)
        elif typ == "weekdays":  # "0,1,2,3,4" — 0 = Thứ Hai ... 6 = Chủ Nhật
            items = val if isinstance(val, list) else str(val or "").split(",")
            val = ",".join(str(d) for d in sorted({int(x) for x in items if str(x).strip().isdigit() and 0 <= int(x) <= 6}))
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


# ---------- nhật ký (tab Log trong Quản lý) ----------
LOG_KEEP = 3000


def add_log(cid, kind, text, data=None):
    """Ghi một dòng nhật ký: kind = reply / proactive / photo / image / plan / error ..."""
    try:
        with _lock:
            _conn.execute("INSERT INTO logs (ts, character_id, kind, text, data) VALUES (?,?,?,?,?)",
                          (now(), cid, kind, str(text)[:1000],
                           json.dumps(data, ensure_ascii=False)[:4000] if data is not None else ""))
            _conn.execute("DELETE FROM logs WHERE id <= (SELECT MAX(id) FROM logs) - ?", (LOG_KEEP,))
            _conn.commit()
    except sqlite3.Error:
        pass  # nhật ký hỏng không được làm hỏng việc chính


def list_logs(cid=None, kind="", before=0, limit=200):
    sql, args = "SELECT * FROM logs WHERE 1=1", []
    if cid:
        sql += " AND character_id=?"
        args.append(cid)
    if kind:
        sql += " AND kind=?"
        args.append(kind)
    if before:
        sql += " AND id<?"
        args.append(before)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(min(int(limit), 500))
    rows = q(sql, args)
    for r in rows:
        try:
            r["data"] = json.loads(r["data"]) if r["data"] else None
        except ValueError:
            pass
    return rows


_HM = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


def clean_schedule(items):
    """Chuẩn hoá danh sách mốc từ giao diện / mô hình: giờ HH:MM hợp lệ, có việc, sắp theo giờ."""
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        t = str(it.get("time", "")).strip()
        if re.fullmatch(r"\d:[0-5]\d", t):
            t = "0" + t
        a = str(it.get("activity", "")).strip()
        if _HM.fullmatch(t) and a:
            out.append({"time": t, "activity": a[:200], "proactive": bool(it.get("proactive"))})
    return sorted(out, key=lambda x: x["time"])


def get_day_schedule(cid, date):
    rows = q("SELECT * FROM day_schedule WHERE character_id=? AND date=? ORDER BY time", (cid, date))
    for r in rows:
        r["proactive"] = bool(r["proactive"])
        r["fired"] = bool(r["fired"])
    return rows


def has_day_schedule(cid, date):
    return bool(one("SELECT 1 AS x FROM day_schedule WHERE character_id=? AND date=? LIMIT 1", (cid, date)))


def replace_day_schedule(cid, date, items):
    """Lưu lịch của một ngày (giữ dấu đã-nhắn của mốc trùng giờ + việc), dọn lịch cũ hơn 14 ngày."""
    old = {r["time"] + "|" + r["activity"]: r["fired"] for r in get_day_schedule(cid, date)}
    with _lock:
        _conn.execute("DELETE FROM day_schedule WHERE character_id=? AND date=?", (cid, date))
        for it in items:
            _conn.execute(
                "INSERT INTO day_schedule (character_id, date, time, activity, proactive, fired) VALUES (?,?,?,?,?,?)",
                (cid, date, it["time"], it["activity"], 1 if it.get("proactive") else 0,
                 1 if old.get(it["time"] + "|" + it["activity"]) else 0))
        _conn.execute("DELETE FROM day_schedule WHERE date < date(?, '-14 day')", (date,))
        _conn.commit()


def mark_day_slot_fired(slot_id):
    ex("UPDATE day_schedule SET fired=1 WHERE id=?", (slot_id,))


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
