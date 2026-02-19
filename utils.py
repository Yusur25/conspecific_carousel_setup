# utils.py
from datetime import datetime
import os
from typing import Optional, Tuple

def now(): return datetime.now()

def parse_beambreak(msg: str) -> Tuple[Optional[str], Optional[str]]:
    msg_l = msg.lower()
    if not any(k in msg_l for k in ("beambreak", "sensor")):
        return None, None
    if "triggered" in msg_l: state = "triggered"
    elif "cleared" in msg_l: state = "cleared"
    else: return None, None
    if "port a" in msg_l: return "A", state
    if "port b" in msg_l: return "B", state
    if "port c" in msg_l: return "C", state
    if "door" in msg_l: return "door", state
    if "table" in msg_l: return "table", state
    return None, None

def safe_filename(base: str, ext: str) -> str:
    name = f"{base}.{ext}"
    if not os.path.exists(name): return name
    i = 0
    while True:
        name_i = f"{base}_{i}.{ext}"
        if not os.path.exists(name_i): return name_i
        i += 1