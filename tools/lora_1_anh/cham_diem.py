"""LoRA từ 1 ảnh · bước 2: chấm độ giống mặt (insightface antelopev2, chạy CPU) của từng ảnh đã vẽ so với ảnh mẫu,
chọn những ảnh giống nhất vào bộ dữ liệu huấn luyện, và ghép một bảng xem nhanh có ghi điểm.

  E:/ComfyUI_windows_portable/python_embeded/python.exe -I cham_diem.py --ten nu_chinh [--nguong 0.45] [--toi_da 28]

Kết quả: D:/AI/learn/waifu_<ten>/dataset/ (ảnh + .txt), diem.json, bang_xem.jpg.
Muốn bỏ ảnh nào thì xoá ảnh đó trong dataset/ trước khi huấn luyện."""
import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from insightface.app import FaceAnalysis
from PIL import Image, ImageDraw, ImageFont

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")

LEARN = Path("D:/AI/learn")
INSIGHT_ROOT = "E:/ComfyUI_windows_portable/ComfyUI/models/insightface"


def mat_lon_nhat(fa, path):
    img = np.array(Image.open(path).convert("RGB"))[:, :, ::-1]  # RGB → BGR cho insightface
    faces = fa.get(img)
    if not faces:
        return None
    f = max(faces, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]))
    return f.normed_embedding


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ten", required=True)
    ap.add_argument("--nguong", type=float, default=0.45, help="độ giống tối thiểu (cosine, 0–1)")
    ap.add_argument("--toi_da", type=int, default=28)
    a = ap.parse_args()
    goc = LEARN / f"waifu_{a.ten}"
    gen, ds = goc / "gen", goc / "dataset"
    mau = next(goc.glob("mau.*"))

    fa = FaceAnalysis(name="antelopev2", root=INSIGHT_ROOT, providers=["CPUExecutionProvider"])
    fa.prepare(ctx_id=-1, det_size=(640, 640))
    ref = mat_lon_nhat(fa, mau)
    if ref is None:
        raise SystemExit(f"Không thấy khuôn mặt trong ảnh mẫu {mau}")

    diem = {}
    for p in sorted(gen.glob("*.png")):
        e = mat_lon_nhat(fa, p)
        diem[p.name] = None if e is None else round(float(np.dot(ref, e)), 3)
        print(f"{p.name}: {'không thấy mặt' if e is None else diem[p.name]}", flush=True)
    (goc / "diem.json").write_text(json.dumps(diem, indent=1), encoding="utf-8")

    xep = sorted(((d, n) for n, d in diem.items() if d is not None and d >= a.nguong), reverse=True)[: a.toi_da]
    chon = {n for _, n in xep}
    if ds.exists():
        shutil.rmtree(ds)
    ds.mkdir(parents=True)
    for n in chon:
        shutil.copyfile(gen / n, ds / n)
        shutil.copyfile(gen / n.replace(".png", ".txt"), ds / n.replace(".png", ".txt"))

    # bảng xem nhanh: ảnh mẫu đầu tiên, rồi mọi ảnh đã vẽ; viền xanh = được chọn, đỏ = bỏ
    tw, th = 208, 304
    items = [(mau, "MẪU", (80, 140, 255))] + [
        (gen / n, f"{n[:3]}  {'—' if d is None else f'{d:.2f}'}", (60, 190, 90) if n in chon else (220, 70, 70))
        for n, d in diem.items()]
    cols = 8
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * th), (24, 24, 28))
    dr = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    for i, (p, nhan, mau_vien) in enumerate(items):
        x, y = (i % cols) * tw, (i // cols) * th
        im = Image.open(p).convert("RGB")
        im.thumbnail((tw - 8, th - 34))
        sheet.paste(im, (x + 4 + (tw - 8 - im.width) // 2, y + 4))
        dr.rectangle([x + 1, y + 1, x + tw - 2, y + th - 2], outline=mau_vien, width=3)
        dr.text((x + 8, y + th - 28), nhan, fill=(235, 235, 235), font=font)
    sheet.save(goc / "bang_xem.jpg", quality=88)

    co = [d for d in diem.values() if d is not None]
    print(f"\nĐã chấm {len(diem)} ảnh · thấy mặt {len(co)} · trung bình {sum(co) / max(len(co), 1):.2f} · "
          f"chọn {len(chon)} ảnh (ngưỡng {a.nguong}) → {ds}")
    print(f"Bảng xem: {goc / 'bang_xem.jpg'}")


if __name__ == "__main__":
    main()
