# hardware.py
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple
import serial
import os

from utils import parse_beambreak, now

# ---------------------------
# Commands
# ---------------------------
COMMANDS = {
    "A": {"led_on": 0x21, "led_off": 0x22, "valve_on": 0x23, "valve_off": 0x24},
    "B": {"led_on": 0x25, "led_off": 0x26, "valve_on": 0x27, "valve_off": 0x28},
    "C": {"led_on": 0x29, "led_off": 0x2A, "valve_on": 0x2B, "valve_off": 0x2C},
}

TABLE_TURN_CCW_45 = 0x08  # 45 degrees counter-clockwise
TABLE_TURN_CW_45  = 0x09  # 45 degrees clockwise
DOOR_OPEN  = 0x10
DOOR_CLOSE = 0x11

#TABLE LOGIC NEEDS CHANGING
DEFAULT_TABLE_POSITION = 0
# Position definitions (in 45° steps from default)
TABLE_POSITIONS = {
    0: 0,   # default / home
    1: 1,   # 45° CW
    2: 3,   # 135° CW
    3: -3,   # 135° CW
    4: -1,  # 45° CCW
}

current_table_position = DEFAULT_TABLE_POSITION

SENSOR_HOLD_TIME = 0.1

STOP_EVENT = threading.Event()
# ---------------------------
# Thread-safe sensor state
# ---------------------------
@dataclass
class SensorSnapshot:
    A: str
    B: str
    C: str
    tA: Optional[datetime]
    tB: Optional[datetime]
    tC: Optional[datetime]
    door: Optional[str] = None
    tDoor: Optional[datetime] = None
    table: Optional[str] = None
    tTable: Optional[datetime] = None


class SharedSensorState:
    """
    Holds the most recent state for each port:
      state: "triggered" or "cleared"
      last_change: datetime of last change
    """
    def __init__(self):
        self._lock = threading.Lock()
        self.state = {"A": "cleared", "B": "cleared", "C": "cleared",
                      "door": "cleared", "table": "cleared"}
        self.last_change = {"A": None, "B": None, "C": None,
                            "door": None, "table": None}

    def update(self, port: str, state: str, ts: datetime) -> None:
        with self._lock:
            self.state[port] = state
            self.last_change[port] = ts

    def get(self) -> SensorSnapshot:
        with self._lock:
            return SensorSnapshot(
                A=self.state["A"],
                B=self.state["B"],
                C=self.state["C"],
                tA=self.last_change["A"],
                tB=self.last_change["B"],
                tC=self.last_change["C"],
                door=self.state["door"],
                tDoor=self.last_change["door"],
                table=self.state["table"],
                tTable=self.last_change["table"],
            )

    def get_port(self, port: str) -> Tuple[str, Optional[datetime]]:
        with self._lock:
            return self.state[port], self.last_change[port]


# ---------------------------
# Serial listener (background)
# ---------------------------
class SerialListener(threading.Thread):
    def __init__(self, ser: serial.Serial, shared: SharedSensorState, event_log_path: str,
                 table_csv_path: str = None, door_csv_path: str = None):
        super().__init__(daemon=True)
        self.ser = ser
        self.shared = shared
        self.event_log_path = event_log_path
        self.table_event_start = None
        self.door_event_start = None
        self.table_csv_path = table_csv_path
        self.door_csv_path = door_csv_path

        self.session_start = time.time()  # track session start

        # write header once if file doesn't exist
        if not os.path.exists(self.event_log_path):
            with open(self.event_log_path, "w", encoding="utf-8") as f:
                f.write("time_str,seconds_since_start,port,state,raw\n")
        if self.table_csv_path and not os.path.exists(self.table_csv_path):
            with open(self.table_csv_path, "w", encoding="utf-8") as f:
                f.write("start,end\n")
        if self.door_csv_path and not os.path.exists(self.door_csv_path):
            with open(self.door_csv_path, "w", encoding="utf-8") as f:
                f.write("start,end\n")

    def run(self):
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


            ts = now()  # datetime object
            seconds_since_start = time.time() - self.session_start
            self.shared.update(port, state, ts)

            # log all sensor events with raw text
            with open(self.event_log_path, "a", encoding="utf-8") as f:
                f.write(f"{ts.strftime('%H:%M:%S.%f')[:-3]},{seconds_since_start:.3f},{port},{state},{msg}\n")

            if port == "table" and self.table_csv_path:
                if state == "triggered":
                    self.table_event_start = seconds_since_start
                elif state == "cleared" and self.table_event_start is not None:
                    with open(self.table_csv_path, "a", encoding="utf-8") as f:
                        f.write(f"{self.table_event_start:.3f},{seconds_since_start:.3f}\n")
                    self.table_event_start = None

            if port == "door" and self.door_csv_path:
                if state == "triggered":
                    self.door_event_start = seconds_since_start
                elif state == "cleared" and self.door_event_start is not None:
                    with open(self.door_csv_path, "a", encoding="utf-8") as f:
                        f.write(f"{self.door_event_start:.3f},{seconds_since_start:.3f}\n")
                    self.door_event_start = None

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

#led has to be held for 0.1seconds to count as a valid poke
def sensor_held(shared: SharedSensorState, port: str) -> bool:
    start = time.time()
    while time.time() - start < SENSOR_HOLD_TIME:
        if STOP_EVENT.is_set():
            return False
        st, _ = shared.get_port(port)
        if st != "triggered":
            return False
        time.sleep(0.005)
    return True

def shutdown_outputs(ser):
    for p in ("A", "B", "C"):
        ser.write(bytes([COMMANDS[p]["led_off"], COMMANDS[p]["valve_off"]]))
    ser.flush()


def turn_table(ser, steps: int):
    if steps == 0:
        return

    # Send ONE command with total steps

    cmd = TABLE_TURN_CW_45 if steps > 0 else TABLE_TURN_CCW_45

    print(f"[DEBUG] Sending single command for {steps} steps")

    # Send step count AFTER command byte
    ser.write(bytes([cmd, abs(steps)]))
    ser.flush()

def move_table_to_position(ser, target_position: int):
    global current_table_position

    if target_position not in TABLE_POSITIONS:
        raise ValueError(f"Unknown table position {target_position}")

    current_steps = TABLE_POSITIONS[current_table_position]
    target_steps = TABLE_POSITIONS[target_position]

    delta = target_steps - current_steps
    turn_table(ser, delta)

    current_table_position = target_position

def reset_table_to_default(ser):
    move_table_to_position(ser, DEFAULT_TABLE_POSITION)

def open_door(ser):
    ser.write(bytes([DOOR_OPEN]))
    ser.flush()

def wait_for_door_clear(shared: 'SharedSensorState', timeout=None):
    """
    Wait until the door sensor is cleared (rat has left the doorway).
    shared: instance of SharedSensorState tracking snsr_door
    timeout: optional maximum seconds to wait
    """
    start_time = time.time()
    while True:
        state, _ = shared.get_port("door")
        if state == "cleared":
            break
        if timeout and (time.time() - start_time) > timeout:
            print("[WARNING] Door sensor did not clear within timeout")
            break
        time.sleep(0.01)  # avoid busy-wait

def close_door(ser):
    ser.write(bytes([DOOR_CLOSE]))
    ser.flush()

