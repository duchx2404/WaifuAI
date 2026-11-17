"""LoRA từ 1 ảnh · bước 4: vẽ ảnh đánh giá cho các bản LoRA (bản cuối + bản lưu giữa chừng) qua ComfyUI.
Mỗi bản vẽ cùng các cảnh, cùng seed để so công bằng. Chỉ dùng LoRA (không PuLID / sửa mặt) để đo đúng bản thân LoRA.
Chấm điểm bằng cham_danh_gia.py (python_embeded của ComfyUI).

  python danh_gia.py --ten nu_chinh_v3 [--canh 3] [--manh 1.0]

Ảnh ra: D:/AI/learn/waifu_<ten>/eval/<tên bản>/NN.png. Bản LoRA được chép tạm vào loras/_eval rồi xoá khi xong."""
import argparse
import json
import shutil
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")

COMFY = "http://127.0.0.1:8188"
LEARN = Path("D:/AI/learn")
LORA_DIR = Path("D:/AI/models/loras")
CKPT = "lustifySDXLNSFW_v20.safetensors"
QUALITY = "photo, high quality photography, sharp focus, soft lighting, natural smooth skin"
NEG = ("child, kid, loli, shota, underage, minor, teen, teenager, young girl, young boy, petite, flat chest, "
       "school uniform, chibi, baby face, middle-aged, milf, mature woman, old woman, wrinkles, aged skin, "
       "2girls, multiple girls, twins, clone, multiple faces, worst quality, low quality, lowres, anime, cartoon, "
       "illustration, drawing, painting, 3d render, cgi, deformed, bad anatomy, bad hands, blurry, watermark, text")
SCENES = [
    ("close-up portrait, looking at viewer, slight smile, white blouse, cafe, soft daylight", 1111),
    ("upper body, mirror selfie, holding smartphone, black slip dress, bedroom", 2222),
    ("sitting on sofa, cozy living room, white satin pajamas, looking at viewer, smile", 3333),
    ("upper body, standing on balcony, city view, beige knit sweater, looking at viewer", 4444),
    ("close-up, lying on bed, head on pillow, white camisole, looking at viewer, morning light", 5555),
]


def api(path, data=None):
    req = urllib.request.Request(COMFY + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Content-Type": "application/json"} if data is not None else {})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def lora_name_in_comfy(stem):
    opts = api("/object_info/LoraLoader")["LoraLoader"]["input"]["required"]["lora_name"][0]
    if isinstance(opts, str):  # kiểu COMBO mới
        opts = api("/object_info/LoraLoader")["LoraLoader"]["input"]["required"]["lora_name"][1]["options"]
    hit = [o for o in opts if Path(o.replace("\\", "/")).stem == stem]
    return hit[0] if hit else None


def workflow(lora, strength, trigger, scene, seed):
    pos = f"{trigger}, {QUALITY}, 1girl, solo, woman, adult, 23 years old, young adult woman, east asian, long black hair, {scene}"
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
        "10": {"class_type": "LoraLoader", "inputs": {"lora_name": lora, "strength_model": strength,
                                                       "strength_clip": strength, "model": ["4", 0], "clip": ["4", 1]}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 832, "height": 1216, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": pos, "clip": ["10", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["10", 1]}},
        "3": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": 30, "cfg": 5.0, "sampler_name": "dpmpp_2m_sde",
                                                   "scheduler": "karras", "denoise": 1.0, "model": ["10", 0],
                                                   "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "waifu_eval", "images": ["8", 0]}},
    }


def render(wf, dst):
    pid = api("/prompt", {"prompt": wf, "client_id": uuid.uuid4().hex})["prompt_id"]
    for _ in range(900):
        time.sleep(1)
        h = api(f"/history/{pid}")
        if pid in h:
            break
    else:
        raise SystemExit("ComfyUI vẽ quá lâu")
    info = h[pid]
    if info.get("status", {}).get("status_str") == "error":
        raise SystemExit("ComfyUI lỗi: " + str(info["status"].get("messages"))[:400])
    img = info["outputs"]["9"]["images"][0]
    q = urllib.parse.urlencode({"filename": img["filename"], "subfolder": img.get("subfolder", ""), "type": img.get("type", "output")})
    with urllib.request.urlopen(f"{COMFY}/view?{q}", timeout=60) as r:
        dst.write_bytes(r.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ten", required=True)
    ap.add_argument("--canh", type=int, default=3, help="số cảnh mỗi bản (tối đa 5)")
    ap.add_argument("--manh", type=float, default=1.0)
    a = ap.parse_args()
    goc = LEARN / f"waifu_{a.ten}"
    trigger = f"wf_{a.ten}"
    ban = sorted((goc / "output").glob(f"{trigger}*.safetensors"))
    if not ban:
        raise SystemExit("Chưa có bản LoRA nào trong output/")
    tmp = LORA_DIR / "_eval"
    tmp.mkdir(parents=True, exist_ok=True)
    scenes = SCENES[:max(1, min(a.canh, len(SCENES)))]
    print(f"Đánh giá {len(ban)} bản × {len(scenes)} cảnh = {len(ban) * len(scenes)} ảnh", flush=True)
    t0 = time.time()
    try:
        for b in ban:
            shutil.copyfile(b, tmp / b.name)
        time.sleep(2)
        for b in ban:
            name = lora_name_in_comfy(b.stem)
            if not name:
                raise SystemExit(f"ComfyUI chưa thấy {b.name} trong loras/_eval")
            out = goc / "eval" / b.stem
            out.mkdir(parents=True, exist_ok=True)
            for i, (scene, seed) in enumerate(scenes):
                dst = out / f"{i:02d}.png"
                if not dst.exists():
                    render(workflow(name, a.manh, trigger, scene, seed), dst)
                print(f"  {b.stem} · cảnh {i + 1}/{len(scenes)} · {time.time() - t0:.0f} giây", flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"Xong → {goc / 'eval'}")


if __name__ == "__main__":
    main()
