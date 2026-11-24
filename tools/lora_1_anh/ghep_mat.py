"""LoRA từ 1 ảnh · xem bằng mắt: cắt khuôn mặt ảnh gốc + mọi ảnh đánh giá, mỗi thư mục eval một hàng (GỐC | cảnh 1 | 2 | 3).
Điểm insightface không bắt được dáng mặt → luôn xem bảng này cạnh ảnh gốc. Chạy bằng python_embeded của ComfyUI:

  E:/ComfyUI_windows_portable/python_embeded/python.exe -I ghep_mat.py --ten nu_chinh_v7 [--goc mau.png]

Ra: D:/AI/learn/waifu_<ten>/eval/bang_mat.jpg"""
import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
from insightface.app import FaceAnalysis

sys.stdout.reconfigure(encoding="utf-8")
ap = argparse.ArgumentParser()
ap.add_argument("--ten", required=True)
ap.add_argument("--goc", default="mau.png")
ap.add_argument("--loc", default="", help="chỉ ghép thư mục eval có tên chứa chuỗi này")
a = ap.parse_args()
root = Path("D:/AI/learn") / f"waifu_{a.ten}"
fa = FaceAnalysis(name="antelopev2", root="E:/ComfyUI_windows_portable/ComfyUI/models/insightface",
                  providers=["CPUExecutionProvider"])
fa.prepare(ctx_id=-1, det_size=(640, 640))
S = 300


def cell(p, label):
    img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
    fs = fa.get(img)
    if fs:
        f = max(fs, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        x0, y0, x1, y1 = f.bbox
        cx, cy, r = (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, y1 - y0) * 0.75
        img = img[max(0, int(cy - r)):int(cy + r), max(0, int(cx - r)):int(cx + r)]
    img = cv2.resize(img, (S, S), interpolation=cv2.INTER_CUBIC)
    lab = np.full((22, S, 3), 255, np.uint8)
    cv2.putText(lab, label[-36:], (2, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 1, cv2.LINE_AA)
    return np.vstack([img, lab])


goc = cell(root / a.goc, "GOC")
rows = []
for d in sorted((root / "eval").iterdir()):
    if not d.is_dir() or a.loc not in d.name:
        continue
    rows.append([goc] + [cell(p, d.name[-26:] + "/" + p.stem) for p in sorted(d.glob("*.png"))])
cot = max(len(r) for r in rows)
rows = [np.hstack(r + [np.full_like(goc, 255)] * (cot - len(r))) for r in rows]
out = root / "eval" / (f"bang_mat_{a.loc}.jpg" if a.loc else "bang_mat.jpg")
cv2.imencode(".jpg", np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 88])[1].tofile(str(out))
print(out, len(rows), "hàng")
