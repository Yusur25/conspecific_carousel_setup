# hardware.py
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple
import serial
import os

# ---------------------------
# Commands
# ---------------------------
COMMANDS = {
    "A": {"led_on": 0x21, "led_off": 0x22, "valve_on": 0x23, "valve_off": 0x24},
    "B": {"led_on": 0x25, "led_off": 0x26, "valve_on": 0x27, "valve_off": 0x28},
}

STOP_EVENT = threading.Event()
# ---------------------------
# Thread-safe sensor state
# ---------------------------
@dataclass
class SensorSnapshot:
    A: str
    B: str
    tA: Optional[datetime]
    tB: Optional[datetime]


class SharedSensorState:
    """
    Holds the most recent state for each port:
      state: "triggered" or "cleared"
      last_change: datetime of last change
    """
    def __init__(self):
        self._lock = threading.Lock()
        self.state = {"A": "cleared", "B": "cleared"}
        self.last_change = {"A": None, "B": None}

    def update(self, port: str, state: str, ts: datetime) -> None:
        with self._lock:
            self.state[port] = state
            self.last_change[port] = ts

    def get(self) -> SensorSnapshot:
        with self._lock:
            return SensorSnapshot(
                A=self.state["A"],
                B=self.state["B"],
                tA=self.last_change["A"],
                tB=self.last_change["B"],
            )

    def get_port(self, port: str) -> Tuple[str, Optional[datetime]]:
        with self._lock:
            return self.state[port], self.last_change[port]


# ---------------------------
# Serial listener (background)
# ---------------------------
class SerialListener(threading.Thread):
    def __init__(self, ser: serial.Serial, shared: SharedSensorState, event_log_path: str):
        super().__init__(daemon=True)
        self.ser = ser
        self.shared = shared
        self.event_log_path = event_log_path

        # write header once if file doesn't exist
        if not os.path.exists(self.event_log_path):
            with open(self.event_log_path, "w", encoding="utf-8") as f:
                f.write("timestamp,port,state,raw\n")

    def run(self):
        from utils import parse_beambreak, now
        while not STOP_EVENT.is_set():
            try:
                line = self.ser.readline()
            except Exception:
                # if serial dies, stop the experiment
                STOP_EVENT.is_set()
                break

            if not line:
                continue

            msg = line.decode("ascii", errors="ignore").strip()
            if not msg:
                continue

            port, state = parse_beambreak(msg)
            if port is None:
                continue

            ts = now()
            self.shared.update(port, state, ts)

            # log all sensor events with raw text
            with open(self.event_log_path, "a", encoding="utf-8") as f:
                f.write(f"{ts.isoformat()},{port},{state},{msg}\n")

#-----------------------------
# Hardware control functions
#-----------------------------

def deliver_reward(ser, port, valve_time=0.15):
    cmds = COMMANDS[port]
    ser.write(bytes([cmds["valve_on"]]))
    ser.flush()
    time.sleep(valve_time)
    ser.write(bytes([cmds["valve_off"]]))
    ser.flush()

def set_led(ser, port, on):
    cmds = COMMANDS[port]
    ser.write(bytes([cmds["led_on"] if on else cmds["led_off"]]))
    ser.flush()

def shutdown_outputs(ser):
    for p in ("A", "B"):
        ser.write(bytes([COMMANDS[p]["led_off"], COMMANDS[p]["valve_off"]]))
    ser.flush()