"""WaifuAI — máy chủ web: giao diện Chat (/chat), giao diện Quản lý (/admin) và API."""
import asyncio
import datetime as dt
import logging
import random
import re
from contextlib import asynccontextmanager
from pathlib import Path

from urllib.parse import quote

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import auth, companion, dates, db, images, importer, llm, prompts, safety, settings

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
    companion.resume_pending()  # tin người chơi gửi lúc máy chủ tắt
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="WaifuAI", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB), name="static")
app.mount("/images", StaticFiles(directory=db.IMAGES, check_dir=False), name="images")


# ---------- đăng nhập ----------

PUBLIC_PATHS = {"/login", "/api/login", "/logout", "/static/common.css", "/static/login.js"}
NO_PASSWORD_MSG = ("Chưa đặt mật khẩu nên WaifuAI chỉ mở được trên chính máy chủ. "
                   "Chạy dat-mat-khau.bat trong thư mục WaifuAI để đặt mật khẩu.")


@app.middleware("http")
async def require_login(request: Request, call_next):
    path = request.url.path
    if path in PUBLIC_PATHS:
        return await call_next(request)
    if auth.enabled():
        if auth.valid_token(request.cookies.get(auth.COOKIE)):
            return await call_next(request)
        if path.startswith("/api/") or request.method != "GET":
            return JSONResponse({"detail": "Cần đăng nhập"}, status_code=401)
        return RedirectResponse("/login?next=" + quote(path, safe="/"), status_code=303)
    # chưa đặt mật khẩu: chỉ cho chính máy này, không qua proxy / mạng ngoài
    if auth.is_direct_local(request):
        return await call_next(request)
    return JSONResponse({"detail": NO_PASSWORD_MSG}, status_code=403)


@app.get("/login")
def login_page():
    return FileResponse(WEB / "login.html", headers={"Cache-Control": "no-cache"})


@app.post("/api/login")
async def login(request: Request, data: dict = Body(...)):
    if not auth.enabled():
        raise HTTPException(403, NO_PASSWORD_MSG)
    key = auth.client_key(request)
    wait = auth.locked_for(key)
    if wait:
        raise HTTPException(429, f"Sai quá nhiều lần, thử lại sau {wait // 60 + 1} phút")
    ok = await asyncio.to_thread(auth.verify_password, str(data.get("password", "")), auth.load()["password"])
    if not ok:
        auth.record_fail(key)
        log.warning("Đăng nhập sai từ %s", key)
        await asyncio.sleep(1)
        raise HTTPException(401, "Sai mật khẩu")
    auth.clear_fails(key)
    res = JSONResponse({"ok": True})
    res.set_cookie(auth.COOKIE, auth.make_token(), max_age=auth.MAX_AGE, httponly=True,
                   samesite="lax", secure=auth.is_https(request), path="/")
    return res


@app.get("/logout")
def logout():
    res = RedirectResponse("/login", status_code=303)
    res.delete_cookie(auth.COOKIE, path="/")
    return res


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
    if fields.get("birthday"):
        b = dates.parse_date(fields["birthday"])
        if not b or b > dt.date.today():
            raise HTTPException(400, "Ngày sinh không hợp lệ (dd/mm/yyyy)")
        tuoi = dates.age_on(b.isoformat(), dt.date.today())
        if tuoi < safety.MIN_AGE:
            raise HTTPException(400, f"Theo ngày sinh nhân vật mới {tuoi} tuổi — phải từ {safety.MIN_AGE} trở lên")
        fields["age"] = tuoi  # tuổi đi theo ngày sinh
    if fields.get("period_start") and not dates.parse_date(fields["period_start"]):
        raise HTTPException(400, "Ngày đến kỳ không hợp lệ (dd/mm/yyyy)")
    for key, (lo, hi), label, unit in (("cycle_length", dates.CYCLE_RANGE, "Chu kỳ", " ngày"),
                                       ("period_length", dates.PERIOD_RANGE, "Số ngày mỗi kỳ", " ngày"),
                                       ("photo_rate", (0, 100), "Tỷ lệ tự gửi ảnh", "%"),
                                       ("photos_max", (1, 5), "Số ảnh tối đa mỗi lần nhắn", " ảnh")):
        if key in fields:
            try:
                v = int(fields[key])
            except (TypeError, ValueError):
                raise HTTPException(400, f"{label} phải là số")
            if not lo <= v <= hi:
                raise HTTPException(400, f"{label} phải từ {lo} đến {hi}{unit}")
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
    c["activity"] = companion.activity_now(c["id"])
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


@app.post("/api/characters/{cid}/face-ref")
def upload_face_ref(cid: int, data: dict = Body(...)):
    """Thêm một ảnh mặt mẫu cho PuLID (data URL), tối đa db.MAX_FACE_REFS ảnh — nhiều ảnh thì PuLID lấy trung bình
    khuôn mặt, giống hơn một ảnh. Thêm ảnh luôn cần tích xác nhận lại (face_ref_ok = 0)."""
    c = _char_or_404(cid)
    refs = c["face_refs"]
    if len(refs) >= db.MAX_FACE_REFS:
        raise HTTPException(400, f"Tối đa {db.MAX_FACE_REFS} ảnh mặt mẫu — xoá bớt trước")
    name = importer._save_data_url(data.get("image"), cid)
    if not name:
        raise HTTPException(400, "Ảnh không hợp lệ (cần PNG / JPG / WEBP)")
    db.update_character(cid, {"face_ref": ",".join(refs + [name]), "face_ref_ok": 0})
    return db.get_character(cid)


@app.delete("/api/characters/{cid}/face-ref")
def delete_face_ref(cid: int, name: str = ""):
    """Xoá một ảnh mặt mẫu (?name=) hoặc tất cả. Còn ảnh thì giữ xác nhận (bớt ảnh không thêm ảnh lạ)."""
    c = _char_or_404(cid)
    refs = c["face_refs"]
    gone = [n for n in refs if not name or n == name]
    if name and not gone:
        raise HTTPException(404, "Không có ảnh mặt mẫu này")
    for n in gone:
        (db.IMAGES / Path(n).name).unlink(missing_ok=True)
    left = [n for n in refs if n not in gone]
    db.update_character(cid, {"face_ref": ",".join(left), "face_ref_ok": int(bool(left and c["face_ref_ok"]))})
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

_clean_schedule = db.clean_schedule


# Lịch HÔM NAY do AI soạn riêng cho từng ngày (lịch mẫu bên dưới chỉ là thói quen để AI tham khảo)

def _today_payload(cid):
    c = db.get_character(cid)
    today = dt.date.today()
    return {"date": today.isoformat(), "weekday": prompts.weekday_vi(today), "workday": prompts.is_workday(c, today),
            "items": db.get_day_schedule(cid, today.isoformat()), "activity": companion.activity_now(cid),
            "planning": companion.is_planning(cid)}


@app.get("/api/characters/{cid}/today")
def get_today(cid: int):
    _char_or_404(cid)
    return _today_payload(cid)


@app.put("/api/characters/{cid}/today")
def put_today(cid: int, data: dict = Body(...)):
    _char_or_404(cid)
    db.replace_day_schedule(cid, dt.date.today().isoformat(), _clean_schedule(data.get("items")))
    return _today_payload(cid)


@app.post("/api/characters/{cid}/today/generate")
async def regenerate_today(cid: int):
    _char_or_404(cid)
    try:
        await companion.plan_day(cid, force=True)
    except llm.LLMError as e:
        raise HTTPException(502, str(e))
    return _today_payload(cid)


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
            "activity": companion.activity_now(cid)}


@app.get("/api/characters/{cid}/messages/before")
def older_messages(cid: int, before: int, limit: int = 50):
    _char_or_404(cid)
    rows = db.q("SELECT * FROM messages WHERE character_id=? AND id<? ORDER BY id DESC LIMIT ?", (cid, before, limit))
    return {"messages": rows[::-1]}


@app.post("/api/characters/{cid}/messages")
async def send_message(cid: int, data: dict = Body(...)):
    _char_or_404(cid)
    try:  # chỉ lưu tin + hẹn giờ; nhân vật trả lời sau reply_delay_seconds (nhắn thêm thì đếm lại)
        await companion.user_message(cid, str(data.get("text", "")), bool(data.get("want_photo")))
    except ValueError as e:
        raise HTTPException(400, str(e))
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


@app.get("/api/logs")
def get_logs(character_id: int = 0, kind: str = "", before: int = 0, limit: int = 200):
    return db.list_logs(character_id or None, kind, before, limit)


@app.post("/api/characters/{cid}/nudge")
async def nudge(cid: int):  # async: cần vòng lặp sự kiện để tạo tác vụ nền
    """Nút "Giục nhắn": trả lời ngay tin đang chờ, hoặc để nhân vật chủ động nhắn."""
    _char_or_404(cid)
    mode = companion.nudge(cid)
    if mode == "busy":
        raise HTTPException(409, "Nhân vật đang soạn tin rồi")
    return {"ok": True, "mode": mode}


@app.post("/api/characters/{cid}/proactive-test")
async def proactive_test(cid: int):
    """Nút trong Quản lý: cho nhân vật chủ động nhắn ngay để thử."""
    _char_or_404(cid)
    try:
        ids = await companion.proactive_message(cid, "Nhân vật tự nhiên muốn nhắn cho người chơi.")
    except llm.LLMError as e:
        raise HTTPException(502, str(e))
    return {"ok": True, "count": len(ids)}
