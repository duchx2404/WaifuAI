"""Nhập nhân vật từ file xuất của IdolAI (HabitMate) hoặc file xuất của chính WaifuAI.
Token bot Telegram, chatId và các số liệu thói quen của IdolAI được bỏ qua."""
import base64
import datetime as dt
import json
import uuid

from . import db, safety

MOOD_MAP = [("vui", "vui"), ("hao_hung", "hào hứng"), ("doi", "dỗi"), ("hon", "dỗi"), ("buon", "buồn"),
            ("nho", "nhớ nhung"), ("met", "mệt"), ("ngai", "ngại ngùng")]


def _join(v):
    if isinstance(v, list):
        return "; ".join(_text(x) for x in v if _text(x))
    return _text(v)


def _text(x):
    if isinstance(x, str):
        return x.strip()
    if isinstance(x, dict):
        for k in ("content", "text", "fact", "change", "summary"):
            if isinstance(x.get(k), str):
                return x[k].strip()
        return json.dumps(x, ensure_ascii=False)
    return str(x) if x is not None else ""


def _save_data_url(url, cid):
    if not isinstance(url, str) or not url.startswith("data:image/"):
        return ""
    try:
        head, b64 = url.split(",", 1)
        ext = "png" if "png" in head else "webp" if "webp" in head else "jpg"
        name = f"{cid}_{uuid.uuid4().hex[:12]}.{ext}"
        (db.IMAGES / name).write_bytes(base64.b64decode(b64))
        return name
    except (ValueError, OSError):
        return ""


def _ts(v):
    try:
        if isinstance(v, (int, float)) and v > 0:
            return dt.datetime.fromtimestamp(v / 1000 if v > 1e11 else v).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        pass
    return db.now()


def _from_idol(p):
    bible = p.get("characterBible") or {}
    notes = []
    for key, label in (("likes", "Thích"), ("dislikes", "Không thích"), ("quirks", "Thói quen"),
                       ("speechTics", "Cách nhắn tin"), ("backstory", "Quá khứ"), ("ongoingArc", "Đang diễn ra"),
                       ("petsAndCompanions", "Thú cưng / người thân")):
        val = _join(bible.get(key))
        if val:
            notes.append(f"{label}: {val}")
    mood_raw = str((p.get("emotionState") or {}).get("mood") or "")
    mood = next((v for k, v in MOOD_MAP if k in mood_raw), "bình thường")
    return {
        "name": p.get("companionName") or "Nhân vật mới",
        "gender": p.get("companionGender") if p.get("companionGender") in ("Nữ", "Nam") else "Nữ",
        "age": 23,
        "personality": p.get("companionPersonality") or "",
        "appearance": p.get("companionAppearance") or "",
        "bio": p.get("idolBio") or _text(bible.get("identityAndStage")),
        "extra_notes": "\n".join(notes),
        "user_profile": p.get("userCurrentState") or "",
        "relationship": p.get("relationship") or "",
        "pronoun_rule": p.get("pronounRule") or "",
        "sample_messages": [_text(m) for m in (p.get("sampleMessages") or []) if _text(m)],
        "mood": mood,
        "mood_reason": str((p.get("emotionState") or {}).get("reason") or "")[:200],
    }


def _memories_from_idol(p):
    mem = p.get("companionMemory") or {}
    out = []
    for key in ("coreFacts", "patterns", "mutualActions", "emotionalContext", "milestones"):
        out += [_text(x) for x in (mem.get(key) or [])]
    for pr in mem.get("promises") or []:
        if isinstance(pr, dict) and pr.get("content"):
            who = pr.get("promiser") or ""
            out.append(f"Lời hứa{' của ' + who if who else ''}: {pr['content']}")
    return [m for m in out if m]


def _create(fields, memories=(), history=(), avatar_url="", schedule=()):
    for key in ("appearance", "appearance_tags"):
        safety.check(fields.get(key, ""), f"Ngoại hình của '{fields.get('name')}'")
    fields["age"] = max(int(fields.get("age") or 23), safety.MIN_AGE)
    cid = db.create_character(db.coerce_char_fields(fields))
    avatar = _save_data_url(avatar_url, cid)
    if avatar:
        db.update_character(cid, {"avatar_path": avatar, "avatar_status": "done"})
    for m in memories:
        db.add_memory(cid, m, "import")
    for h in history:
        role = "user" if h.get("role") == "user" else "assistant"
        text = _text(h.get("content"))
        photo = _save_data_url(h.get("photo"), cid)
        if text or photo:
            db.add_message(cid, role, text, image_path=photo, image_status="done" if photo else "",
                           created_at=_ts(h.get("ts")))
    if schedule:
        db.replace_schedule(cid, schedule)
    return cid


def import_payload(data):
    if not isinstance(data, dict):
        raise ValueError("File không đúng định dạng")
    created = []
    if data.get("type") == "habitmate_persona":
        created.append(_create(_from_idol(data.get("persona") or {})))
    elif isinstance(data.get("sessions"), list):
        for s in data["sessions"]:
            created.append(_create(_from_idol(s), _memories_from_idol(s), s.get("chatHistory") or [],
                                   s.get("companionAvatarUrl") or ""))
    elif data.get("type") == "waifuai_character":
        ch = dict(data.get("character") or {})
        created.append(_create(ch, data.get("memories") or [], schedule=[
            x for x in (data.get("schedule") or []) if isinstance(x, dict) and x.get("time") and x.get("activity")]))
    else:
        raise ValueError("Không nhận ra file. Hỗ trợ: hồ sơ IdolAI, bản lưu nhiều Idol của IdolAI, file xuất WaifuAI")
    return created


def export_character(cid):
    c = db.get_character(cid)
    keep = {k: c[k] for k in db.CHAR_FIELDS if k in c}
    return {
        "type": "waifuai_character", "version": 1, "exportedAt": db.now(),
        "character": keep,
        "memories": [m["content"] for m in db.list_memories(cid)],
        "schedule": [{"time": s["time"], "activity": s["activity"], "proactive": s["proactive"]}
                     for s in db.list_schedule(cid)],
    }
