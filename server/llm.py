"""Gọi Ollama (Gemma / Mistral Nemo / Qwen...) để sinh thoại."""
import json
import re

import httpx

from . import settings

_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
_client = httpx.AsyncClient(timeout=httpx.Timeout(600, connect=10))


class LLMError(RuntimeError):
    pass


def strip_think(text):
    return _THINK.sub("", text or "").strip()


async def chat(messages, model=None, schema=None, temperature=None):
    s = settings.get()
    model = model or s["model_chat"]
    body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "keep_alive": s["keep_alive"],
        "options": {"temperature": s["temperature"] if temperature is None else temperature, "num_ctx": 8192},
    }
    if schema is not None:
        body["format"] = schema
    if s["disable_thinking"]:
        body["think"] = False
    url = s["ollama_url"] + "/api/chat"
    try:
        r = await _client.post(url, json=body)
        if r.status_code == 400 and "think" in r.text.lower() and "think" in body:
            body.pop("think")  # mô hình không hỗ trợ tắt suy nghĩ
            r = await _client.post(url, json=body)
    except httpx.HTTPError as e:
        raise LLMError(f"Không kết nối được Ollama ({s['ollama_url']}): {e}") from e
    if r.status_code != 200:
        raise LLMError(f"Ollama trả lỗi {r.status_code}: {r.text[:300]}")
    j = r.json()
    # số token + lý do dừng của lần gọi gần nhất (ghi vào nhật ký: "length" = bị cắt vì hết chỗ)
    last_meta.clear()
    last_meta.update({"prompt_tokens": j.get("prompt_eval_count"), "output_tokens": j.get("eval_count"),
                      "done_reason": j.get("done_reason"), "num_ctx": body["options"]["num_ctx"]})
    return strip_think(j.get("message", {}).get("content", ""))


last_meta = {}


def parse_json(raw):
    raw = strip_think(raw)
    try:
        return json.loads(raw)
    except ValueError:
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                pass
    return None


async def list_models():
    s = settings.get()
    try:
        r = await _client.get(s["ollama_url"] + "/api/tags", timeout=5)
        r.raise_for_status()
        return sorted(m["name"] for m in r.json().get("models", []))
    except (httpx.HTTPError, ValueError, KeyError):
        return None


async def unload_all():
    """Nhả VRAM của mọi mô hình Ollama đang nạp (trước khi vẽ ảnh)."""
    s = settings.get()
    try:
        r = await _client.get(s["ollama_url"] + "/api/ps", timeout=5)
        for m in r.json().get("models", []):
            await _client.post(s["ollama_url"] + "/api/generate",
                               json={"model": m["name"], "keep_alive": 0}, timeout=30)
    except (httpx.HTTPError, ValueError):
        pass
