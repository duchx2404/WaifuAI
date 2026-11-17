"""Chạy WaifuAI: python run.py  (đọc host/port trong config.json)."""
import json
import logging
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parent
cfg_path = ROOT / "config.json"
cfg = {"host": "127.0.0.1", "port": 8600}
if cfg_path.exists():
    cfg.update(json.loads(cfg_path.read_text(encoding="utf-8")))

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    shown = "localhost" if cfg["host"] in ("0.0.0.0", "127.0.0.1") else cfg["host"]
    print(f"\n  WaifuAI  ->  Chat:     http://{shown}:{cfg['port']}/chat")
    print(f"               Quản lý:  http://{shown}:{cfg['port']}/admin\n")
    uvicorn.run("server.app:app", host=cfg["host"], port=int(cfg["port"]), log_level="warning")
