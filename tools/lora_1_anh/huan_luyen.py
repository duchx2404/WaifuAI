"""LoRA từ 1 ảnh · bước 3: huấn luyện LoRA SDXL (kohya sd-scripts) trên checkpoint đang dùng (LUSTIFY) từ dataset/.
Tự tắt ComfyUI + dừng model Ollama để nhường VRAM. SDXL nằm gọn trong 12 GB nên không cần hoán đổi khối như Flux.

  D:/AI/venv/kohya/Scripts/python.exe -I huan_luyen.py --ten nu_chinh [--buoc 1500] [--rank 32]

Kết quả: D:/AI/models/loras/wf_<ten>.safetensors — trong WaifuAI chọn LoRA này cho nhân vật;
từ khoá kích hoạt (wf_<ten>) app tự chèn vào câu mô tả ảnh."""
import argparse
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")

LEARN = Path("D:/AI/learn")
SD_SCRIPTS = Path("D:/AI/sd-scripts")
CKPT = Path("D:/AI/models/checkpoints/lustifySDXLNSFW_v20.safetensors")
LORA_DIR = Path("D:/AI/models/loras")
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def nhuong_vram():
    out = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        p = line.split()
        if len(p) >= 5 and p[1].endswith(":8188") and p[3].upper() == "LISTENING":
            subprocess.run(["taskkill", "/PID", p[4], "/T", "/F"], capture_output=True)
            print("đã tắt ComfyUI để nhường VRAM", flush=True)
    try:
        for line in subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=15).stdout.splitlines()[1:]:
            if line.split():
                subprocess.run(["ollama", "stop", line.split()[0]], capture_output=True, timeout=30)
                print(f"đã dừng Ollama {line.split()[0]}", flush=True)
    except (OSError, subprocess.SubprocessError):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ten", required=True)
    ap.add_argument("--buoc", type=int, default=1500)
    ap.add_argument("--rank", type=int, default=32)
    ap.add_argument("--alpha", type=int, default=0, help="mặc định rank/2; đặt bằng rank để học mạnh hơn (giữ mặt tốt hơn)")
    ap.add_argument("--min_snr", type=float, default=0, help="min-SNR gamma (vd. 5) — học chi tiết ổn định hơn; 0 = tắt")
    ap.add_argument("--ckpt", default=str(CKPT))
    a = ap.parse_args()
    goc = LEARN / f"waifu_{a.ten}"
    ds, out = goc / "dataset", goc / "output"
    n = sum(1 for p in ds.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")) if ds.exists() else 0
    if n < 8:
        raise SystemExit(f"dataset/ mới có {n} ảnh — cần ít nhất 8 (chạy cham_diem.py trước).")
    ten_lora = f"wf_{a.ten}"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    toml = out / "dataset.toml"
    toml.write_text(f"""[general]
caption_extension = ".txt"
shuffle_caption = false
keep_tokens = 1

[[datasets]]
resolution = 1024
batch_size = 1
enable_bucket = true
min_bucket_reso = 640
max_bucket_reso = 1536

  [[datasets.subsets]]
  image_dir = '{ds.as_posix()}'
  num_repeats = 10
""", encoding="utf-8")

    py = Path(sys.executable)
    cmd = [str(py), "-u", str(SD_SCRIPTS / "sdxl_train_network.py"),
           f"--pretrained_model_name_or_path={a.ckpt}", f"--dataset_config={toml}",
           f"--output_dir={out}", f"--output_name={ten_lora}", "--save_model_as=safetensors",
           "--network_module=networks.lora", f"--network_dim={a.rank}", f"--network_alpha={a.alpha or a.rank // 2}",
           "--network_train_unet_only", "--learning_rate=1e-4", "--optimizer_type=AdamW8bit",
           "--lr_scheduler=cosine", "--lr_warmup_steps=60", f"--max_train_steps={a.buoc}",
           "--mixed_precision=bf16", "--save_precision=fp16", "--gradient_checkpointing", "--sdpa", "--no_half_vae",
           "--cache_latents", "--cache_latents_to_disk", "--cache_text_encoder_outputs",
           "--max_data_loader_n_workers=0", "--seed=42", f"--save_every_n_steps={max(a.buoc // 3, 100)}"]
    if a.min_snr > 0:
        cmd.append(f"--min_snr_gamma={a.min_snr}")
    print(f"Huấn luyện LoRA SDXL '{ten_lora}' · {n} ảnh · {a.buoc} bước · rank {a.rank} / alpha {a.alpha or a.rank // 2}"
          f"{f' · min-SNR {a.min_snr:g}' if a.min_snr > 0 else ''} · gốc {Path(a.ckpt).name}", flush=True)
    nhuong_vram()
    time.sleep(3)
    t0 = time.time()
    proc = subprocess.Popen(cmd, cwd=str(SD_SCRIPTS), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=NOWIN)
    pat = re.compile(r"steps:\s*\d+%.*?\|\s*(\d+)/(\d+)\s*\[([^\]]*)\]")
    buf, last = b"", -1
    while True:
        ch = proc.stdout.read(1)
        if not ch:
            break
        if ch not in (b"\r", b"\n"):
            buf += ch
            continue
        line = buf.decode("utf-8", "replace").strip()
        buf = b""
        if not line:
            continue
        m = pat.search(line)
        if m:
            done = int(m.group(1))
            if done != last and (done in (1, 10) or done % 50 == 0 or done == a.buoc):
                print(f"  bước {done}/{a.buoc} · {m.group(3)}", flush=True)
            last = done
        elif "steps:" not in line:
            print(line[:300], flush=True)
    proc.wait()
    final = out / f"{ten_lora}.safetensors"
    if proc.returncode != 0 or not final.exists():
        raise SystemExit(f"Huấn luyện lỗi (mã {proc.returncode}). Xem log ở trên; thường do tràn RAM/VRAM — đóng bớt ứng dụng rồi chạy lại.")
    LORA_DIR.mkdir(parents=True, exist_ok=True)
    dst = LORA_DIR / final.name
    shutil.copyfile(final, dst)
    # chỉ giữ bản cuối; checkpoint giữa chừng có thể cần để so → để lại trong output/
    print(f"✔ Xong sau {(time.time() - t0) / 60:.0f} phút → {dst}  (từ khoá: {ten_lora})")


if __name__ == "__main__":
    main()
