"""Đăng nhập bằng mật khẩu.

- Mật khẩu băm PBKDF2-SHA256 lưu trong data/auth.json (không nằm trong config.json vì file đó theo git).
- Phiên đăng nhập = cookie "hạn.chữ ký" ký HMAC bằng secret trong auth.json; đổi mật khẩu thì đổi secret
  nên mọi phiên cũ mất hiệu lực.
- Chưa đặt mật khẩu: chỉ cho truy cập trực tiếp từ chính máy này (không qua proxy như Tailscale Funnel).
- Đặt / đổi mật khẩu: tools/dat_mat_khau.py (hoặc dat-mat-khau.bat).
"""
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import deque

from . import db

AUTH_FILE = db.DATA / "auth.json"
COOKIE = "waifuai_session"
MAX_AGE = 30 * 24 * 3600
ITERATIONS = 600_000

# chống dò mật khẩu
WINDOW = 15 * 60
MAX_FAILS_PER_CLIENT = 5
MAX_FAILS_TOTAL = 30

_cache = {"mtime": None, "data": None}
_lock = threading.Lock()
_fails = {}            # client -> deque[thời điểm sai]
_fails_total = deque()


# ---------- mật khẩu ----------

def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk.hex(), hash_hex)


def load() -> dict | None:
    """Đọc auth.json (đọc lại khi file đổi, nên đổi mật khẩu không cần khởi động lại)."""
    try:
        mtime = AUTH_FILE.stat().st_mtime
    except OSError:
        _cache.update(mtime=None, data=None)
        return None
    if mtime != _cache["mtime"]:
        try:
            data = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
            if not (isinstance(data, dict) and data.get("password") and data.get("secret")):
                data = None
        except (OSError, ValueError):
            data = None
        _cache.update(mtime=mtime, data=data)
    return _cache["data"]


def enabled() -> bool:
    return load() is not None


def set_password(password: str) -> None:
    db.DATA.mkdir(parents=True, exist_ok=True)
    data = {"password": hash_password(password), "secret": secrets.token_hex(32),
            "changed_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    tmp = AUTH_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(AUTH_FILE)


# ---------- phiên ----------

def _sign(secret: str, exp: int) -> str:
    return hmac.new(secret.encode(), f"waifuai:{exp}".encode(), hashlib.sha256).hexdigest()


def make_token() -> str:
    data = load()
    exp = int(time.time()) + MAX_AGE
    return f"{exp}.{_sign(data['secret'], exp)}"


def valid_token(token: str | None) -> bool:
    data = load()
    if not data or not token or "." not in token:
        return False
    exp_s, sig = token.split(".", 1)
    try:
        exp = int(exp_s)
    except ValueError:
        return False
    return exp > time.time() and hmac.compare_digest(sig, _sign(data["secret"], exp))


# ---------- nguồn truy cập ----------

def client_key(request) -> str:
    """IP thật của người gọi. Qua Tailscale Funnel, proxy NỐI IP thật vào cuối X-Forwarded-For."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[-1].strip()
    return request.client.host if request.client else "?"


def is_direct_local(request) -> bool:
    """Gọi thẳng từ chính máy này (không qua proxy)."""
    host = request.client.host if request.client else ""
    proxied = any(h in request.headers for h in ("x-forwarded-for", "forwarded", "x-real-ip"))
    return host in ("127.0.0.1", "::1", "localhost") and not proxied


def is_https(request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"


# ---------- giới hạn sai ----------

def _trim(dq: deque, now: float) -> None:
    while dq and dq[0] < now - WINDOW:
        dq.popleft()


def locked_for(key: str) -> int:
    """Còn bao nhiêu giây bị khoá (0 = được thử)."""
    now = time.time()
    with _lock:
        _trim(_fails_total, now)
        dq = _fails.get(key, deque())
        _trim(dq, now)
        waits = []
        if len(dq) >= MAX_FAILS_PER_CLIENT:
            waits.append(dq[0] + WINDOW - now)
        if len(_fails_total) >= MAX_FAILS_TOTAL:
            waits.append(_fails_total[0] + WINDOW - now)
        return int(max(waits)) + 1 if waits else 0


def record_fail(key: str) -> None:
    now = time.time()
    with _lock:
        _fails.setdefault(key, deque()).append(now)
        _fails_total.append(now)
        if len(_fails) > 1000:  # dọn khoá cũ
            for k in [k for k, d in _fails.items() if not d or d[-1] < now - WINDOW]:
                _fails.pop(k, None)


def clear_fails(key: str) -> None:
    with _lock:
        _fails.pop(key, None)
