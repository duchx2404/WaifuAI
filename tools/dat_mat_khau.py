"""Đặt / đổi mật khẩu đăng nhập WaifuAI (lưu dạng băm trong data/auth.json).

    python tools/dat_mat_khau.py              # hỏi mật khẩu (gõ không hiện)
    python tools/dat_mat_khau.py --ngau-nhien # tự sinh mật khẩu mạnh và in ra
    python tools/dat_mat_khau.py --xoa        # bỏ mật khẩu (chỉ vào được từ chính máy này)

Đổi mật khẩu thì mọi thiết bị đang đăng nhập phải đăng nhập lại. Máy chủ đang chạy nhận ngay, không cần khởi động lại.
"""
import argparse
import getpass
import secrets
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import auth  # noqa: E402

CHU = "abcdefghjkmnpqrstuvwxyz23456789"  # bỏ i, l, o, 0, 1 cho dễ đọc


def ngau_nhien() -> str:
    return "-".join("".join(secrets.choice(CHU) for _ in range(4)) for _ in range(4))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ngau-nhien", action="store_true", help="tự sinh mật khẩu")
    ap.add_argument("--xoa", action="store_true", help="bỏ mật khẩu")
    a = ap.parse_args()

    if a.xoa:
        auth.AUTH_FILE.unlink(missing_ok=True)
        print("Đã bỏ mật khẩu. WaifuAI giờ chỉ mở được trên chính máy này.")
        return

    if a.ngau_nhien:
        pw = ngau_nhien()
    else:
        pw = getpass.getpass("Mật khẩu mới (ít nhất 8 ký tự, gõ không hiện): ")
        if len(pw) < 8:
            sys.exit("Mật khẩu quá ngắn, cần ít nhất 8 ký tự.")
        if getpass.getpass("Gõ lại: ") != pw:
            sys.exit("Hai lần gõ không khớp.")

    auth.set_password(pw)
    print(f"Đã đặt mật khẩu → {auth.AUTH_FILE}")
    if a.ngau_nhien:
        print(f"\n    Mật khẩu:  {pw}\n")
        print("Ghi lại mật khẩu này — file chỉ lưu bản băm, không xem lại được.")


if __name__ == "__main__":
    main()
