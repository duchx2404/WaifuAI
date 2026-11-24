"""LoRA từ 1 ảnh · thêm ảnh CẬN MẶT vào dataset: dò mặt bằng insightface, cắt vuông quanh mặt, phóng lên 1024.
Ảnh nửa người / toàn thân thì mặt chỉ vài trăm pixel — LoRA học bối cảnh nhiều hơn học mặt; ảnh cận mặt bù vào.
Chạy bằng python_embeded của ComfyUI:

  E:/ComfyUI_windows_portable/python_embeded/python.exe -I cat_mat.py --nguon <dataset cũ> --dich <dataset mới> --tu_khoa wf_x

Chép cả ảnh gốc + caption (đổi từ khoá) và thêm mat_NNN.png + caption 'close-up face portrait'."""
import argparse
import re
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
from insightface.app import FaceAnalysis

sys.stdout.reconfigure(encoding="utf-8")
ap = argparse.ArgumentParser()
ap.add_argument("--nguon", required=True)
ap.add_argument("--dich", required=True)
ap.add_argument("--tu_khoa", required=True)
ap.add_argument("--khung", type=float, default=2.0, help="cạnh khung cắt = khung × cạnh lớn của mặt")
a = ap.parse_args()
src, dst = Path(a.nguon), Path(a.dich)
if dst.exists():
    shutil.rmtree(dst)
dst.mkdir(parents=True)

fa = FaceAnalysis(name="antelopev2", root="E:/ComfyUI_windows_portable/ComfyUI/models/insightface",
                  providers=["CPUExecutionProvider"])
fa.prepare(ctx_id=-1, det_size=(640, 640))
EXPR = ["pouting", "smiling", "smile", "duck face", "blush", "looking at viewer", "eyes closed", "wet hair", "hair bun", "half updo"]
n_full = n_crop = 0
for p in sorted(src.iterdir()):
    if p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        continue
    cap_p = p.with_suffix(".txt")
    cap = cap_p.read_text(encoding="utf-8") if cap_p.exists() else f"{a.tu_khoa}, a woman, photo"
    cap = re.sub(r"\bwf_[a-z0-9_]+", a.tu_khoa, cap, count=1)
    shutil.copyfile(p, dst / p.name)
    (dst / p.with_suffix(".txt").name).write_text(cap, encoding="utf-8")
    n_full += 1
    if p.suffix.lower() == ".jpg":  # ảnh gốc cách điệu: không cắt thêm
        continue
    img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
    faces = fa.get(img)
    if not faces:
        print(f"  {p.name}: không thấy mặt, bỏ qua cắt")
        continue
    f = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    x1, y1, x2, y2 = f.bbox
    cx, cy, side = (x1 + x2) / 2, (y1 + y2) / 2, max(x2 - x1, y2 - y1) * a.khung
    h, w = img.shape[:2]
    side = min(side, w, h)
    x0 = int(min(max(cx - side / 2, 0), w - side))
    y0 = int(min(max(cy - side / 2, 0), h - side))
    crop = img[y0:y0 + int(side), x0:x0 + int(side)]
    crop = cv2.resize(crop, (1024, 1024), interpolation=cv2.INTER_LANCZOS4)
    name = f"mat_{p.stem}.png"
    cv2.imencode(".png", crop)[1].tofile(str(dst / name))
    extra = [e for e in EXPR if re.search(rf"\b{re.escape(e)}\b", cap)]
    (dst / f"mat_{p.stem}.txt").write_text(
        ", ".join([a.tu_khoa, "a woman", "close-up face portrait"] + extra + ["photo"]), encoding="utf-8")
    n_crop += 1
    print(f"  {p.name}: mặt {int(x2 - x1)}px → cắt {int(side)}px → 1024")
print(f"Xong: {n_full} ảnh gốc + {n_crop} ảnh cận mặt → {dst}")
