"""LoRA từ 1 ảnh · bước 4: vẽ ảnh đánh giá cho các bản LoRA (bản cuối + bản lưu giữa chừng) qua ComfyUI.
Mỗi bản vẽ cùng các cảnh, cùng seed để so công bằng. Mặc định vẽ ĐÚNG như app: luôn gửi kèm ảnh mặt mẫu (PuLID,
lấy ảnh mặt mẫu đã xác nhận + độ mạnh PuLID / sửa mặt trong data/waifu.db) và có bước sửa mặt.
--tron: chỉ LoRA, không ảnh mẫu, không sửa mặt (đo riêng bản thân LoRA).
Chấm điểm bằng cham_danh_gia.py (python_embeded của ComfyUI).

  python danh_gia.py --ten nu_chinh_v3 [--canh 3] [--manh 1.0] [--pulid <ảnh trong dataset/ hoặc đường dẫn>] [--tron]

Ảnh ra: D:/AI/learn/waifu_<ten>/eval/<tên bản>/NN.png. Bản LoRA được chép tạm vào loras/_eval rồi xoá khi xong."""
import argparse
import json
import shutil
import sqlite3
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
COMFY_INPUT = Path("E:/ComfyUI_windows_portable/ComfyUI/input")
APP_DB = Path(__file__).resolve().parents[2] / "data" / "waifu.db"
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


def workflow(lora, strength, trigger, scene, seed, quality=QUALITY, neg=NEG):
    pos = f"{trigger}, {quality}, 1girl, solo, woman, adult, 23 years old, young adult woman, east asian, long black hair, {scene}"
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
        "10": {"class_type": "LoraLoader", "inputs": {"lora_name": lora, "strength_model": strength,
                                                       "strength_clip": strength, "model": ["4", 0], "clip": ["4", 1]}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 832, "height": 1216, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": pos, "clip": ["10", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": neg, "clip": ["10", 1]}},
        "3": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": 30, "cfg": 5.0, "sampler_name": "dpmpp_2m_sde",
                                                   "scheduler": "karras", "denoise": 1.0, "model": ["10", 0],
                                                   "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "waifu_eval", "images": ["8", 0]}},
    }


def _opts(sp):
    if sp and isinstance(sp[0], list):
        return sp[0]
    if sp and sp[0] == "COMBO" and len(sp) > 1 and isinstance(sp[1], dict):
        return sp[1].get("options", [])
    return None


def add_face_detailer(wf, seed, denoise):
    """Thêm bước sửa mặt giống hệt app (server/images.py): dò mặt face_yolov8m rồi vẽ lại vùng mặt qua cùng LoRA."""
    spec = api("/object_info/FaceDetailer")["FaceDetailer"]["input"]["required"]
    det = api("/object_info/UltralyticsDetectorProvider")["UltralyticsDetectorProvider"]["input"]["required"]
    faces = [m for m in (_opts(det["model_name"]) or []) if "face" in m.lower()]
    if not faces:
        raise SystemExit("ComfyUI chưa có mô hình dò mặt (chạy tools/cai_face_detailer.bat)")
    links = {"image": ["8", 0], "model": ["10", 0], "clip": ["10", 1], "vae": ["4", 2],
             "positive": ["6", 0], "negative": ["7", 0], "bbox_detector": ["30", 0]}
    want = {"seed": seed, "steps": 20, "cfg": 5.0, "sampler_name": "dpmpp_2m_sde", "scheduler": "karras", "denoise": denoise,
            "guide_size": 768, "guide_size_for": True, "max_size": 1024, "feather": 5, "noise_mask": True,
            "force_inpaint": True, "bbox_threshold": 0.5, "bbox_dilation": 10, "bbox_crop_factor": 3.0, "drop_size": 10,
            "wildcard": "", "cycle": 1}
    inp = {}
    for name, sp in spec.items():
        if name in links:
            inp[name] = links[name]
            continue
        cfg = sp[1] if len(sp) > 1 and isinstance(sp[1], dict) else {}
        o = _opts(sp)
        dflt = cfg.get("default", o[0] if o else None)
        v = want.get(name, dflt)
        inp[name] = dflt if (o is not None and v not in o) else v
    wf["30"] = {"class_type": "UltralyticsDetectorProvider",
                "inputs": {"model_name": next((m for m in faces if "yolov8m" in m), faces[0])}}
    wf["31"] = {"class_type": "FaceDetailer", "inputs": inp}
    wf["9"]["inputs"]["images"] = ["31", 0]
    return wf


def add_hires(wf, seed, scale, denoise, extra=""):
    """Vẽ phóng to lần 2: giải mã → phóng ảnh (lanczos) → mã hoá → KSampler vẽ lại nhẹ bằng LoRA KHÔNG kèm PuLID
    (PuLID làm mịn da; hình mặt đã được khoá ở lần 1). Gọi sau add_pulid / add_face_detailer."""
    pos = wf["6"]["inputs"]["text"] + (", " + extra if extra else "")
    wf.update({
        "50": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "51": {"class_type": "ImageScaleBy", "inputs": {"image": ["50", 0], "upscale_method": "lanczos", "scale_by": scale}},
        "52": {"class_type": "VAEEncode", "inputs": {"pixels": ["51", 0], "vae": ["4", 2]}},
        "53": {"class_type": "CLIPTextEncode", "inputs": {"text": pos, "clip": ["10", 1]}},
        "54": {"class_type": "KSampler", "inputs": {"seed": seed + 1, "steps": 25, "cfg": 5.0, "sampler_name": "dpmpp_2m_sde",
                                                    "scheduler": "karras", "denoise": denoise, "model": ["10", 0],
                                                    "positive": ["53", 0], "negative": ["7", 0], "latent_image": ["52", 0]}},
    })
    wf["8"]["inputs"]["samples"] = ["54", 0]
    return wf


def add_lora2(wf, name, strength, trigger=""):
    """Gắn LoRA phụ (vd. chi tiết da) ngay sau LoRA nhân vật: mọi node đang lấy model/clip từ "10" chuyển sang "11".
    Gọi SAU CÙNG (sau pulid / sửa mặt / phóng to) để không sót node nào."""
    for nid, node in wf.items():
        for k, v in node["inputs"].items():
            if isinstance(v, list) and len(v) == 2 and v[0] == "10":
                node["inputs"][k] = ["11", v[1]]
    wf["11"] = {"class_type": "LoraLoader", "inputs": {"lora_name": name, "strength_model": strength,
                                                       "strength_clip": strength, "model": ["10", 0], "clip": ["10", 1]}}
    if trigger:
        for nid in ("6", "32", "53"):
            if nid in wf:
                wf[nid]["inputs"]["text"] = trigger + ", " + wf[nid]["inputs"]["text"]
    return wf


def add_pulid(wf, face_input_names, weight=1.0, end_at=1.0, method="fidelity"):
    """Khoá mặt bằng PuLID SDXL (như app khi có ảnh mặt mẫu): chen giữa LoRA và KSampler / FaceDetailer.
    Nhiều ảnh mẫu thì gộp thành một lô (ImageBatch) — PuLID lấy trung bình đặc trưng mặt của cả lô."""
    if isinstance(face_input_names, str):
        face_input_names = [face_input_names]
    wf.update({
        "20": {"class_type": "PulidModelLoader", "inputs": {"pulid_file": "ip-adapter_pulid_sdxl_fp16.safetensors"}},
        "21": {"class_type": "PulidEvaClipLoader", "inputs": {}},
        "22": {"class_type": "PulidInsightFaceLoader", "inputs": {"provider": "CPU"}},
    })
    img = None
    for i, name in enumerate(face_input_names):
        wf[f"4{i}"] = {"class_type": "LoadImage", "inputs": {"image": name}}
        if img is None:
            img = [f"4{i}", 0]
        else:
            wf[f"6{i}"] = {"class_type": "ImageBatch", "inputs": {"image1": img, "image2": [f"4{i}", 0]}}
            img = [f"6{i}", 0]
    wf["24"] = {"class_type": "ApplyPulid", "inputs": {"model": ["10", 0], "pulid": ["20", 0], "eva_clip": ["21", 0],
                                                       "face_analysis": ["22", 0], "image": img, "method": method,
                                                       "weight": weight, "start_at": 0.0, "end_at": end_at}}
    wf["3"]["inputs"]["model"] = ["24", 0]
    if "31" in wf:
        wf["31"]["inputs"]["model"] = ["24", 0]
    return wf


def app_config(trigger, cid=0):
    """Ảnh mặt mẫu đã xác nhận + độ mạnh PuLID / sửa mặt mà app đang dùng (đọc thẳng data/waifu.db, chỉ đọc)."""
    cfg = {"face": "", "weight": 1.0, "denoise": 0.5}
    if not APP_DB.is_file():
        return cfg
    con = sqlite3.connect(f"file:{APP_DB.as_posix()}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT id, lora_name, face_ref, face_ref_ok FROM characters").fetchall()
        hit = [r for r in rows if (r[0] == cid if cid else Path(r[1] or "").stem == trigger)]
        if hit and hit[0][2] and hit[0][3]:  # face_ref: nhiều tên file cách nhau dấu phẩy
            ps = [APP_DB.parent / "images" / Path(n.strip()).name for n in hit[0][2].split(",") if n.strip()]
            cfg["face"] = ",".join(str(p) for p in ps if p.is_file())
        st = dict(con.execute("SELECT key, value FROM settings WHERE key IN ('pulid_weight', 'face_detail_denoise')"))
        cfg["weight"] = float(json.loads(st.get("pulid_weight", "1.0")))
        cfg["denoise"] = float(json.loads(st.get("face_detail_denoise", "0.5")))
    finally:
        con.close()
    return cfg


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
    ap.add_argument("--tron", action="store_true", help="chỉ LoRA: không gửi ảnh mặt mẫu, không sửa mặt")
    ap.add_argument("--chi", default="", help="chỉ đánh giá bản có tên chứa chuỗi này")
    ap.add_argument("--canh_chon", type=int, default=0, help="chỉ vẽ cảnh số này (1-5), dùng với --hat")
    ap.add_argument("--hat", default="", help="các hạt giống cho --canh_chon, cách nhau dấu phẩy")
    ap.add_argument("--pulid", default="", help="ảnh mặt mẫu (tên trong dataset/ hoặc đường dẫn); mặc định ảnh mẫu của app")
    ap.add_argument("--w", type=float, default=0, help="độ mạnh PuLID thử (mặc định lấy của app)")
    ap.add_argument("--end", type=float, default=1.0, help="PuLID ngừng tác dụng ở tỉ lệ bước này (vd. 0.8 để mấy bước cuối vẽ chi tiết da)")
    ap.add_argument("--sm", type=float, default=0, help="độ vẽ lại vùng mặt thử (mặc định lấy của app)")
    ap.add_argument("--chat", default="", help="thay câu chất lượng ảnh (mặc định như app)")
    ap.add_argument("--am", default="", help="thêm vào phần cấm vẽ")
    ap.add_argument("--bo_am", default="", help="bỏ các từ này khỏi phần cấm vẽ (cách nhau dấu phẩy)")
    ap.add_argument("--nhan", default="", help="nhãn gắn vào tên thư mục kết quả")
    ap.add_argument("--khong_sua", action="store_true", help="bỏ bước sửa mặt (vẫn gửi ảnh mẫu)")
    ap.add_argument("--cach", default="fidelity", choices=["fidelity", "style", "neutral"], help="kiểu PuLID")
    ap.add_argument("--hires", type=float, default=0, help="vẽ phóng to lần 2 (vd. 1.5) bằng LoRA không PuLID để tạo kết cấu da")
    ap.add_argument("--hires_dn", type=float, default=0.4, help="độ vẽ lại của lần phóng to")
    ap.add_argument("--lora2", default="", help="LoRA phụ gắn sau LoRA nhân vật (tên file không đuôi, vd. ultra_realistic_face_skin_e10)")
    ap.add_argument("--lora2_manh", type=float, default=0.6)
    ap.add_argument("--lora2_tu", default="", help="từ kích hoạt của LoRA phụ, đặt đầu câu lệnh (vd. ufs9)")
    ap.add_argument("--lora2_chi_sua", action="store_true",
                    help="LoRA phụ CHỈ ở bước sửa mặt (gắn vào lần vẽ chính thì LoRA da kéo dáng mặt ở cảnh cận)")
    ap.add_argument("--sua_pulid", type=float, default=0, help="độ mạnh PuLID riêng cho bước sửa mặt có chuỗi LoRA riêng (0 = không)")
    ap.add_argument("--sua_manh", type=float, default=0, help="độ mạnh LoRA nhân vật RIÊNG cho bước sửa mặt (vd. 0.6, da bớt mịn)")
    ap.add_argument("--sua_tron", action="store_true", help="bước sửa mặt dùng LoRA không kèm PuLID (PuLID làm da mịn)")
    ap.add_argument("--sua_chat", default="", help="thêm vào câu lệnh của riêng bước sửa mặt (vd. nhấn kết cấu da)")
    ap.add_argument("--nv", type=int, default=0, help="id nhân vật trong app để lấy ảnh mặt mẫu (mặc định: nhân vật dùng LoRA này)")
    a = ap.parse_args()
    goc = LEARN / f"waifu_{a.ten}"
    trigger = f"wf_{a.ten}"
    app = app_config(trigger, a.nv)
    if a.w:
        app["weight"] = a.w
    if a.sm:
        app["denoise"] = a.sm
    quality = a.chat or QUALITY
    bo = {x.strip() for x in a.bo_am.split(",") if x.strip()}
    neg = ", ".join([x for x in NEG.split(", ") if x not in bo] + ([a.am] if a.am else []))
    a.sua_mat = not (a.tron or a.khong_sua)
    if a.tron:
        a.pulid = ""
    elif not a.pulid:
        if not app["face"]:
            raise SystemExit("Nhân vật chưa có ảnh mặt mẫu đã xác nhận trong app — bắt buộc phải có (tab Ảnh) hoặc truyền --pulid")
        a.pulid = app["face"]
    refs = [Path(x.strip()) if Path(x.strip()).is_absolute() else goc / "dataset" / x.strip()
            for x in a.pulid.split(",") if x.strip()]
    for r in refs:
        if not r.is_file():
            raise SystemExit(f"Không thấy ảnh mặt mẫu: {r}")
    tag = "_".join(r.stem.replace("mat_", "") for r in refs) if len(refs) > 1 else (refs[0].stem if refs else "")
    print(f"Ảnh mặt mẫu: {', '.join(r.name for r in refs) or 'KHÔNG (--tron)'} · PuLID {app['weight']:g} · "
          f"sửa mặt {format(app['denoise'], 'g') if a.sua_mat else 'tắt'}", flush=True)
    ban = [b for b in sorted((goc / "output").glob(f"{trigger}*.safetensors")) if a.chi in b.stem]
    if not ban:
        raise SystemExit("Chưa có bản LoRA nào trong output/")
    tmp = LORA_DIR / "_eval"
    tmp.mkdir(parents=True, exist_ok=True)
    scenes = SCENES[:max(1, min(a.canh, len(SCENES)))]
    if a.canh_chon:  # một cảnh, nhiều hạt giống — xem lỗi là của cả loại cảnh hay chỉ một bố cục
        txt = SCENES[a.canh_chon - 1][0]
        scenes = [(txt, int(s)) for s in (a.hat.split(",") if a.hat else [SCENES[a.canh_chon - 1][1]])]
    print(f"Đánh giá {len(ban)} bản × {len(scenes)} cảnh = {len(ban) * len(scenes)} ảnh", flush=True)
    t0 = time.time()
    pulid_names = []
    for r in refs:
        pulid_names.append(f"waifu_eval_mau_{r.name}")
        shutil.copyfile(r, COMFY_INPUT / pulid_names[-1])
    try:
        for b in ban:
            shutil.copyfile(b, tmp / b.name)
        time.sleep(2)
        lora2 = ""
        if a.lora2:
            lora2 = lora_name_in_comfy(a.lora2)
            if not lora2:
                raise SystemExit(f"ComfyUI chưa thấy LoRA phụ {a.lora2} (chạy tools\\tai_lora_da.bat)")
        for b in ban:
            name = lora_name_in_comfy(b.stem)
            if not name:
                raise SystemExit(f"ComfyUI chưa thấy {b.name} trong loras/_eval")
            out = goc / "eval" / (b.stem + (f"@{a.manh:g}" if a.manh != 1.0 else "") + ("+suamat" if a.sua_mat else "")
                                  + (f"+pulid_{tag}" if refs else "") + (f"_w{app['weight']:g}" if refs and a.w else "")
                                  + (f"+{a.nhan}" if a.nhan else ""))
            out.mkdir(parents=True, exist_ok=True)
            for i, (scene, seed) in enumerate(scenes):
                dst = out / f"{i:02d}.png"
                if not dst.exists():
                    wf = workflow(name, a.manh, trigger, scene, seed, quality, neg)
                    if a.sua_mat:
                        wf = add_face_detailer(wf, seed, app["denoise"])
                    if refs:
                        wf = add_pulid(wf, pulid_names, app["weight"], a.end, a.cach)
                    if a.hires > 1:
                        wf = add_hires(wf, seed, a.hires, a.hires_dn, a.sua_chat)
                    if a.sua_mat and a.sua_tron:  # PuLID làm mịn da → bước sửa mặt chỉ dùng LoRA để vẽ lại kết cấu da
                        wf["31"]["inputs"]["model"] = ["10", 0]
                    if a.sua_mat and a.sua_chat:
                        wf["32"] = {"class_type": "CLIPTextEncode",
                                    "inputs": {"text": wf["6"]["inputs"]["text"] + ", " + a.sua_chat, "clip": ["10", 1]}}
                        wf["31"]["inputs"]["positive"] = ["32", 0]
                    if lora2 and not a.lora2_chi_sua:
                        wf = add_lora2(wf, lora2, a.lora2_manh, a.lora2_tu)
                    if a.sua_mat and (a.sua_manh or (lora2 and a.lora2_chi_sua)):
                        if a.lora2_chi_sua and a.lora2_tu and "32" in wf:
                            wf["32"]["inputs"]["text"] = a.lora2_tu + ", " + wf["32"]["inputs"]["text"]
                        # bước sửa mặt có chuỗi LoRA riêng: LoRA nhân vật yếu (da bớt mịn) + LoRA phụ, không PuLID
                        sm = a.sua_manh or a.manh
                        wf["12"] = {"class_type": "LoraLoader", "inputs": {"lora_name": name, "strength_model": sm,
                                                                           "strength_clip": sm, "model": ["4", 0], "clip": ["4", 1]}}
                        last = "12"
                        if lora2:
                            wf["13"] = {"class_type": "LoraLoader", "inputs": {"lora_name": lora2, "strength_model": a.lora2_manh,
                                                                               "strength_clip": a.lora2_manh, "model": ["12", 0], "clip": ["12", 1]}}
                            last = "13"
                        if a.sua_pulid and "24" in wf:
                            # khoá mặt cả ở bước sửa mặt (mặt nhỏ trong khung bị phóng to rồi vẽ lại → không khoá thì lệch)
                            wf["25"] = {"class_type": "ApplyPulid",
                                        "inputs": {**wf["24"]["inputs"], "model": [last, 0], "weight": a.sua_pulid, "end_at": 1.0}}
                            wf["31"]["inputs"]["model"] = ["25", 0]
                        else:
                            wf["31"]["inputs"]["model"] = [last, 0]
                        wf["31"]["inputs"]["clip"] = [last, 1]
                        if "32" in wf:
                            wf["32"]["inputs"]["clip"] = [last, 1]
                    render(wf, dst)
                print(f"  {b.stem} · cảnh {i + 1}/{len(scenes)} · {time.time() - t0:.0f} giây", flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        for n in pulid_names:
            (COMFY_INPUT / n).unlink(missing_ok=True)
    print(f"Xong → {goc / 'eval'}")


if __name__ == "__main__":
    main()
