"""Cài đặt hệ thống: giá trị mặc định + phần người dùng sửa trong giao diện Quản lý (lưu ở bảng settings)."""
import json
from pathlib import Path

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
    # Chờ bao lâu (giây) kể từ tin nhắn CUỐI của người chơi rồi mới trả lời; nhắn thêm thì đếm lại từ đầu
    "reply_delay_seconds": 120,
    # 12 GB VRAM: nhả mô hình chữ trước khi vẽ, nhả mô hình ảnh sau khi vẽ
    "vram_swap": True,
    # Mô hình ảnh (SDXL qua ComfyUI) — mặc định theo khuyến nghị của LUSTIFY v2 (ảnh tả thực)
    "image_enabled": True,
    "checkpoint": "",
    # "smooth skin" / "soft lighting" làm mặt bóng như nhựa → tả ảnh chụp thật có kết cấu da. Ảnh mặt mẫu (PuLID) +
    # phần cấm vẽ tuổi giữ nhân vật trẻ (đã thử 2026-11-19: giống 0.65, không bị già)
    "quality_prefix": "raw photo, candid smartphone photo, photorealistic, realistic skin texture, visible skin pores, "
                      "natural skin, slight film grain, natural lighting",
    "negative_extra": "worst quality, low quality, lowres, anime, cartoon, illustration, drawing, painting, 3d render, cgi, deformed, bad anatomy, bad hands, extra fingers, missing fingers, blurry, watermark, text, signature, "
                      "plastic skin, airbrushed, smooth skin, waxy skin, doll, porcelain skin, beauty filter, overly smooth skin, glossy skin, cgi face",
    "steps": 30,
    "cfg": 5.0,
    "sampler": "dpmpp_2m_sde",
    "scheduler": "karras",
    "width": 832,
    "height": 1216,
    # Giữ khuôn mặt theo ảnh đại diện (PuLID SDXL, cần node PuLID_ComfyUI — xem cai_pulid_sdxl.bat)
    "pulid_file": "ip-adapter_pulid_sdxl_fp16.safetensors",
    "pulid_weight": 0.8,
    # Sửa mặt sau khi vẽ (FaceDetailer của Impact Pack — xem tools\cai_face_detailer.bat); chưa cài thì tự bỏ qua
    "face_detail": True,
    "face_detail_denoise": 0.3,  # cao hơn (0.5) vẽ lại mặt mịn như sáp
    # Chủ động nhắn
    "proactive_enabled": True,
    "quiet_start": "23:30",
    "quiet_end": "07:00",
}

# Bộ cài ghi mô hình chữ đã có sẵn trên máy vào config.json -> dùng làm mặc định
# (người dùng sửa trong Quản lý → Cài đặt thì giá trị trong DB vẫn được ưu tiên).
_CONFIG = Path(__file__).resolve().parent.parent / "config.json"
try:
    _cfg = json.loads(_CONFIG.read_text(encoding="utf-8"))
except (OSError, ValueError):
    _cfg = {}
for _k in ("model_chat", "model_explicit"):
    if isinstance(_cfg.get(_k), str):
        DEFAULTS[_k] = _cfg[_k].strip()


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
