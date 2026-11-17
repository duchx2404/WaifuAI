"""LoRA từ 1 ảnh · bước 5: chấm ảnh đánh giá — độ giống mặt (insightface) so với khuôn mặt chung của dataset.
Chạy bằng python_embeded của ComfyUI:

  E:/ComfyUI_windows_portable/python_embeded/python.exe -I cham_danh_gia.py --ten nu_chinh_v3

In điểm từng bản; bản cao nhất ghi vào eval/ket_qua.json."""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from insightface.app import FaceAnalysis

sys.stdout.reconfigure(encoding="utf-8")
ap = argparse.ArgumentParser()
ap.add_argument("--ten", required=True)
ap.add_argument("--nguong", type=float, default=0.60, help="đạt khi điểm TRUNG BÌNH các ảnh của một bản ≥ ngưỡng")
a = ap.parse_args()
goc = Path("D:/AI/learn") / f"waifu_{a.ten}"

fa = FaceAnalysis(name="antelopev2", root="E:/ComfyUI_windows_portable/ComfyUI/models/insightface",
                  providers=["CPUExecutionProvider"])
fa.prepare(ctx_id=-1, det_size=(640, 640))


def emb(p):
    img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
    faces = fa.get(img)
    if not faces:
        return None
    return max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])).normed_embedding


ds = [e for p in sorted((goc / "dataset").iterdir()) if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
      and p.suffix.lower() != ".jpg" for e in [emb(p)] if e is not None]  # bỏ ảnh gốc cách điệu (.jpg)
center = np.mean(ds, axis=0)
center /= np.linalg.norm(center)
self_sim = float(np.mean([e @ center for e in ds]))
print(f"Dataset: {len(ds)} mặt · tự so với khuôn mặt chung {self_sim:.2f}")
res = {}
for d in sorted((goc / "eval").iterdir()):
    if not d.is_dir():
        continue
    sc = []
    for p in sorted(d.glob("*.png")):
        e = emb(p)
        sc.append(float(e @ center) if e is not None else 0.0)
    if sc:
        res[d.name] = {"mean": round(float(np.mean(sc)), 3), "min": round(min(sc), 3), "scores": [round(s, 2) for s in sc]}
        print(f"{d.name:40} TB {np.mean(sc):.2f} · thấp nhất {min(sc):.2f} · {[round(s, 2) for s in sc]}")
best = max(res, key=lambda k: res[k]["mean"]) if res else None
dat = bool(best) and res[best]["mean"] >= a.nguong
out = {"dataset_self": round(self_sim, 3), "nguong": a.nguong, "ban": res, "tot_nhat": best, "dat": dat}
(goc / "eval" / "ket_qua.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Tốt nhất: {best} · TB {res.get(best, {}).get('mean')} · ngưỡng {a.nguong} → {'ĐẠT' if dat else 'CHƯA ĐẠT'}")
