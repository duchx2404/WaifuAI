"""Lõi hội thoại: nhận tin, gọi mô hình chữ, cập nhật tâm trạng / trí nhớ, xếp hàng vẽ ảnh, chủ động nhắn."""
import asyncio
import datetime as dt
import logging
import random
import re

from . import db, images, llm, prompts, safety, settings

log = logging.getLogger("waifuai")

# Một GPU 12 GB: chữ và ảnh không chạy chồng lên nhau.
gpu_lock = asyncio.Lock()
image_queue: "asyncio.Queue[dict]" = asyncio.Queue()
_busy = set()  # nhân vật đang soạn tin, để giao diện hiện "đang nhập..."

EXPLICIT = re.compile(
    r"\b(sex|fuck|horny|nude|naked|blowjob|cum|địt|đụ|chịch|nứng|làm tình|ân ái|lên giường|cởi đồ|cởi áo|"
    r"khoả thân|khỏa thân|thủ dâm|bú|liếm|vú|lồn|cặc|buồi|sướng quá|rên)\b",
    re.IGNORECASE,
)
EXPLICIT_STICKY_TURNS = 6


def is_busy(cid):
    return cid in _busy


def pick_model(c, text):
    s = settings.get()
    turns = c["explicit_turns"]
    if EXPLICIT.search(text or "") or c["mood"] == "nứng":
        turns = EXPLICIT_STICKY_TURNS
    else:
        turns = max(0, turns - 1)
    db.update_character(c["id"], {"explicit_turns": turns})
    if c["explicit_enabled"] and turns > 0 and s["model_explicit"]:
        return s["model_explicit"]
    return c["model_chat"] or s["model_chat"]


def history_for(c):
    s = settings.get()
    out = []
    for m in db.recent_messages(c["id"], s["context_messages"]):
        if m["role"] == "system":  # thông báo lỗi, không đưa vào ngữ cảnh
            continue
        content = m["content"]
        if m["image_path"] or m["image_status"] in ("pending", "done"):
            content += " [đã gửi kèm 1 ảnh]"
        role = "user" if m["role"] == "user" else "assistant"
        if out and out[-1]["role"] == role:  # gộp các bong bóng liền nhau
            out[-1]["content"] += "\n" + content
        else:
            out.append({"role": role, "content": content})
    return out


def parse_reply(raw):
    data = llm.parse_json(raw)
    if not isinstance(data, dict):
        text = (raw or "").strip()
        return {"messages": [text] if text else [], "mood": None, "mood_reason": "", "image": "", "memories": []}
    msgs = data.get("messages")
    if isinstance(msgs, str):
        msgs = [msgs]
    msgs = [str(m).strip() for m in (msgs or []) if str(m).strip()][:4]
    image = data.get("image")
    image = image.strip() if isinstance(image, str) else ""
    if image.lower() in ("null", "none", "no", "false"):
        image = ""
    mood = data.get("mood") if data.get("mood") in prompts.MOODS else None
    mems = data.get("memories") or []
    if isinstance(mems, str):
        mems = [mems]
    mems = [str(m).strip()[:300] for m in mems if str(m).strip()][:3]
    return {"messages": msgs, "mood": mood, "mood_reason": str(data.get("mood_reason") or "")[:200],
            "image": image, "memories": mems}


async def _generate(c, extra_note=None, model=None):
    convo = [{"role": "system", "content": prompts.system_prompt(c, db.list_memories(c["id"]), db.list_schedule(c["id"]))}]
    convo += history_for(c)
    if extra_note:
        if convo[-1]["role"] == "user":
            convo[-1]["content"] += "\n\n" + extra_note
        else:
            convo.append({"role": "user", "content": extra_note})
    async with gpu_lock:
        raw = await llm.chat(convo, model=model or c["model_chat"] or None, schema=prompts.REPLY_SCHEMA)
    return parse_reply(raw)


def _store_reply(c, reply, proactive=False):
    s = settings.get()
    ids = []
    msgs = reply["messages"] or ["..."]
    want_image = bool(reply["image"]) and s["image_enabled"]
    for i, text in enumerate(msgs):
        last = i == len(msgs) - 1
        status, prompt = "", ""
        if last and want_image:
            if safety.is_ok(reply["image"]):
                status, prompt = "pending", reply["image"]
            else:
                status, prompt = "blocked", reply["image"]
        mid = db.add_message(c["id"], "assistant", text, image_status=status, image_prompt=prompt, proactive=proactive)
        ids.append(mid)
        if status == "pending":
            image_queue.put_nowait({"kind": "message", "message_id": mid, "character_id": c["id"], "scene": prompt})
    upd = {}
    if reply["mood"] == "nứng" and c["mood"] != "nứng" and not c["explicit_turns"] \
            and not any(EXPLICIT.search(m) for m in msgs):
        reply["mood"] = "ngại ngùng"  # mô hình nhỏ hay tự nhảy sang "nứng" khi chưa có gì gợi tình
    if reply["mood"]:
        upd["mood"] = reply["mood"]
        upd["mood_reason"] = reply["mood_reason"]
    if proactive:
        upd["last_proactive_at"] = db.now()
    db.update_character(c["id"], upd)
    for m in reply["memories"]:
        db.add_memory(c["id"], m, "auto")
    return ids


async def user_message(cid, text, want_photo=False):
    c = db.get_character(cid)
    if not c:
        raise KeyError(cid)
    text = (text or "").strip() or ("Chụp ảnh cho anh xem với 📷" if want_photo else "")
    if not text:
        raise ValueError("Tin nhắn trống")
    db.add_message(cid, "user", text)
    db.update_character(cid, {"last_user_at": db.now()})
    model = pick_model(c, text)
    c = db.get_character(cid)
    _busy.add(cid)
    try:
        reply = await _generate(c, prompts.photo_note() if want_photo else None, model=model)
    except Exception as e:  # lỗi kết nối: báo trong khung chat thay vì mất tin
        db.add_message(cid, "system", f"Lỗi khi soạn trả lời: {e}")
        raise
    finally:
        _busy.discard(cid)
    return _store_reply(c, reply)


async def proactive_message(cid, reason):
    c = db.get_character(cid)
    if not c or cid in _busy:
        return []
    _busy.add(cid)
    try:
        reply = await _generate(c, prompts.proactive_note(reason), model=pick_model(c, ""))
    finally:
        _busy.discard(cid)
    return _store_reply(c, reply, proactive=True)


# ---------- hàng đợi vẽ ảnh ----------

VI_CHARS = re.compile(r"[ăâđêôơưàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ]", re.IGNORECASE)


async def to_english_tags(text, c):
    raw = await llm.chat([
        {"role": "system", "content": "Translate the photo description into English Stable Diffusion tags, comma separated. Output JSON only."},
        {"role": "user", "content": f'{text}\n\nReturn: {{"tags": "..."}}'},
    ], model=c["model_chat"] or None, schema={"type": "object", "properties": {"tags": {"type": "string"}}, "required": ["tags"]},
        temperature=0.2)
    tags = str((llm.parse_json(raw) or {}).get("tags") or "").strip()
    if not tags or VI_CHARS.search(tags):
        raise images.ImageError("Không dịch được mô tả ảnh sang tiếng Anh")
    return tags

def queue_avatar(cid):
    db.update_character(cid, {"avatar_status": "pending", "avatar_error": ""})
    image_queue.put_nowait({"kind": "avatar", "character_id": cid})


async def image_worker():
    while True:
        job = await image_queue.get()
        try:
            await _run_image_job(job)
        except Exception:  # không để worker chết
            log.exception("image job lỗi")
        finally:
            image_queue.task_done()


async def _run_image_job(job):
    c = db.get_character(job["character_id"])
    if not c:
        return
    s = settings.get()
    if job["kind"] == "avatar":
        scene = "portrait, upper body, looking at viewer, smile, simple background, soft lighting"
        seed = c["seed"] or None
    else:
        scene = job["scene"]
        seed = None
    try:
        if VI_CHARS.search(scene):  # SDXL không hiểu tiếng Việt: dịch sang tag trước khi vẽ
            async with gpu_lock:
                scene = await to_english_tags(scene, c)
            safety.check(scene, "Câu mô tả ảnh")
        async with gpu_lock:
            if s["vram_swap"]:
                await llm.unload_all()
            try:
                name = await images.generate(c, scene, seed=seed)
            finally:
                if s["vram_swap"]:
                    await images.free_vram()
    except safety.Blocked as e:
        _image_failed(job, "blocked", str(e))
        return
    except Exception as e:
        _image_failed(job, "error", str(e))
        return
    if job["kind"] == "avatar":
        db.update_character(c["id"], {"avatar_path": name, "avatar_status": "done", "avatar_error": ""})
    else:
        db.update_message(job["message_id"], image_path=name, image_status="done", image_prompt=scene)


def _image_failed(job, status, err):
    log.warning("vẽ ảnh thất bại: %s", err)
    if job["kind"] == "avatar":
        db.update_character(job["character_id"], {"avatar_status": status, "avatar_error": err[:300]})
    else:
        db.update_message(job["message_id"], image_status=status)


# ---------- chủ động nhắn ----------

def _in_quiet(now, s):
    hm = now.strftime("%H:%M")
    a, b = s["quiet_start"], s["quiet_end"]
    if not a or not b or a == b:
        return False
    return (a <= hm or hm < b) if a > b else (a <= hm < b)


def _parse(ts):
    try:
        return dt.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


async def proactive_tick(now=None):
    now = now or dt.datetime.now()
    s = settings.get()
    if not s["proactive_enabled"] or _in_quiet(now, s):
        return
    today, hm = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
    window_start = (now - dt.timedelta(minutes=10)).strftime("%H:%M")
    for c in db.list_characters():
        if not c["proactive_enabled"] or c["id"] in _busy:
            continue
        # 1) Mốc lịch có đánh dấu chủ động nhắn
        slot = next((x for x in db.list_schedule(c["id"])
                     if x["proactive"] and x["last_fired_date"] != today and window_start <= x["time"] <= hm), None)
        if slot:
            db.ex("UPDATE schedule SET last_fired_date=? WHERE id=?", (today, slot["id"]))
            await _safe_proactive(c["id"], f"Nhân vật vừa tới mốc lịch: {slot['activity']}.")
            continue
        # 2) Người chơi im lặng quá lâu (chỉ nhắn 1 lần cho mỗi đợt im lặng)
        last_user = _parse(c["last_user_at"])
        last_pro = _parse(c["last_proactive_at"])
        if c["silence_minutes"] > 0 and last_user and (not last_pro or last_pro < last_user):
            if now - last_user >= dt.timedelta(minutes=c["silence_minutes"]):
                mins = int((now - last_user).total_seconds() // 60)
                await _safe_proactive(c["id"], f"Người chơi đã im lặng {mins // 60} giờ {mins % 60} phút chưa nhắn gì.")
                # đánh dấu đã nhắn cho đợt im lặng này (kể cả khi gọi mô hình lỗi, để không thử lại mỗi 30 giây)
                db.update_character(c["id"], {"last_proactive_at": now.strftime("%Y-%m-%d %H:%M:%S")})


async def _safe_proactive(cid, reason):
    try:
        await proactive_message(cid, reason)
    except Exception as e:
        log.warning("chủ động nhắn lỗi: %s", e)


async def proactive_loop():
    await asyncio.sleep(random.uniform(5, 15))
    while True:
        try:
            await proactive_tick()
        except Exception:
            log.exception("proactive_tick lỗi")
        await asyncio.sleep(30)
