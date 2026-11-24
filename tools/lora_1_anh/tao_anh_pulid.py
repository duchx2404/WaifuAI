"""LoRA từ 1 ảnh · bổ sung dữ liệu: vẽ ảnh mới bằng PuLID SDXL (khoá mặt theo các ảnh mẫu trong dataset) trên LUSTIFY.
Ảnh ra để chấm bằng cham_bo_sung.py (chỉ giữ ảnh rất giống). Không dùng LoRA khi vẽ.

  python tao_anh_pulid.py --ten nu_chinh_v5 --mau mat_009.png,mat_010.png,mat_015.png --so 24

Ảnh ra: D:/AI/learn/waifu_<ten>/bo_sung/NN.png + NN.txt (caption có từ khoá wf_<ten>)."""
import argparse
import json
import random
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
COMFY_INPUT = Path("E:/ComfyUI_windows_portable/ComfyUI/input")
LEARN = Path("D:/AI/learn")
CKPT = "lustifySDXLNSFW_v20.safetensors"
QUALITY = "photo, high quality photography, sharp focus, soft lighting, natural smooth skin"
NEG = ("child, kid, loli, teen, teenager, young girl, petite, flat chest, school uniform, baby face, middle-aged, "
       "old woman, wrinkles, 2girls, multiple girls, twins, multiple faces, worst quality, low quality, lowres, anime, "
       "cartoon, illustration, drawing, painting, 3d render, cgi, deformed, bad anatomy, bad hands, blurry, watermark, text")
KHUNG = ["close-up face portrait", "close-up portrait", "head and shoulders portrait", "upper body"]
GOC = ["looking at viewer", "slight head tilt, looking at viewer", "three-quarter view", "looking to the side"]
BIEU_CAM = ["soft smile", "gentle smile", "smiling", "pouting", "neutral expression", "playful smile", "shy smile, blush"]
DO = ["white blouse", "black slip dress", "beige knit sweater", "white satin pajamas", "light blue shirt",
      "black off-shoulder top", "white t-shirt", "pink cardigan", "white camisole"]
CANH = ["cafe, soft daylight", "bedroom, warm lamp light", "living room, window light", "city street at dusk",
        "park, golden hour", "plain light grey background, studio lighting", "balcony, overcast daylight", "kitchen, morning light"]


def api(path, data=None):
    req = urllib.request.Request(COMFY + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Content-Type": "application/json"} if data is not None else {})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def workflow(face, scene, seed, weight):
    pos = f"{QUALITY}, 1girl, solo, woman, adult, 23 years old, young adult woman, east asian, long black hair, {scene}"
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
        "20": {"class_type": "PulidModelLoader", "inputs": {"pulid_file": "ip-adapter_pulid_sdxl_fp16.safetensors"}},
        "21": {"class_type": "PulidEvaClipLoader", "inputs": {}},
        "22": {"class_type": "PulidInsightFaceLoader", "inputs": {"provider": "CPU"}},
        "23": {"class_type": "LoadImage", "inputs": {"image": face}},
        "24": {"class_type": "ApplyPulid", "inputs": {"model": ["4", 0], "pulid": ["20", 0], "eva_clip": ["21", 0],
                                                      "face_analysis": ["22", 0], "image": ["23", 0], "method": "fidelity",
                                                      "weight": weight, "start_at": 0.0, "end_at": 1.0}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 896, "height": 1152, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": pos, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["4", 1]}},
        "3": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": 30, "cfg": 5.0, "sampler_name": "dpmpp_2m_sde",
                                                   "scheduler": "karras", "denoise": 1.0, "model": ["24", 0],
                                                   "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "waifu_bosung", "images": ["8", 0]}},
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
    ap.add_argument("--mau", required=True, help="các ảnh mặt mẫu trong dataset, cách nhau dấu phẩy")
    ap.add_argument("--so", type=int, default=24)
    ap.add_argument("--manh", type=float, default=1.0, help="độ mạnh PuLID")
    a = ap.parse_args()
    goc = LEARN / f"waifu_{a.ten}"
    out = goc / "bo_sung"
    out.mkdir(parents=True, exist_ok=True)
    faces = []
    for m in a.mau.split(","):
        src = goc / "dataset" / m.strip()
        name = f"waifu_mau_{a.ten}_{src.name}"
        shutil.copyfile(src, COMFY_INPUT / name)
        faces.append(name)
    rnd = random.Random(20261118)
    t0 = time.time()
    try:
        for i in range(a.so):
            dst = out / f"{i:03d}.png"
            khung, goc_nhin, bc, do, canh = (rnd.choice(KHUNG), rnd.choice(GOC), rnd.choice(BIEU_CAM), rnd.choice(DO), rnd.choice(CANH))
            scene = f"{khung}, {goc_nhin}, {bc}, {do}, {canh}"
            seed = rnd.randint(1, 2**31 - 1)
            if not dst.exists():
                render(workflow(faces[i % len(faces)], scene, seed, a.manh), dst)
            dst.with_suffix(".txt").write_text(f"wf_{a.ten}, a woman, {scene}, photo", encoding="utf-8")
            print(f"  [{i + 1}/{a.so}] {dst.name} · {time.time() - t0:.0f} giây", flush=True)
    finally:
        for f in faces:
            (COMFY_INPUT / f).unlink(missing_ok=True)
    print(f"Xong → {out}")


if __name__ == "__main__":
    main()
