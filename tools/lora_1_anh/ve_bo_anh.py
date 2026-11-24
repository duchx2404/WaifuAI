"""LoRA từ 1 ảnh · bước 1: từ MỘT ảnh mặt, dùng Flux dev + PuLID-Flux (ComfyUI) vẽ ra cả bộ ảnh
cùng một người: nhiều góc mặt, biểu cảm, trang phục, bối cảnh, ánh sáng — kèm chú thích để huấn luyện.

  python ve_bo_anh.py --ten nu_chinh --anh "D:/AI/character assets/.../face.png" [--so 32] [--tuoi 25]

Kết quả: D:/AI/learn/waifu_<ten>/gen/NNN.png + NNN.txt. Chạy lại thì bỏ qua ảnh đã có (vẽ tiếp chỗ dở).
Chỉ dùng cho nhân vật hư cấu (ảnh AI vẽ). Không dùng ảnh chụp người thật."""
import argparse
import json
import random
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")

COMFY = "http://127.0.0.1:8188"
COMFY_DIR = Path("E:/ComfyUI_windows_portable/ComfyUI")
LEARN = Path("D:/AI/learn")

FLUX = {"unet": "flux1-dev-Q6_K.gguf", "t5": "t5-v1_1-xxl-encoder-Q5_K_M.gguf", "clip_l": "clip_l.safetensors",
        "vae": "ae.safetensors", "pulid": "pulid_flux_v0.9.1.safetensors", "steps": 24, "guidance": 3.0,
        "lora": ("FLUX.1-dev-LoRA-add-details.safetensors", 0.6)}
# Thông số PuLID theo cỡ khung (đã chỉnh trong AIFilm): khung rộng thì PuLID chỉ tác động vùng đầu
KHUNG = {
    "mat": {"cau": "close-up portrait of her face and shoulders", "wh": (832, 1216), "weight": 0.9, "start": 0.1, "top": 1.0},
    "nua": {"cau": "medium shot from the waist up", "wh": (832, 1216), "weight": 0.8, "start": 0.3, "top": 0.45},
    "toan": {"cau": "full body shot, standing, whole figure visible", "wh": (832, 1216), "weight": 0.75, "start": 0.35, "top": 0.28},
}
GOC = ["facing the camera", "three-quarter view, head turned to her left", "three-quarter view, head turned to her right",
       "side profile view facing left", "side profile view facing right", "looking up slightly, seen from a low angle",
       "looking down slightly, seen from a high angle"]
BIEU_CAM = ["calm neutral expression", "gentle closed-mouth smile", "bright laughing smile showing teeth", "shy smile with a light blush",
            "serious focused expression", "surprised expression with raised eyebrows", "pensive dreamy expression", "playful wink"]
TOC = ["black hair in a loose updo with soft strands framing her face", "long straight black hair worn down",
       "black hair in a high ponytail", "long wavy black hair over one shoulder"]
DO = ["a white silk hanfu with delicate gold embroidery", "a cream knit sweater", "an elegant black evening dress",
      "a light blue summer sundress", "a white blouse and a grey blazer", "a red silk qipao", "a plain white t-shirt and jeans",
      "pink silk pajamas", "a denim jacket over a white top", "a lavender off-shoulder top", "a black turtleneck", "a beige trench coat"]
CANH = ["plain light grey studio backdrop", "a cherry blossom garden", "a cozy cafe interior", "a city street at night with neon bokeh",
        "a bedroom with warm lamp light", "a beach at golden hour", "a library with wooden bookshelves", "a traditional Chinese courtyard",
        "a sunlit living room", "a rooftop at sunset"]
ANH_SANG = ["soft natural window light", "warm golden hour sunlight", "soft diffused studio lighting", "cinematic low key lighting",
            "bright overcast daylight"]


BIEU_CAM_NHE = ["calm neutral expression", "gentle closed-mouth smile", "shy smile with a light blush", "pensive dreamy expression"]


def ke_hoach(so, seed, nghieng=False):
    """Danh sách ảnh cần vẽ: ~45% cận mặt, ~35% nửa người, ~20% toàn thân; góc/biểu cảm xoay vòng cho đủ.
    nghieng=True: chỉ góc nghiêng (bỏ nhìn thẳng), nửa cận mặt nửa nửa người, biểu cảm nhẹ; 1/3 ảnh nửa người là selfie gương
    — bổ sung cho LoRA giữ mặt kém khi quay 3/4."""
    r = random.Random(seed)
    if nghieng:
        goc_ds, bc_ds = GOC[1:], BIEU_CAM_NHE
        loai = ["mat"] * (so // 2) + ["nua"] * (so - so // 2)
    else:
        goc_ds, bc_ds = GOC, BIEU_CAM
        n_mat, n_nua = round(so * 0.45), round(so * 0.35)
        loai = ["mat"] * n_mat + ["nua"] * n_nua + ["toan"] * (so - n_mat - n_nua)
    ds = []
    for i, k in enumerate(loai):
        m = {"khung": k, "goc": goc_ds[i % len(goc_ds)], "bieu_cam": bc_ds[(i * 3) % len(bc_ds)],
             "toc": TOC[r.randrange(len(TOC))], "do": DO[r.randrange(len(DO))], "canh": CANH[r.randrange(len(CANH))],
             "anh_sang": ANH_SANG[r.randrange(len(ANH_SANG))], "seed": r.randrange(1, 2**31 - 1)}
        if nghieng and k == "nua" and i % 3 == 0:
            m["hanh_dong"] = "taking a mirror selfie with a smartphone"
            m["canh"] = "a bright bathroom with a large mirror"
        ds.append(m)
    return ds


def _hd(m):
    return f"{m['hanh_dong']}, " if m.get("hanh_dong") else ""


def cau_lenh(m, tuoi):
    return (f"RAW photo, realistic photograph of a beautiful {tuoi}-year-old adult Chinese woman, {KHUNG[m['khung']]['cau']}, "
            f"{_hd(m)}{m['goc']}, {m['bieu_cam']}, {m['toc']}, wearing {m['do']}, in {m['canh']}, {m['anh_sang']}, "
            "natural skin texture, sharp focus, shot on Canon EOS 5D, 85mm lens, high detail")


def chu_thich(m, trigger):
    return (f"{trigger}, a woman, {KHUNG[m['khung']]['cau']}, {_hd(m)}{m['goc']}, {m['bieu_cam']}, {m['toc']}, "
            f"wearing {m['do']}, in {m['canh']}, {m['anh_sang']}, photo")


def workflow(prompt, m, anh_mau):
    k = KHUNG[m["khung"]]
    w, h = k["wh"]
    lora, lora_w = FLUX["lora"]
    wf = {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": FLUX["unet"]}},
        "2": {"class_type": "DualCLIPLoaderGGUF", "inputs": {"clip_name1": FLUX["t5"], "clip_name2": FLUX["clip_l"], "type": "flux"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": FLUX["vae"]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": ""}},
        "15": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["4", 0], "guidance": FLUX["guidance"]}},
        "5": {"class_type": "EmptySD3LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "30": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": lora, "strength_model": lora_w}},
        "40": {"class_type": "PulidFluxModelLoader", "inputs": {"pulid_file": FLUX["pulid"]}},
        "41": {"class_type": "PulidFluxInsightFaceLoader", "inputs": {"provider": "CPU"}},
        "42": {"class_type": "PulidFluxEvaClipLoader", "inputs": {}},
        "60": {"class_type": "LoadImage", "inputs": {"image": anh_mau}},
        "6": {"class_type": "KSampler", "inputs": {"model": ["44", 0], "positive": ["15", 0], "negative": ["7", 0], "latent_image": ["5", 0],
                                                  "seed": m["seed"], "steps": FLUX["steps"], "cfg": 1.0, "sampler_name": "euler",
                                                  "scheduler": "simple", "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "waifu_lora/gen"}},
    }
    pulid = {"model": ["30", 0], "pulid_flux": ["40", 0], "eva_clip": ["42", 0], "face_analysis": ["41", 0], "image": ["60", 0],
             "weight": k["weight"], "start_at": k["start"], "end_at": 1.0, "fusion": "mean", "fusion_weight_max": 1.0,
             "fusion_weight_min": 0.0, "train_step": 1000, "use_gray": True}
    if k["top"] < 1.0:
        wf["45"] = {"class_type": "SolidMask", "inputs": {"value": 0.0, "width": w, "height": h}}
        wf["46"] = {"class_type": "SolidMask", "inputs": {"value": 1.0, "width": w, "height": int(h * k["top"])}}
        wf["47"] = {"class_type": "MaskComposite", "inputs": {"destination": ["45", 0], "source": ["46", 0], "x": 0, "y": 0, "operation": "add"}}
        pulid["attn_mask"] = ["47", 0]
    wf["44"] = {"class_type": "ApplyPulidFlux", "inputs": pulid}
    return wf


def goi(path, data=None, timeout=30):
    req = urllib.request.Request(COMFY + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Content-Type": "application/json"} if data is not None else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


CHO_XOA = []


def don_dep(lan=3):
    """Xoá các ảnh tạm trong output của ComfyUI; file đang bị khoá thì để lần sau."""
    for _ in range(lan):
        for p in list(CHO_XOA):
            try:
                p.unlink(missing_ok=True)
                CHO_XOA.remove(p)
            except PermissionError:
                pass
        if not CHO_XOA:
            return
        time.sleep(2)


def ve_mot(wf):
    try:
        pid = json.loads(goi("/prompt", {"prompt": wf, "client_id": uuid.uuid4().hex}))["prompt_id"]
    except urllib.error.HTTPError as e:
        raise SystemExit("ComfyUI từ chối workflow: " + e.read().decode("utf-8", "replace")[:600])
    for _ in range(1800):
        time.sleep(1)
        h = json.loads(goi(f"/history/{pid}"))
        if pid in h:
            info = h[pid]
            if info.get("status", {}).get("status_str") == "error":
                raise SystemExit("ComfyUI lỗi khi vẽ: " + json.dumps(info["status"].get("messages", ""), ensure_ascii=False)[:600])
            img = info["outputs"]["9"]["images"][0]
            q = urllib.parse.urlencode({"filename": img["filename"], "subfolder": img.get("subfolder", ""), "type": "output"})
            data = goi(f"/view?{q}", timeout=60)
            # bản trong output của ComfyUI phải xoá (ảnh chỉ nằm ở thư mục học — xoá là xoá hết);
            # bộ quét asset của ComfyUI hay giữ file vài giây → thử lại, không được thì dọn ở cuối
            CHO_XOA.append(COMFY_DIR / "output" / img.get("subfolder", "") / img["filename"])
            don_dep(lan=3)
            return data
    raise SystemExit("ComfyUI vẽ quá 30 phút một ảnh")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ten", required=True, help="tên ngắn không dấu, vd nu_chinh")
    ap.add_argument("--anh", required=True, help="ảnh mặt mẫu (ảnh AI vẽ của nhân vật hư cấu)")
    ap.add_argument("--so", type=int, default=32)
    ap.add_argument("--tuoi", type=int, default=25)
    ap.add_argument("--seed", type=int, default=20261117)
    ap.add_argument("--nghieng", action="store_true", help="chỉ vẽ góc nghiêng / selfie gương (bổ sung bộ đã có)")
    a = ap.parse_args()
    if a.tuoi < 21:
        raise SystemExit("Nhân vật phải từ 21 tuổi.")

    goc = LEARN / f"waifu_{a.ten}"
    gen = goc / "gen"
    gen.mkdir(parents=True, exist_ok=True)
    anh = Path(a.anh)
    mau = goc / ("mau" + anh.suffix.lower())
    if not mau.exists():
        shutil.copyfile(anh, mau)
    trigger = f"wf_{a.ten}"
    ds = ke_hoach(a.so, a.seed, a.nghieng)
    (goc / "ke_hoach.json").write_text(json.dumps({"trigger": trigger, "tuoi": a.tuoi, "anh_mau": str(anh), "ds": ds},
                                                  ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        goi("/system_stats", timeout=5)
    except OSError:
        raise SystemExit("ComfyUI chưa chạy ở " + COMFY)
    ten_input = f"waifu_lora_{a.ten}{mau.suffix}"
    shutil.copyfile(mau, COMFY_DIR / "input" / ten_input)

    con = [i for i in range(len(ds)) if not (gen / f"{i:03d}.png").exists()]
    print(f"Vẽ {len(con)}/{len(ds)} ảnh cho '{a.ten}' (từ khoá {trigger}) → {gen}", flush=True)
    t0 = time.time()
    for n, i in enumerate(con, 1):
        m = ds[i]
        t = time.time()
        data = ve_mot(workflow(cau_lenh(m, a.tuoi), m, ten_input))
        (gen / f"{i:03d}.png").write_bytes(data)
        (gen / f"{i:03d}.txt").write_text(chu_thich(m, trigger), encoding="utf-8")
        tb = (time.time() - t0) / n
        print(f"[{n}/{len(con)}] {i:03d}.png ({m['khung']}) {time.time() - t:.0f} giây · còn ~{tb * (len(con) - n) / 60:.0f} phút", flush=True)
    (COMFY_DIR / "input" / ten_input).unlink(missing_ok=True)
    CHO_XOA.extend((COMFY_DIR / "output" / "waifu_lora").glob("gen_*.png"))  # sót từ lần chạy bị ngắt
    don_dep(lan=10)
    if CHO_XOA:
        print("Chưa xoá được (đang bị khoá): " + ", ".join(str(p) for p in CHO_XOA))
    print(f"Xong {len(con)} ảnh sau {(time.time() - t0) / 60:.0f} phút.")


if __name__ == "__main__":
    main()
