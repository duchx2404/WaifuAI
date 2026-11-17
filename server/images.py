"""Gọi ComfyUI (SDXL) để vẽ ảnh nhân vật."""
import asyncio
import random
import uuid

import httpx

from . import db, safety, settings

_client = httpx.AsyncClient(timeout=httpx.Timeout(120, connect=10))


class ImageError(RuntimeError):
    pass


GENDER_TAGS = {"Nữ": "1girl, solo, woman", "Nam": "1boy, solo, man"}


def build_prompts(character, scene):
    s = settings.get()
    age = max(int(character.get("age") or safety.MIN_AGE), safety.MIN_AGE)
    parts = [
        s["quality_prefix"],
        GENDER_TAGS.get(character.get("gender"), "solo, person"),
        f"{safety.HARD_POSITIVE}, {age} years old",
        character.get("appearance_tags") or "",
        scene or "",
    ]
    positive = ", ".join(p.strip(" ,") for p in parts if p and p.strip(" ,"))
    negative = ", ".join(p for p in (safety.HARD_NEGATIVE, s["negative_extra"]) if p)
    safety.check(positive, "Câu mô tả ảnh")
    return positive, negative


def build_workflow(positive, negative, seed, lora_name="", lora_strength=0.8):
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
    return wf


async def generate(character, scene, seed=None):
    """Vẽ một ảnh, lưu vào data/images, trả về tên file."""
    s = settings.get()
    base = s["comfy_url"]
    positive, negative = build_prompts(character, scene)
    if seed is None:
        seed = random.randint(1, 2**31 - 1)
    wf = build_workflow(positive, negative, seed, character.get("lora_name") or "",
                        float(character.get("lora_strength") or 0.8))
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


async def options():
    """Danh sách checkpoint / LoRA / sampler / scheduler mà ComfyUI đang có. None nếu không kết nối được."""
    ck = await _object_info("CheckpointLoaderSimple")
    if ck is None:
        return None
    lora = await _object_info("LoraLoader") or {}
    ks = await _object_info("KSampler") or {}

    def first(d, key):
        v = d.get(key)
        if not v:
            return []
        if isinstance(v[0], list):  # kiểu cũ: [[...các lựa chọn], {...}]
            return list(v[0])
        if v[0] == "COMBO" and len(v) > 1 and isinstance(v[1], dict):  # kiểu mới
            return list(v[1].get("options", []))
        return []

    return {
        "checkpoints": first(ck, "ckpt_name"),
        "loras": first(lora, "lora_name"),
        "samplers": first(ks, "sampler_name"),
        "schedulers": first(ks, "scheduler"),
    }
