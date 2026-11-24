"""LoRA từ 1 ảnh · chấm ảnh bổ sung (bo_sung/) so với khuôn mặt chung của dataset; ảnh ≥ ngưỡng chép vào dataset/ (bs_NNN).
Chạy bằng python_embeded của ComfyUI:

  E:/ComfyUI_windows_portable/python_embeded/python.exe -I cham_bo_sung.py --ten nu_chinh_v5 [--nguong 0.62]"""
import argparse
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
from insightface.app import FaceAnalysis

sys.stdout.reconfigure(encoding="utf-8")
ap = argparse.ArgumentParser()
ap.add_argument("--ten", required=True)
ap.add_argument("--nguong", type=float, default=0.62)
a = ap.parse_args()
goc = Path("D:/AI/learn") / f"waifu_{a.ten}"
fa = FaceAnalysis(name="antelopev2", root="E:/ComfyUI_windows_portable/ComfyUI/models/insightface",
                  providers=["CPUExecutionProvider"])
fa.prepare(ctx_id=-1, det_size=(640, 640))


def emb(p):
    img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
    faces = fa.get(img)
    if len(faces) != 1:  # bỏ ảnh không thấy mặt hoặc có hơn một người
        return None
    return faces[0].normed_embedding


ds = [emb(p) for p in sorted((goc / "dataset").glob("*.png")) if not p.name.startswith("bs_")]
ds = [e for e in ds if e is not None]
center = np.mean(ds, axis=0)
center /= np.linalg.norm(center)
keep = 0
for p in sorted((goc / "bo_sung").glob("*.png")):
    e = emb(p)
    s = float(e @ center) if e is not None else 0.0
    ok = s >= a.nguong
    print(f"  {p.name}: {s:.2f} {'→ GIỮ' if ok else ''}")
    if ok:
        dst = goc / "dataset" / f"bs_{p.stem}.png"
        shutil.copyfile(p, dst)
        shutil.copyfile(p.with_suffix(".txt"), dst.with_suffix(".txt"))
        keep += 1
print(f"Giữ {keep} ảnh (≥ {a.nguong}) → dataset/")
