"""Gọi ComfyUI (SDXL) để vẽ ảnh nhân vật."""
import asyncio
import logging
import random
import re
import uuid
from pathlib import Path

import httpx

from . import db, safety, settings

_client = httpx.AsyncClient(timeout=httpx.Timeout(120, connect=10))
log = logging.getLogger("waifuai.images")


class ImageError(RuntimeError):
    pass


GENDER_TAGS = {"Nữ": "1girl, solo, woman", "Nam": "1boy, solo, man"}


def lora_trigger(lora_name):
    """LoRA do tools/lora_1_anh tạo tên wf_<ten>.safetensors, từ khoá kích hoạt chính là wf_<ten>."""
    stem = Path(lora_name or "").stem
    return stem if stem.startswith("wf_") else ""


def _age_look(gender, age):
    """Giữ đúng độ tuổi trên ảnh: 21–29 tuổi thì nói rõ 'young adult' và cấm vẽ già (SDXL tả thực hay vẽ già hơn tuổi)."""
    if age >= 30:
        return "", ""
    if gender == "Nam":
        return "young adult man", "middle-aged, old man, wrinkles, aged skin"
    return "young adult woman", "middle-aged, milf, mature woman, old woman, wrinkles, aged skin"


_TOUCH = re.compile(r"\b(hug\w*|cuddl\w*|embrac\w*|kiss\w*|lying next to|spooning|holding hands|couple|sex|missionary|cowgirl|doggystyle)\b", re.I)
_PARTNER = re.compile(r"\b(pov|1boy|faceless male|boyfriend|viewer)\b", re.I)
_MALE = re.compile(r"\b(1boy|faceless male|hetero|boyfriend)\b", re.I)
SINGLE_NEGATIVE = ("2girls, multiple girls, twins, clone, duplicate person, two women, multiple faces, two faces, "
                   "yuri, girls kissing")
# tag tương tác "trơn" (không nói với ai) → viết lại thành hướng về người xem (người chơi)
_REWRITE = [
    (re.compile(r"^(passionate(ly)?\s+)?kiss(ing|es)?(\s+passionately)?$|^french kiss(ing)?$|^making out$", re.I),
     "incoming kiss"),
    (re.compile(r"^(hug|hugging|cuddl\w*|embrac\w*|holding each other)$", re.I), "hugging viewer"),
]


def _fix_interaction(scene):
    """Cảnh ôm / hôn mà không nói rõ hướng về người chơi → SDXL vẽ thêm một người nữ (hai cô gái ôm / hôn nhau).
    Viết lại từng tag tương tác thành hướng về người xem (incoming kiss, hugging viewer) và đảm bảo có POV.
    Có người nam trong cảnh (1boy...) thì để nguyên."""
    if not scene or _MALE.search(scene):
        return scene
    tags = [t.strip() for t in scene.split(",") if t.strip()]
    changed = False
    for i, t in enumerate(tags):
        for pat, new in _REWRITE:
            if pat.match(t):
                tags[i], changed = new, True
                break
    scene = ", ".join(dict.fromkeys(tags))  # bỏ tag trùng, giữ thứ tự
    if (changed or _TOUCH.search(scene)) and not re.search(r"\bpov\b", scene, re.I):
        scene = "pov, looking at viewer, " + scene
    if _TOUCH.search(scene) and not _PARTNER.search(scene):
        scene = "pov, hugging viewer, arms around viewer, looking at viewer, " + scene
    return scene


def build_prompts(character, scene):
    s = settings.get()
    age = max(int(character.get("age") or safety.MIN_AGE), safety.MIN_AGE)
    trigger = lora_trigger(character.get("lora_name"))
    look, older = _age_look(character.get("gender"), age)
    scene = _fix_interaction(scene or "")
    who = GENDER_TAGS.get(character.get("gender"), "solo, person")
    if _MALE.search(scene) and character.get("gender") == "Nữ":
        who = "1girl, woman"  # có người chơi (nam) trong khung: bỏ 'solo'
    parts = [
        trigger,
        s["quality_prefix"],
        who,
        f"{safety.HARD_POSITIVE}, {age} years old" + (f", {look}" if look else ""),
        character.get("appearance_tags") or "",
        scene or "",
    ]
    positive = ", ".join(p.strip(" ,") for p in parts if p and p.strip(" ,"))
    negative = ", ".join(p for p in (safety.HARD_NEGATIVE, older, SINGLE_NEGATIVE, s["negative_extra"]) if p)
    safety.check(positive, "Câu mô tả ảnh")
    safety.check_real_person(positive, "Câu mô tả ảnh")
    return positive, negative


def _spec_options(sp):
    if sp and isinstance(sp[0], list):
        return list(sp[0])
    if sp and sp[0] == "COMBO" and len(sp) > 1 and isinstance(sp[1], dict):
        return list(sp[1].get("options", []))
    return None


def _spec_default(sp):
    cfg = sp[1] if len(sp) > 1 and isinstance(sp[1], dict) else {}
    opts = _spec_options(sp)
    if opts is not None:
        return cfg.get("default", opts[0] if opts else None)
    return cfg.get("default")


def _detailer_inputs(spec, seed, s, model_src, clip_src):
    """Điền đầu vào FaceDetailer theo đúng danh sách ComfyUI báo (Impact Pack hay đổi tên/thêm ô giữa các bản)."""
    links = {"image": ["8", 0], "model": [model_src, 0], "clip": [clip_src, 1], "vae": ["4", 2],
             "positive": ["6", 0], "negative": ["7", 0], "bbox_detector": ["30", 0]}
    want = {"seed": seed, "steps": 20, "cfg": s["cfg"], "sampler_name": s["sampler"], "scheduler": s["scheduler"],
            "denoise": float(s["face_detail_denoise"]), "guide_size": 768, "guide_size_for": True, "max_size": 1024,
            "feather": 5, "noise_mask": True, "force_inpaint": True, "bbox_threshold": 0.5, "bbox_dilation": 10,
            "bbox_crop_factor": 3.0, "drop_size": 10, "wildcard": "", "cycle": 1}
    out = {}
    for name, sp in spec.items():
        if name in links:
            out[name] = links[name]
            continue
        val = want.get(name, _spec_default(sp))
        opts = _spec_options(sp)
        if opts is not None and val not in opts:  # vd. scheduler không có trong danh sách của node
            val = _spec_default(sp)
        if val is None:
            raise ImageError(f"FaceDetailer cần đầu vào '{name}' mà app chưa biết — tắt Sửa mặt trong Cài đặt")
        out[name] = val
    return out


def build_workflow(positive, negative, seed, lora_name="", lora_strength=0.8, face_image="", detailer=None):
    s = settings.get()
    if not s["checkpoint"]:
        raise ImageError("Chưa chọn checkpoint SDXL trong Cài đặt")
    model_src, clip_src = "4", "4"
    wf = {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": s["checkpoint"]}},
        "5": {"class_type": "EmptyLatentImage",
              "inputs": {"width": s["width"], "height": s["height"], "batch_size": 1}},
    }
    if lora_name:
        wf["10"] = {"class_type": "LoraLoader", "inputs": {
            "lora_name": lora_name, "strength_model": lora_strength, "strength_clip": lora_strength,
            "model": ["4", 0], "clip": ["4", 1]}}
        model_src, clip_src = "10", "10"
    faces = [face_image] if isinstance(face_image, str) and face_image else list(face_image or [])
    if faces:  # PuLID SDXL: khoá khuôn mặt theo ảnh mặt mẫu; nhiều ảnh gộp một lô → PuLID lấy trung bình khuôn mặt
        wf.update({
            "20": {"class_type": "PulidModelLoader", "inputs": {"pulid_file": s["pulid_file"]}},
            "21": {"class_type": "PulidEvaClipLoader", "inputs": {}},
            "22": {"class_type": "PulidInsightFaceLoader", "inputs": {"provider": "CPU"}},
        })
        img = None
        for i, name in enumerate(faces):
            wf[f"4{i}"] = {"class_type": "LoadImage", "inputs": {"image": name}}
            if img is None:
                img = [f"4{i}", 0]
            else:  # ImageBatch tự co ảnh sau về cỡ ảnh đầu
                wf[f"6{i}"] = {"class_type": "ImageBatch", "inputs": {"image1": img, "image2": [f"4{i}", 0]}}
                img = [f"6{i}", 0]
        wf["24"] = {"class_type": "ApplyPulid", "inputs": {
            "model": [model_src, 0], "pulid": ["20", 0], "eva_clip": ["21", 0], "face_analysis": ["22", 0],
            "image": img, "method": "fidelity", "weight": float(s["pulid_weight"]),
            "start_at": 0.0, "end_at": 1.0}}
        model_src = "24"
    wf.update({
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": [clip_src, 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": [clip_src, 1]}},
        "3": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": s["steps"], "cfg": s["cfg"], "sampler_name": s["sampler"],
            "scheduler": s["scheduler"], "denoise": 1.0, "model": [model_src, 0],
            "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "waifuai", "images": ["8", 0]}},
    })
    if detailer:  # sửa mặt: dò mặt rồi vẽ lại riêng vùng mặt ở độ phân giải cao (qua cùng LoRA / PuLID)
        spec, det_model = detailer
        wf["30"] = {"class_type": "UltralyticsDetectorProvider", "inputs": {"model_name": det_model}}
        wf["31"] = {"class_type": "FaceDetailer", "inputs": _detailer_inputs(spec, seed, settings.get(), model_src, clip_src)}
        wf["9"]["inputs"]["images"] = ["31", 0]
    return wf


async def detailer_spec():
    """(đầu vào FaceDetailer, mô hình dò mặt) nếu ComfyUI đã cài Impact Pack + Subpack + face_yolov8m; không thì None."""
    fd = await _object_info("FaceDetailer")
    det = await _object_info("UltralyticsDetectorProvider")
    if not fd or not det:
        return None
    faces = [m for m in _combo(det, "model_name") if "face" in m.lower()]
    if not faces:
        return None
    return fd, next((m for m in faces if "yolov8m" in m), faces[0])


async def ensure_checkpoint():
    """Chưa chọn checkpoint thì tự lấy cái đầu tiên ComfyUI đang có (cho lần chạy đầu sau khi cài)."""
    opts = await options()
    if opts and opts.get("checkpoints"):
        db.save_setting("checkpoint", opts["checkpoints"][0])


last_face = ""  # ảnh mặt mẫu đã gửi kèm ở lần vẽ gần nhất (để ghi log); vẽ tuần tự dưới gpu_lock nên không tranh chấp


def face_source(character):
    """Danh sách ảnh làm mặt mẫu PuLID (rỗng = không có).
    1. Các ảnh mặt mẫu người dùng tải lên (face_ref) — CHỈ khi đã tích xác nhận ảnh do AI tạo / nhân vật hư cấu (face_ref_ok).
    2. Không có thì ảnh đại diện do chính app vẽ (avatar_source == "gen"). Ảnh đại diện nhập từ ngoài không bao giờ dùng."""
    if not character.get("face_lock"):
        return []
    if character.get("face_ref_ok"):
        refs = [db.IMAGES / Path(n).name for n in db.face_refs(character)]
        refs = [p for p in refs if p.is_file()]
        if refs:
            return refs
    if character.get("avatar_source") != "gen":
        return []
    p = db.IMAGES / (character.get("avatar_path") or "")
    return [p] if character.get("avatar_path") and p.is_file() else []


async def _pulid_ready():
    info = await _object_info("PulidModelLoader")
    if not info or not await _object_info("ApplyPulid"):
        return False
    return settings.get()["pulid_file"] in _combo(info, "pulid_file")


async def _upload_face(path):
    name = f"waifuai_face_{path.stem}{path.suffix}"
    r = await _client.post(settings.get()["comfy_url"] + "/upload/image",
                           files={"image": (name, path.read_bytes(), "image/png")}, data={"overwrite": "true"})
    r.raise_for_status()
    return r.json()["name"]


async def generate(character, scene, seed=None, use_face=True):
    """Vẽ một ảnh, lưu vào data/images, trả về tên file."""
    s = settings.get()
    if not s["checkpoint"]:
        await ensure_checkpoint()
        s = settings.get()
    base = s["comfy_url"]
    positive, negative = build_prompts(character, scene)
    if seed is None:
        seed = random.randint(1, 2**31 - 1)
    global last_face
    face_image, last_face = [], ""
    faces = face_source(character) if use_face else []
    if faces:  # đã có ảnh mặt mẫu thì BẮT BUỘC gửi kèm — thiếu PuLID thì báo lỗi chứ không vẽ ra mặt khác
        if not await _pulid_ready():
            raise ImageError(f"Không gửi được ảnh mặt mẫu: ComfyUI chưa có node PuLID_ComfyUI hoặc {s['pulid_file']} "
                             "(chạy tools\\cai_pulid_sdxl.bat)")
        face_image = [await _upload_face(p) for p in faces]
        last_face = ", ".join(p.name for p in faces)
    elif use_face and character.get("face_lock"):
        log.warning("Nhân vật %s bật giữ khuôn mặt nhưng chưa có ảnh mặt mẫu đã xác nhận — ảnh này vẽ không có mẫu",
                    character.get("name"))
    detailer = await detailer_spec() if s["face_detail"] else None
    if s["face_detail"] and not detailer:
        log.info("Bỏ qua sửa mặt: ComfyUI chưa có FaceDetailer (chạy tools\\cai_face_detailer.bat)")
    wf = build_workflow(positive, negative, seed, character.get("lora_name") or "",
                        float(character.get("lora_strength") or 0.8), face_image, detailer)
    try:
        r = await _client.post(base + "/prompt", json={"prompt": wf, "client_id": uuid.uuid4().hex})
    except httpx.HTTPError as e:
        raise ImageError(f"Không kết nối được ComfyUI ({base}): {e}") from e
    if r.status_code != 200:
        raise ImageError(f"ComfyUI từ chối workflow: {r.text[:300]}")
    prompt_id = r.json()["prompt_id"]

    info = None
    for _ in range(600):  # tối đa ~10 phút
        await asyncio.sleep(1)
        try:
            h = (await _client.get(f"{base}/history/{prompt_id}")).json()
        except (httpx.HTTPError, ValueError):
            continue
        if prompt_id in h:
            info = h[prompt_id]
            break
    if info is None:
        raise ImageError("ComfyUI vẽ quá lâu (quá 10 phút)")
    status = info.get("status", {})
    if status.get("status_str") == "error":
        raise ImageError("ComfyUI báo lỗi khi vẽ: " + str(status.get("messages", ""))[:300])
    imgs = info.get("outputs", {}).get("9", {}).get("images", [])
    if not imgs:
        raise ImageError("ComfyUI không trả ảnh")
    img = imgs[0]
    v = await _client.get(base + "/view", params={
        "filename": img["filename"], "subfolder": img.get("subfolder", ""), "type": img.get("type", "output")})
    v.raise_for_status()
    name = f"{character['id']}_{uuid.uuid4().hex[:12]}.png"
    (db.IMAGES / name).write_bytes(v.content)
    return name


async def free_vram():
    try:
        await _client.post(settings.get()["comfy_url"] + "/free",
                           json={"unload_models": True, "free_memory": True}, timeout=15)
    except httpx.HTTPError:
        pass


async def _object_info(node):
    try:
        r = await _client.get(f"{settings.get()['comfy_url']}/object_info/{node}", timeout=5)
        r.raise_for_status()
        return r.json()[node]["input"]["required"]
    except (httpx.HTTPError, ValueError, KeyError):
        return None


def _combo(d, key):
    """Các lựa chọn của một ô COMBO trong /object_info."""
    v = d.get(key)
    if not v:
        return []
    if isinstance(v[0], list):  # kiểu cũ: [[...các lựa chọn], {...}]
        return list(v[0])
    if v[0] == "COMBO" and len(v) > 1 and isinstance(v[1], dict):  # kiểu mới
        return list(v[1].get("options", []))
    return []


async def options():
    """Danh sách checkpoint / LoRA / sampler / scheduler mà ComfyUI đang có. None nếu không kết nối được."""
    ck = await _object_info("CheckpointLoaderSimple")
    if ck is None:
        return None
    lora = await _object_info("LoraLoader") or {}
    ks = await _object_info("KSampler") or {}
    return {
        "checkpoints": _combo(ck, "ckpt_name"),
        "loras": _combo(lora, "lora_name"),
        "samplers": _combo(ks, "sampler_name"),
        "schedulers": _combo(ks, "scheduler"),
        "pulid": await _pulid_ready(),
        "face_detail": bool(await detailer_spec()),
    }
