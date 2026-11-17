"""Cài đặt hệ thống: giá trị mặc định + phần người dùng sửa trong giao diện Quản lý (lưu ở bảng settings)."""
from . import db

DEFAULTS = {
    # Kết nối
    "ollama_url": "http://127.0.0.1:11434",
    "comfy_url": "http://127.0.0.1:8188",
    # Mô hình chữ
    "model_chat": "gemma3:12b",
    "model_explicit": "mistral-nemo:12b",
    "disable_thinking": True,
    "keep_alive": "10m",
    "temperature": 0.9,
    "context_messages": 30,
    # 12 GB VRAM: nhả mô hình chữ trước khi vẽ, nhả mô hình ảnh sau khi vẽ
    "vram_swap": True,
    # Mô hình ảnh (SDXL qua ComfyUI)
    "image_enabled": True,
    "checkpoint": "",
    "quality_prefix": "masterpiece, best quality, highly detailed",
    "negative_extra": "lowres, bad anatomy, bad hands, extra fingers, missing fingers, blurry, watermark, text, signature",
    "steps": 28,
    "cfg": 6.0,
    "sampler": "dpmpp_2m",
    "scheduler": "karras",
    "width": 832,
    "height": 1216,
    # Chủ động nhắn
    "proactive_enabled": True,
    "quiet_start": "23:30",
    "quiet_end": "07:00",
}


def get():
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in db.load_settings().items() if k in DEFAULTS})
    return merged


def update(data):
    for key, default in DEFAULTS.items():
        if key not in data:
            continue
        val = data[key]
        if isinstance(default, bool):
            val = bool(val)
        elif isinstance(default, int):
            val = int(float(val))
        elif isinstance(default, float):
            val = float(val)
        else:
            val = str(val or "").strip()
            if key.endswith("_url"):
                val = val.rstrip("/")
        db.save_setting(key, val)
    return get()
