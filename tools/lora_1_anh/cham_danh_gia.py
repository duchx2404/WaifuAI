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
ap.add_argument("--goc", default="", help="chấm giống so với MỘT ảnh này (vd. mau.png = ảnh gốc nhân vật) thay vì khuôn mặt chung dataset")
a = ap.parse_args()
goc = Path("D:/AI/learn") / f"waifu_{a.ten}"

fa = FaceAnalysis(name="antelopev2", root="E:/ComfyUI_windows_portable/ComfyUI/models/insightface",
                  providers=["CPUExecutionProvider"])
fa.prepare(ctx_id=-1, det_size=(640, 640))


def _da(img, f):
    """Độ chi tiết da: phương sai Laplacian của vùng giữa mặt (bỏ viền tóc), chuẩn hoá về 256 px.
    Da 'nhựa' / mịn quá → thấp."""
    x0, y0, x1, y1 = [int(v) for v in f.bbox]
    w, hh = x1 - x0, y1 - y0
    x0, x1 = max(0, x0 + w // 5), min(img.shape[1], x1 - w // 5)
    y0, y1 = max(0, y0 + hh // 4), min(img.shape[0], y1 - hh // 6)
    if x1 - x0 < 16 or y1 - y0 < 16:
        return 0.0
    g = cv2.cvtColor(cv2.resize(img[y0:y1, x0:x1], (256, 256), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


DA = {}


def emb(p):
    img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
    faces = fa.get(img)
    if not faces:
        return None
    f = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    DA[str(p)] = _da(img, f)
    return f.normed_embedding


ds_files = [p for p in sorted((goc / "dataset").iterdir()) if p.suffix.lower() in (".png", ".webp")]  # bỏ ảnh gốc cách điệu (.jpg)
ds = [e for p in ds_files for e in [emb(p)] if e is not None]
da_ds = float(np.median([DA[str(p)] for p in ds_files if p.name.startswith("mat_") and str(p) in DA] or [0]))
if a.goc:
    gp = Path(a.goc) if Path(a.goc).is_absolute() else goc / a.goc
    center = emb(gp)
    if center is None:
        raise SystemExit(f"Không thấy mặt trong {gp}")
    muc_tieu = f"ảnh gốc {gp.name}"
else:
    center = np.mean(ds, axis=0)
    center /= np.linalg.norm(center)
    muc_tieu = "khuôn mặt chung dataset"
self_sim = float(np.mean([e @ center for e in ds]))
print(f"Chấm theo {muc_tieu} · dataset {len(ds)} mặt, tự so {self_sim:.2f} · chi tiết da ảnh cận mặt dataset {da_ds:.0f}")
res = {}
for d in sorted((goc / "eval").iterdir()):
    if not d.is_dir():
        continue
    sc, da = [], []
    for p in sorted(d.glob("*.png")):
        e = emb(p)
        sc.append(float(e @ center) if e is not None else 0.0)
        da.append(DA.get(str(p), 0.0))
    if sc:
        res[d.name] = {"mean": round(float(np.mean(sc)), 3), "min": round(min(sc), 3), "scores": [round(s, 2) for s in sc],
                       "da": round(float(np.mean(da)), 1)}
        print(f"{d.name:60} TB {np.mean(sc):.2f} · thấp nhất {min(sc):.2f} · {[round(s, 2) for s in sc]} · da {np.mean(da):.0f}")
# xét đạt theo đúng quy trình app: LoRA + ảnh mặt mẫu (PuLID) + sửa mặt; chưa có bản nào như vậy thì theo LoRA trơn
app = {k: v for k, v in res.items() if "+pulid_" in k and "+suamat" in k}
tron = {k: v for k, v in res.items() if "+" not in k}
xet = app or tron
best = max(xet, key=lambda k: xet[k]["mean"]) if xet else None
dat = bool(best) and res[best]["mean"] >= a.nguong
if app and tron:
    b2 = max(tron, key=lambda k: tron[k]["mean"])
    print(f"Tham khảo — LoRA trơn (không ảnh mẫu) tốt nhất: {b2} · TB {tron[b2]['mean']}")
out = {"muc_tieu": muc_tieu, "dataset_self": round(self_sim, 3), "dataset_da": round(da_ds, 1), "nguong": a.nguong, "ban": res, "tot_nhat": best, "dat": dat}
(goc / "eval" / "ket_qua.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Tốt nhất: {best} · TB {res.get(best, {}).get('mean')} · ngưỡng {a.nguong} → {'ĐẠT' if dat else 'CHƯA ĐẠT'}")
