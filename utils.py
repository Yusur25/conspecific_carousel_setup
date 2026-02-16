# utils.py
from datetime import datetime
import os
from typing import Optional, Tuple

def now(): return datetime.now()

def parse_beambreak(msg: str) -> Tuple[Optional[str], Optional[str]]:
    msg_l = msg.lower()
    if "beambreak" not in msg_l: return None, None
    if "triggered" in msg_l: state = "triggered"
    elif "cleared" in msg_l: state = "cleared"
    else: return None, None
    if "port a" in msg_l: return "A", state
    if "port b" in msg_l: return "B", state
    return None, None

def safe_filename(base: str, ext: str) -> str:
    name = f"{base}.{ext}"
    if not os.path.exists(name): return name
    i = 0
    while True:
        name_i = f"{base}_{i}.{ext}"
        if not os.path.exists(name_i): return name_i
        i += 1