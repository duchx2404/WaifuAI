"""WaifuAI — máy chủ web: giao diện Chat (/chat), giao diện Quản lý (/admin) và API."""
import asyncio
import logging
import random
import re
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import companion, db, images, importer, llm, prompts, safety, settings

WEB = db.ROOT / "web"
log = logging.getLogger("waifuai")


@asynccontextmanager
async def lifespan(_app):
    db.init()
    tasks = [asyncio.create_task(companion.image_worker()), asyncio.create_task(companion.proactive_loop())]
    # Ảnh còn dở từ lần chạy trước: xếp hàng lại
    for m in db.q("SELECT id, character_id, image_prompt FROM messages WHERE image_status='pending'"):
        companion.image_queue.put_nowait({"kind": "message", "message_id": m["id"],
                                          "character_id": m["character_id"], "scene": m["image_prompt"]})
    for c in db.q("SELECT id FROM characters WHERE avatar_status='pending'"):
        companion.image_queue.put_nowait({"kind": "avatar", "character_id": c["id"]})
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="WaifuAI", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB), name="static")
app.mount("/images", StaticFiles(directory=db.IMAGES, check_dir=False), name="images")


@app.get("/")
def index():
    return RedirectResponse("/chat")


@app.get("/chat")
def chat_page():
    return FileResponse(WEB / "chat.html", headers={"Cache-Control": "no-cache"})


@app.get("/admin")
def admin_page():
    return FileResponse(WEB / "admin.html", headers={"Cache-Control": "no-cache"})


def _char_or_404(cid):
    c = db.get_character(cid)
    if not c:
        raise HTTPException(404, "Không tìm thấy nhân vật")
    return c


def _validate_char(fields, partial=False):
    if not partial or "name" in fields:
        if not str(fields.get("name", "")).strip():
            raise HTTPException(400, "Nhân vật cần có tên")
    if "age" in fields:
        try:
            age = int(fields["age"])
        except (TypeError, ValueError):
            raise HTTPException(400, "Tuổi phải là số")
        if age < safety.MIN_AGE:
            raise HTTPException(400, f"Nhân vật phải từ {safety.MIN_AGE} tuổi trở lên")
    if "mood" in fields and fields["mood"] not in prompts.MOODS:
        raise HTTPException(400, "Tâm trạng không hợp lệ")
    try:
        for key in ("appearance", "appearance_tags"):
            if key in fields:
                safety.check(str(fields[key]), "Ngoại hình")
    except safety.Blocked as e:
        raise HTTPException(400, str(e))


# ---------- trạng thái & cài đặt ----------

@app.get("/api/status")
async def status():
    models, img = await asyncio.gather(llm.list_models(), images.options())
    return {
        "ollama": models is not None, "models": models or [],
        "comfy": img is not None, "image_options": img or {},
        "image_queue": companion.image_queue.qsize(),
        "moods": prompts.MOODS, "min_age": safety.MIN_AGE, "hard_negative": safety.HARD_NEGATIVE,
    }


@app.get("/api/settings")
def get_settings():
    return settings.get()


@app.put("/api/settings")
def put_settings(data: dict = Body(...)):
    for key in ("quiet_start", "quiet_end"):
        if key in data and data[key] and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(data[key])):
            raise HTTPException(400, "Giờ yên lặng phải dạng HH:MM")
    try:
        return settings.update(data)
    except (TypeError, ValueError):
        raise HTTPException(400, "Giá trị cài đặt không hợp lệ")


# ---------- nhân vật ----------

def _with_runtime(c):
    c["busy"] = companion.is_busy(c["id"])
    c["activity"] = prompts.current_activity(db.list_schedule(c["id"]))
    last = db.one("SELECT id, role, content, image_path, created_at FROM messages WHERE character_id=? AND role!='system'"
                  " ORDER BY id DESC LIMIT 1", (c["id"],))
    c["last_message"] = last
    return c


@app.get("/api/characters")
def list_chars():
    return [_with_runtime(c) for c in db.list_characters()]


@app.post("/api/characters")
def create_char(data: dict = Body(...)):
    _validate_char(data)
    fields = db.coerce_char_fields(data)
    fields.setdefault("seed", random.randint(1, 2**31 - 1))
    cid = db.create_character(fields)
    return db.get_character(cid)


@app.get("/api/characters/{cid}")
def get_char(cid: int):
    return _with_runtime(_char_or_404(cid))


@app.put("/api/characters/{cid}")
def update_char(cid: int, data: dict = Body(...)):
    _char_or_404(cid)
    _validate_char(data, partial=True)
    db.update_character(cid, db.coerce_char_fields(data))
    return db.get_character(cid)


@app.delete("/api/characters/{cid}")
def delete_char(cid: int):
    _char_or_404(cid)
    db.delete_character(cid)
    return {"ok": True}


@app.post("/api/characters/{cid}/pin")
def pin_char(cid: int, data: dict = Body(default={})):
    """Ghim / bỏ ghim hội thoại để nó nằm trên đầu danh sách Chat."""
    c = _char_or_404(cid)
    want = data.get("pinned")
    if want is None:
        want = not c["pinned"]
    db.update_character(cid, {"pinned": 1 if want else 0})
    return db.get_character(cid)


@app.get("/api/characters/{cid}/export")
def export_char(cid: int):
    _char_or_404(cid)
    return importer.export_character(cid)


@app.post("/api/import")
def import_chars(data: dict = Body(...)):
    try:
        ids = importer.import_payload(data)
    except (ValueError, safety.Blocked) as e:
        raise HTTPException(400, str(e))
    return {"created": ids}


@app.post("/api/characters/{cid}/avatar")
def gen_avatar(cid: int, data: dict = Body(default={})):
    c = _char_or_404(cid)
    if data.get("new_seed"):
        db.update_character(cid, {"seed": random.randint(1, 2**31 - 1)})
    elif not c["seed"]:
        db.update_character(cid, {"seed": random.randint(1, 2**31 - 1)})
    companion.queue_avatar(cid)
    return db.get_character(cid)


@app.post("/api/characters/{cid}/appearance-tags")
async def gen_tags(cid: int, data: dict = Body(default={})):
    c = _char_or_404(cid)
    c.update({k: data[k] for k in ("appearance", "gender", "age") if k in data})
    if not c["appearance"].strip():
        raise HTTPException(400, "Hãy viết mô tả ngoại hình trước")
    try:
        async with companion.gpu_lock:
            raw = await llm.chat(prompts.tags_request(c), schema={
                "type": "object", "properties": {"tags": {"type": "string"}}, "required": ["tags"]}, temperature=0.3)
    except llm.LLMError as e:
        raise HTTPException(502, str(e))
    tags = str((llm.parse_json(raw) or {}).get("tags") or "").strip()
    if not tags:
        raise HTTPException(502, "Mô hình không trả về tag")
    try:
        safety.check(tags, "Tag ngoại hình")
    except safety.Blocked as e:
        raise HTTPException(400, str(e))
    return {"tags": tags}


# ---------- tâm trạng & trí nhớ ----------

@app.get("/api/characters/{cid}/memories")
def list_mem(cid: int):
    _char_or_404(cid)
    return db.list_memories(cid)


@app.post("/api/characters/{cid}/memories")
def add_mem(cid: int, data: dict = Body(...)):
    _char_or_404(cid)
    mid = db.add_memory(cid, str(data.get("content", "")), "manual")
    if not mid:
        raise HTTPException(400, "Trí nhớ trống hoặc đã có")
    return db.one("SELECT * FROM memories WHERE id=?", (mid,))


@app.put("/api/memories/{mid}")
def edit_mem(mid: int, data: dict = Body(...)):
    content = str(data.get("content", "")).strip()
    if not content:
        raise HTTPException(400, "Trí nhớ trống")
    db.ex("UPDATE memories SET content=?, source='manual' WHERE id=?", (content[:400], mid))
    return db.one("SELECT * FROM memories WHERE id=?", (mid,))


@app.delete("/api/memories/{mid}")
def del_mem(mid: int):
    db.ex("DELETE FROM memories WHERE id=?", (mid,))
    return {"ok": True}


# ---------- lịch sinh hoạt ----------

_HM = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


def _clean_schedule(items):
    out = []
    for it in items or []:
        t = str(it.get("time", "")).strip()
        if re.fullmatch(r"\d:[0-5]\d", t):
            t = "0" + t
        a = str(it.get("activity", "")).strip()
        if _HM.fullmatch(t) and a:
            out.append({"time": t, "activity": a[:200], "proactive": bool(it.get("proactive"))})
    return sorted(out, key=lambda x: x["time"])


@app.get("/api/characters/{cid}/schedule")
def get_schedule(cid: int):
    _char_or_404(cid)
    return db.list_schedule(cid)


@app.put("/api/characters/{cid}/schedule")
def put_schedule(cid: int, data: dict = Body(...)):
    _char_or_404(cid)
    items = _clean_schedule(data.get("items"))
    db.replace_schedule(cid, items)
    return db.list_schedule(cid)


@app.post("/api/characters/{cid}/schedule/generate")
async def generate_schedule(cid: int):
    c = _char_or_404(cid)
    try:
        async with companion.gpu_lock:
            raw = await llm.chat(prompts.schedule_request(c), schema=prompts.SCHEDULE_SCHEMA, temperature=0.7)
    except llm.LLMError as e:
        raise HTTPException(502, str(e))
    items = _clean_schedule((llm.parse_json(raw) or {}).get("items"))
    if not items:
        raise HTTPException(502, "Mô hình không trả về lịch hợp lệ, thử lại")
    return {"items": items}  # giao diện cho xem trước, bấm Lưu mới ghi


# ---------- chat ----------

@app.get("/api/characters/{cid}/messages")
def get_messages(cid: int, rev: int = 0, limit: int = 80):
    c = _char_or_404(cid)
    if rev <= 0:
        rows = db.q("SELECT * FROM messages WHERE character_id=? ORDER BY id DESC LIMIT ?", (cid, limit))[::-1]
    else:
        rows = db.messages_since(cid, rev)
    return {"messages": rows, "rev": db.max_rev(), "busy": companion.is_busy(cid),
            "mood": c["mood"], "mood_reason": c["mood_reason"],
            "activity": prompts.current_activity(db.list_schedule(cid))}


@app.get("/api/characters/{cid}/messages/before")
def older_messages(cid: int, before: int, limit: int = 50):
    _char_or_404(cid)
    rows = db.q("SELECT * FROM messages WHERE character_id=? AND id<? ORDER BY id DESC LIMIT ?", (cid, before, limit))
    return {"messages": rows[::-1]}


@app.post("/api/characters/{cid}/messages")
async def send_message(cid: int, data: dict = Body(...)):
    _char_or_404(cid)
    if companion.is_busy(cid):
        raise HTTPException(409, "Nhân vật đang trả lời, chờ chút")
    try:
        await companion.user_message(cid, str(data.get("text", "")), bool(data.get("want_photo")))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except llm.LLMError as e:
        raise HTTPException(502, str(e))
    return {"ok": True, "rev": db.max_rev()}


@app.delete("/api/characters/{cid}/messages")
def clear_messages(cid: int):
    _char_or_404(cid)
    db.clear_messages(cid)
    db.update_character(cid, {"explicit_turns": 0})
    return {"ok": True}


@app.post("/api/messages/{mid}/retry-image")
def retry_image(mid: int):
    m = db.get_message(mid)
    if not m or not m["image_prompt"]:
        raise HTTPException(404, "Tin nhắn không có ảnh")
    if not safety.is_ok(m["image_prompt"]):
        raise HTTPException(400, "Mô tả ảnh này bị chặn")
    db.update_message(mid, image_status="pending")
    companion.image_queue.put_nowait({"kind": "message", "message_id": mid,
                                      "character_id": m["character_id"], "scene": m["image_prompt"]})
    return {"ok": True}


@app.post("/api/characters/{cid}/proactive-test")
async def proactive_test(cid: int):
    """Nút trong Quản lý: cho nhân vật chủ động nhắn ngay để thử."""
    _char_or_404(cid)
    try:
        ids = await companion.proactive_message(cid, "Nhân vật tự nhiên muốn nhắn cho người chơi.")
    except llm.LLMError as e:
        raise HTTPException(502, str(e))
    return {"ok": True, "count": len(ids)}
