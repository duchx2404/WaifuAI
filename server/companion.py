"""Lõi hội thoại: nhận tin, gọi mô hình chữ, cập nhật tâm trạng / trí nhớ, xếp hàng vẽ ảnh, chủ động nhắn."""
import asyncio
import datetime as dt
import logging
import random
import re
import time

from . import dates, db, images, llm, prompts, safety, settings

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


MAX_PHOTOS = 5  # trần cứng số ảnh một lượt (mỗi nhân vật đặt riêng photos_max ≤ trần này)


def photos_max(c):
    return min(MAX_PHOTOS, max(1, int(c.get("photos_max") or 1)))


def roll_photo(c):
    """Nhân vật tự gửi kèm ảnh lần này? Theo 'Tỷ lệ tự gửi ảnh' của nhân vật (mô hình tự quyết thì gần như không gửi).
    Mỗi lần gieo đều ghi vào nhật ký để xem lại ở tab Log."""
    if not settings.get()["image_enabled"]:
        db.add_log(c["id"], "photo", "Không gửi ảnh: đang tắt \"Cho nhân vật gửi ảnh\" trong Cài đặt")
        return False
    rate = int(c.get("photo_rate") or 0)
    if rate >= 100 or rate <= 0:  # 100% luôn gửi, 0% chỉ gửi khi người chơi xin — không gieo
        db.add_log(c["id"], "photo", f"Tỷ lệ {rate}% → {'luôn GỬI ẢNH' if rate >= 100 else 'không tự gửi (chỉ gửi khi bạn xin)'}",
                   {"rate": rate, "hit": rate >= 100})
        return rate >= 100
    roll = random.random() * 100
    hit = roll < rate
    db.add_log(c["id"], "photo",
               f"Tỷ lệ {rate}% · số ngẫu nhiên 0–100 ra {roll:.1f} "
               + (f"(dưới {rate}) → GỬI ẢNH" if hit else f"(không dưới {rate}, rơi vào {100 - rate}% không gửi) → không gửi"),
               {"roll": round(roll, 2), "rate": rate, "hit": hit})
    return hit


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
        return {"messages": [text] if text else [], "mood": None, "mood_reason": "", "images": [], "memories": []}
    msgs = data.get("messages")
    if isinstance(msgs, str):
        msgs = [msgs]
    msgs = [str(m).strip() for m in (msgs or []) if str(m).strip()][:4]
    raw_imgs = data.get("images")
    if raw_imgs is None:
        raw_imgs = data.get("image")  # khuôn cũ: một ảnh dạng chuỗi
    if isinstance(raw_imgs, str):
        raw_imgs = [raw_imgs]
    images = [str(x).strip() for x in (raw_imgs or []) if isinstance(x, (str, int, float)) and str(x).strip()]
    images = [x for x in images if x.lower() not in ("null", "none", "no", "false")][:MAX_PHOTOS]
    mood = data.get("mood") if data.get("mood") in prompts.MOODS else None
    mems = data.get("memories") or []
    if isinstance(mems, str):
        mems = [mems]
    mems = [str(m).strip()[:300] for m in mems if str(m).strip()][:3]
    return {"messages": msgs, "mood": mood, "mood_reason": str(data.get("mood_reason") or "")[:200],
            "images": images, "memories": mems}


# ---------- lịch từng ngày (AI soạn mới mỗi ngày; lịch mẫu chỉ là thói quen tham khảo) ----------

_planning = set()
_plan_fail = {}  # cid -> lúc soạn lịch lỗi gần nhất (thử lại sau 10 phút)


def is_planning(cid):
    return cid in _planning


def schedule_view(cid, now=None):
    """(lịch hôm nay, việc lúc trước mốc đầu tiên). Hôm nay chưa soạn thì tạm dùng lịch mẫu."""
    now = now or dt.datetime.now()
    template = None
    today = db.get_day_schedule(cid, now.date().isoformat())
    if not today:
        template = db.list_schedule(cid)
        today = template
    yest = db.get_day_schedule(cid, (now.date() - dt.timedelta(days=1)).isoformat())
    if not yest:
        yest = template if template is not None else db.list_schedule(cid)
    return today, (yest[-1]["activity"] if yest else "")


def activity_now(cid, now=None):
    today, before = schedule_view(cid, now)
    return prompts.current_activity(today, now, before)


async def plan_day(cid, day=None, force=False):
    """Soạn lịch riêng cho một ngày (mặc định hôm nay) và lưu lại."""
    day = day or dt.date.today()
    iso = day.isoformat()
    if not force and db.has_day_schedule(cid, iso):
        return db.get_day_schedule(cid, iso)
    c = db.get_character(cid)
    if not c:
        return []
    yesterday = db.get_day_schedule(cid, (day - dt.timedelta(days=1)).isoformat())
    recent = [("Người chơi: " if m["role"] == "user" else "Nhân vật: ") + m["content"]
              for m in db.recent_messages(cid, 24) if m["role"] != "system" and m["content"]]
    req = prompts.day_plan_request(c, day, db.list_schedule(cid), yesterday, db.list_memories(cid), recent)
    _planning.add(cid)
    try:
        async with gpu_lock:
            raw = await llm.chat(req, model=c["model_chat"] or None, schema=prompts.SCHEDULE_SCHEMA, temperature=0.95)
    finally:
        _planning.discard(cid)
    items = db.clean_schedule((llm.parse_json(raw) or {}).get("items"))
    if len(items) < 4:
        raise llm.LLMError("Mô hình không trả về lịch hợp lệ, thử lại")
    db.replace_day_schedule(cid, iso, items)
    log.info("đã soạn lịch %s cho nhân vật %s (%d mốc)", iso, cid, len(items))
    db.add_log(cid, "plan", f"AI soạn lịch {prompts.weekday_vi(day)} {day.strftime('%d/%m')} "
                            f"({'ngày đi làm' if prompts.is_workday(c, day) else 'ngày nghỉ'}): {len(items)} mốc",
               {"items": [f"{x['time']} {'[nhắn] ' if x['proactive'] else ''}{x['activity']}" for x in items]})
    return db.get_day_schedule(cid, iso)


async def plan_tick(now=None):
    """Nhân vật nào chưa có lịch hôm nay thì soạn (mỗi lượt một nhân vật cho đỡ chiếm GPU)."""
    now = now or dt.datetime.now()
    iso = now.date().isoformat()
    for c in db.list_characters():
        if db.has_day_schedule(c["id"], iso) or c["id"] in _busy:
            continue
        if time.monotonic() - _plan_fail.get(c["id"], -1e9) < 600:
            continue
        try:
            await plan_day(c["id"], now.date())
        except Exception as e:
            _plan_fail[c["id"]] = time.monotonic()
            log.warning("soạn lịch hôm nay lỗi (%s): %s", c["name"], e)
            db.add_log(c["id"], "error", f"Soạn lịch hôm nay lỗi, 10 phút nữa thử lại: {e}")
        return


async def _generate(c, extra_note=None, model=None):
    her = [m["content"] for m in db.recent_messages(c["id"], 40) if m["role"] == "assistant"]
    used = prompts.recent_phrases(her[-24:])
    today, before = schedule_view(c["id"])
    convo = [{"role": "system", "content": prompts.system_prompt(c, db.list_memories(c["id"]), today,
                                                                 used_phrases=used, before_first=before)}]
    convo += history_for(c)
    if extra_note:
        if convo[-1]["role"] == "user":
            convo[-1]["content"] += "\n\n" + extra_note
        else:
            convo.append({"role": "user", "content": extra_note})
    reply = await _ask(convo, model or c["model_chat"] or None)
    cut = _cut_message(reply["messages"])
    if cut:  # bỏ dở giữa câu → soạn lại một lần
        db.add_log(c["id"], "error", "Câu trả lời bị bỏ dở giữa câu → soạn lại", {"messages": reply["messages"], "tokens": reply["_meta"]})
        fix = (f"(Ghi chú hệ thống: bản nháp vừa rồi bị bỏ dở giữa câu: «{cut}». Viết lại cả lượt trả lời, "
               "mỗi tin là câu trọn vẹn. Không nhắc tới ghi chú này.)")
        retry = convo[:-1] + [{"role": convo[-1]["role"], "content": convo[-1]["content"] + "\n\n" + fix}] \
            if convo[-1]["role"] == "user" else convo + [{"role": "user", "content": fix}]
        again = await _ask(retry, model or c["model_chat"] or None)
        if again["messages"] and not _cut_message(again["messages"]):
            reply = again
    return reply


async def _ask(convo, model):
    async with gpu_lock:
        raw = await llm.chat(convo, model=model, schema=prompts.REPLY_SCHEMA)
    reply = parse_reply(raw)
    reply["messages"] = _join_fragments(reply["messages"])
    reply["_meta"] = dict(llm.last_meta)
    return reply


_END = re.compile(r"[.!?…~)*\]\"'”»:;]\s*$|[\U0001F300-\U0001FAFF☀-➿]\s*$")
# từ không thể đứng cuối một câu trọn vẹn
_DANGLING = {"để", "là", "và", "mà", "thì", "của", "với", "cho", "vì", "nên", "nhưng", "hay", "hoặc", "khi", "nếu",
             "rằng", "những", "các", "một", "đang", "sẽ", "đã", "bị", "được", "ở", "tại", "từ", "đến", "như", "bằng", "lúc"}


def _dangling(m):
    """Tin rõ ràng bị bỏ dở: kết thúc bằng dấu phẩy hoặc từ nối (không thể đứng cuối câu)."""
    t = m.rstrip()
    if not t or _END.search(t):
        return False
    words = t.split()
    last = re.sub(r"[^\w]+$", "", words[-1].lower()) if words else ""
    return t.endswith(",") or last in _DANGLING


def _join_fragments(msgs):
    """Mô hình hay cắt một câu ra hai tin ('...là để' + 'đòi'): tin trước bỏ dở (từ nối / dấu phẩy)
    thì ghép tin sau vào. Hai tin thường ngày không dấu chấm ('em vừa chụp nè', 'đẹp hông') giữ nguyên."""
    out = []
    for m in msgs:
        if out and _dangling(out[-1]):
            out[-1] = out[-1].rstrip() + " " + m.lstrip()
        else:
            out.append(m)
    return out


def _cut_message(msgs):
    """Tin bị bỏ dở → trả về tin đó, không thì ''."""
    return next((m for m in msgs if _dangling(m)), "")


def _store_reply(c, reply, proactive=False):
    s = settings.get()
    ids = []
    msgs = reply["messages"] or ["..."]
    images = (reply.get("images") or [])[:photos_max(c)] if s["image_enabled"] else []
    # ảnh đầu gắn vào tin cuối; mỗi ảnh sau là một bong bóng ảnh riêng (như chụp liền mấy tấm)
    rows = [(t, images[0] if (i == len(msgs) - 1 and images) else "") for i, t in enumerate(msgs)]
    rows += [("", scene) for scene in images[1:]]
    for text, scene in rows:
        status = ("pending" if safety.is_ok(scene) else "blocked") if scene else ""
        mid = db.add_message(c["id"], "assistant", text, image_status=status, image_prompt=scene, proactive=proactive)
        ids.append(mid)
        if status == "pending":
            image_queue.put_nowait({"kind": "message", "message_id": mid, "character_id": c["id"], "scene": scene})
            db.add_log(c["id"], "image", f"Xếp hàng vẽ ảnh cho tin #{mid} (đang chờ trước: {image_queue.qsize() - 1})",
                       {"message_id": mid, "scene": scene})
        elif status == "blocked":
            db.add_log(c["id"], "image", f"Ảnh tin #{mid} bị bộ lọc an toàn chặn", {"message_id": mid, "scene": scene})
    db.add_log(c["id"], "proactive" if proactive else "reply",
               f"Đã gửi {len(msgs)} tin" + (f" + {len(images)} ảnh" if images else " (không kèm ảnh)")
               + (f" · tâm trạng {reply['mood']}" if reply["mood"] else ""),
               {"messages": msgs, "images": images, "message_ids": ids, "memories": reply["memories"],
                "tokens": reply.get("_meta")})
    meta = reply.get("_meta") or {}
    if meta.get("done_reason") == "length" or (meta.get("prompt_tokens") or 0) > (meta.get("num_ctx") or 8192) - 600:
        db.add_log(c["id"], "error", f"Lời nhắc gần chạm giới hạn ngữ cảnh ({meta.get('prompt_tokens')}/{meta.get('num_ctx')} token, "
                                     f"dừng vì {meta.get('done_reason')}) — có thể bị cắt; giảm 'Số tin nhắn đưa vào ngữ cảnh'", meta)
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


# Trả lời có hẹn giờ: chờ reply_delay_seconds kể từ tin CUỐI của người chơi, nhắn thêm thì đếm lại.
_timers: "dict[int, asyncio.Task]" = {}
_want_photo: "dict[int, bool]" = {}


def reply_pending(cid):
    t = _timers.get(cid)
    return bool(t and not t.done())


async def user_message(cid, text, want_photo=False):
    """Lưu tin của người chơi rồi hẹn giờ trả lời (không chờ mô hình soạn xong)."""
    c = db.get_character(cid)
    if not c:
        raise KeyError(cid)
    text = (text or "").strip() or ("Chụp ảnh cho anh xem với 📷" if want_photo else "")
    if not text:
        raise ValueError("Tin nhắn trống")
    db.add_message(cid, "user", text)
    db.update_character(cid, {"last_user_at": db.now()})
    if want_photo:
        _want_photo[cid] = True
    schedule_reply(cid)


def schedule_reply(cid, delay=None):
    old = _timers.get(cid)
    if old and not old.done():
        old.cancel()
    if delay is None:
        delay = max(0, int(settings.get()["reply_delay_seconds"]))
    _timers[cid] = asyncio.create_task(_reply_after(cid, delay))


async def _reply_after(cid, delay):
    try:
        await asyncio.sleep(delay)
        while cid in _busy:  # đang soạn tin khác (chủ động nhắn): đợi xong
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        return
    if _timers.get(cid) is asyncio.current_task():
        _timers.pop(cid, None)  # từ đây tin mới của người chơi sẽ hẹn một lượt trả lời mới
    try:
        await reply_now(cid)
    except Exception as e:  # lỗi kết nối: báo trong khung chat thay vì mất tin
        log.warning("soạn trả lời lỗi: %s", e)
        db.add_log(cid, "error", f"Soạn trả lời lỗi: {e}")
        db.add_message(cid, "system", f"Lỗi khi soạn trả lời: {e}")


def _unanswered(cid):
    """Các tin người chơi gửi sau câu trả lời gần nhất của nhân vật."""
    out = []
    for m in reversed(db.recent_messages(cid, 40)):
        if m["role"] == "assistant":
            break
        if m["role"] == "user":
            out.append(m["content"])
    return out[::-1]


async def reply_now(cid):
    c = db.get_character(cid)
    if not c:
        return []
    want_photo = _want_photo.pop(cid, False)
    pending = _unanswered(cid)
    model = pick_model(c, "\n".join(pending))
    c = db.get_character(cid)
    db.add_log(cid, "reply", f"Bắt đầu soạn trả lời cho {len(pending)} tin của người chơi · mô hình {model}",
               {"user_messages": pending})
    if want_photo:
        db.add_log(cid, "photo", "Người chơi bấm xin ảnh → bắt buộc gửi ảnh (không gieo)")
    photo = want_photo or roll_photo(c)
    note = None
    if photo:
        sit, act, n = _situation(cid), activity_now(cid), photos_max(c)
        note = prompts.photo_note(sit, act, n) if want_photo else prompts.selfie_note(sit, act, n)
    _busy.add(cid)
    try:
        reply = await _generate(c, note, model=model)
    finally:
        _busy.discard(cid)
    if photo:
        _ensure_image(cid, reply)
    return _store_reply(c, reply)


def _situation(cid, n=6):
    """Mấy tin gần nhất (cả hai bên) để ảnh khớp đúng việc nhân vật vừa kể."""
    msgs = [m for m in db.recent_messages(cid, 20) if m["role"] in ("user", "assistant") and m["content"]]
    return [("Người chơi: " if m["role"] == "user" else "Nhân vật: ") + m["content"][:200] for m in msgs[-n:]]


def _ensure_image(cid, reply):
    """Đã quyết gửi ảnh mà mô hình bỏ trống trường image: lấy tin vừa nhắn + việc theo lịch làm cảnh (sẽ dịch sang tag)."""
    if reply.get("images"):
        db.add_log(cid, "photo", f"Mô hình đã tả cảnh {len(reply['images'])} ảnh", {"scenes": reply["images"]})
        return
    said = " ".join(reply.get("messages") or [])[:200]
    scene = ", ".join(x for x in (said, activity_now(cid)) if x)
    reply["images"] = ["selfie, " + (scene or "ở nhà")]
    db.add_log(cid, "photo", "Mô hình bỏ trống mô tả ảnh → dùng cảnh dự phòng theo tin vừa nhắn + lịch",
               {"scenes": reply["images"]})


def nudge(cid):
    """Nút "Giục nhắn" trong Chat: còn tin chưa trả lời thì trả lời ngay (bỏ thời gian chờ), không thì nhân vật nhắn trước."""
    if cid in _busy:
        return "busy"
    if _unanswered(cid):
        db.add_log(cid, "nudge", "Người chơi bấm Giục nhắn → trả lời ngay, bỏ thời gian chờ")
        schedule_reply(cid, delay=0)
        return "reply"
    db.add_log(cid, "nudge", "Người chơi bấm Giục nhắn → nhân vật chủ động nhắn trước")
    old = _timers.pop(cid, None)
    if old and not old.done():
        old.cancel()
    _busy.add(cid)  # hiện "đang nhập..." ngay, trước khi tác vụ nền kịp chạy

    async def run():
        _busy.discard(cid)
        await _safe_proactive(cid, "Người chơi đang chờ và muốn nhân vật nhắn cho mình ngay. Nhắn trước một cách tự nhiên, "
                                   "hợp với việc nhân vật đang làm và chuyện hai người vừa nói.")
    asyncio.create_task(run())
    return "proactive"


def resume_pending():
    """Khởi động lại máy chủ khi còn tin chưa trả lời: hẹn trả lời sau ít giây."""
    for c in db.list_characters():
        last = db.one("SELECT role FROM messages WHERE character_id=? AND role!='system' ORDER BY id DESC LIMIT 1",
                      (c["id"],))
        if last and last["role"] == "user":
            schedule_reply(c["id"], delay=10)


async def proactive_message(cid, reason):
    c = db.get_character(cid)
    if not c or cid in _busy or reply_pending(cid):
        return []
    db.add_log(cid, "proactive", f"Chủ động nhắn: {reason}")
    photo = roll_photo(c)
    note = prompts.proactive_note(reason) + (
        "\n" + prompts.selfie_note(_situation(cid), activity_now(cid), photos_max(c)) if photo else "")
    _busy.add(cid)
    try:
        reply = await _generate(c, note, model=pick_model(c, ""))
    finally:
        _busy.discard(cid)
    if photo:
        _ensure_image(cid, reply)
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
    what = "ảnh đại diện" if job["kind"] == "avatar" else f"ảnh tin #{job['message_id']}"
    t0 = time.monotonic()
    try:
        if VI_CHARS.search(scene):  # SDXL không hiểu tiếng Việt: dịch sang tag trước khi vẽ
            async with gpu_lock:
                scene = await to_english_tags(scene, c)
            safety.check(scene, "Câu mô tả ảnh")
            db.add_log(c["id"], "image", f"Dịch mô tả {what} sang tag tiếng Anh", {"tags": scene})
        db.add_log(c["id"], "image", f"Bắt đầu vẽ {what}", {"scene": scene, "lora": c.get("lora_name") or ""})
        async with gpu_lock:
            if s["vram_swap"]:
                await llm.unload_all()
            try:
                # ảnh đại diện vẽ theo ảnh mặt mẫu đã xác nhận nếu có; không có thì nó là nơi TẠO ra khuôn mặt
                # → không khoá mặt theo ảnh đại diện cũ
                has_ref = bool(c.get("face_ref") and c.get("face_ref_ok"))
                name = await images.generate(c, scene, seed=seed, use_face=job["kind"] != "avatar" or has_ref)
                db.add_log(c["id"], "image", "Gửi kèm ảnh mặt mẫu (PuLID)" if images.last_face else "Vẽ không có ảnh mặt mẫu",
                           {"face": images.last_face})
            finally:
                if s["vram_swap"]:
                    await images.free_vram()
    except safety.Blocked as e:
        _image_failed(job, "blocked", str(e))
        return
    except Exception as e:
        _image_failed(job, "error", str(e))
        return
    db.add_log(c["id"], "image", f"Vẽ xong {what} sau {time.monotonic() - t0:.0f} giây", {"file": name})
    if job["kind"] == "avatar":
        db.update_character(c["id"], {"avatar_path": name, "avatar_status": "done", "avatar_error": "", "avatar_source": "gen"})
    else:
        db.update_message(job["message_id"], image_path=name, image_status="done", image_prompt=scene)


def _image_failed(job, status, err):
    log.warning("vẽ ảnh thất bại: %s", err)
    what = "ảnh đại diện" if job["kind"] == "avatar" else f"ảnh tin #{job.get('message_id')}"
    db.add_log(job["character_id"], "error" if status == "error" else "image",
               f"{'Bị chặn' if status == 'blocked' else 'Vẽ lỗi'} {what}: {err}", {"scene": job.get("scene", "")})
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
        if not c["proactive_enabled"] or c["id"] in _busy or reply_pending(c["id"]):
            continue
        # 0) Sinh nhật / ngày kỷ niệm: nhắn một lần trong ngày, sau 8 giờ sáng
        if hm >= "08:00" and c.get("events_fired") != today:
            ev = dates.today_events(c, now.date())
            if ev:
                db.update_character(c["id"], {"events_fired": today})  # đánh dấu trước, lỗi cũng không thử lại liên tục
                await _safe_proactive(c["id"], "Hôm nay là ngày đặc biệt: " + "; ".join(ev)
                                      + ". Nhân vật nhắn cho người chơi về ngày này một cách tình cảm, tự nhiên.")
                continue
        # 1) Mốc lịch có đánh dấu chủ động nhắn
        day_plan = db.get_day_schedule(c["id"], today)
        if day_plan:  # lịch AI soạn cho hôm nay
            slot = next((x for x in day_plan if x["proactive"] and not x["fired"] and window_start <= x["time"] <= hm), None)
            if slot:
                db.mark_day_slot_fired(slot["id"])
        else:  # chưa soạn được lịch hôm nay: dùng lịch mẫu
            slot = next((x for x in db.list_schedule(c["id"])
                         if x["proactive"] and x["last_fired_date"] != today and window_start <= x["time"] <= hm), None)
            if slot:
                db.ex("UPDATE schedule SET last_fired_date=? WHERE id=?", (today, slot["id"]))
        if slot:
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
        db.add_log(cid, "error", f"Chủ động nhắn lỗi: {e}")


async def proactive_loop():
    await asyncio.sleep(random.uniform(5, 15))
    while True:
        try:
            await plan_tick()  # soạn lịch hôm nay trước, để mốc chủ động nhắn đi theo lịch mới
        except Exception:
            log.exception("plan_tick lỗi")
        try:
            await proactive_tick()
        except Exception:
            log.exception("proactive_tick lỗi")
        await asyncio.sleep(30)
