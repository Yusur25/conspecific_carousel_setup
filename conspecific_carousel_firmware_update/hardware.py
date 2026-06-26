# hardware.py  –  new-firmware version
#
# Communication model (new firmware):
#   WRITE  →  [0xCC, register, 0x01, value]   →  ACK [0xCC, register, 0x02, value]
#   READ   →  [0xCC, register, 0x02, 0x00]    →  ACK [0xCC, register, 0x02, value]
#   EVENT  ←  [0xCC, register, 0x03, value]   (unsolicited, sent by firmware)
#
# The DeviceConnection class (serial_comm.py) handles the threading, ACK
# waiting and retry logic.  Session scripts pass a DeviceConnection instance
# wherever the old code accepted a serial.Serial object.

import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple
from typing import Optional, Tuple

from protocol import (
    REG_PA_LED, REG_PA_VALVE, REG_PA_IR,
    REG_PB_LED, REG_PB_VALVE, REG_PB_IR,
    REG_PC_LED, REG_PC_VALVE, REG_PC_IR,
    REG_DOOR_SENSOR, REG_TABLE_SENSOR,
    REG_DOOR_STATUS, REG_DOOR_CMD,
    REG_DOOR_OPN_SPD, REG_DOOR_CLS_SPD,
    REG_TABLE_STATUS, REG_TABLE_CMD, REG_TABLE_SPD,
    REG_CAM_A, REG_CAM_B,
    build_table_command,
)
from serial_comm import DeviceConnection
from utils import now

# ── Port register map ─────────────────────────────────────────────────────────

PORT_REGS = {
    "A": {"led": REG_PA_LED, "valve": REG_PA_VALVE, "ir": REG_PA_IR},
    "B": {"led": REG_PB_LED, "valve": REG_PB_VALVE, "ir": REG_PB_IR},
    "C": {"led": REG_PC_LED, "valve": REG_PC_VALVE, "ir": REG_PC_IR},
}

# IR register → port label
_IR_PORT_MAP = {REG_PA_IR: "A", REG_PB_IR: "B", REG_PC_IR: "C"}

# Door status register value → human-readable string (matches old firmware strings)
DOOR_STATUS_STR = {
    0: "door closed",
    1: "door opened",
    2: "door moving",
    3: "door paused",
}

# ── Table positioning ─────────────────────────────────────────────────────────

DEFAULT_TABLE_POSITION = 0

# Position index → angle in degrees
TABLE_POSITIONS = {
    0: 0,    # home
    1: 90,
    2: 180,
    3: 270,
}

current_table_position = DEFAULT_TABLE_POSITION

# ── Globals ───────────────────────────────────────────────────────────────────

SENSOR_HOLD_TIME = 0.1   # seconds a sensor must stay triggered to count as a poke
STOP_EVENT = threading.Event()

# ── Thread-safe sensor state ──────────────────────────────────────────────────

@dataclass
class SensorSnapshot:
    A: str
    B: str
    C: str
    tA: Optional[datetime]
    tB: Optional[datetime]
    tC: Optional[datetime]
    doorsensor: Optional[str] = None
    tDoorsensor: Optional[datetime] = None
    door: Optional[str] = None
    tDoor: Optional[datetime] = None
    table: Optional[str] = None
    tTable: Optional[datetime] = None
    table_motor: Optional[str] = None
    tTableMotor: Optional[datetime] = None


class SharedSensorState:
    """
    Holds the most recent decoded state for each port/sensor.
    Updated by EventLogger via DeviceConnection.on_event() callbacks.

    State strings mirror the old firmware so that session-task scripts that
    compare e.g.  state == "triggered"  or  state == "door opened"  keep
    working without modification.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.state = {
            "A": "cleared",
            "B": "cleared",
            "C": "cleared",
            "doorsensor": "cleared",
            "table": "cleared",
            "door": "door closed",
            "table_motor": "table stopped",
        }
        self.last_change: dict[str, Optional[datetime]] = {k: None for k in self.state}

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
                doorsensor=self.state["doorsensor"],
                tDoorsensor=self.last_change["doorsensor"],
                table=self.state["table"],
                tTable=self.last_change["table"],
                door=self.state["door"],
                tDoor=self.last_change["door"],
                table_motor=self.state["table_motor"],
                tTableMotor=self.last_change["table_motor"],
            )

    def get_port(self, port: str) -> Tuple[str, Optional[datetime]]:
        with self._lock:
            return self.state[port], self.last_change[port]


# ── Event logger ──────────────────────────────────────────────────────────────

class EventLogger:
    """
    Replaces the old SerialReader + SerialProcessor pair.

    Register this with DeviceConnection.on_event() and it will:
      • translate register/value events into SharedSensorState updates
      • write timestamped CSV event lines to event_log_path
      • optionally write per-interval CSVs for doorsensor and table sensor

    Usage in main script:
        device = DeviceConnection(port, baudrate=115200)
        shared = SharedSensorState()
        logger = EventLogger(shared, event_log_path=sensor_log,
                             session_start=time.time())
        device.on_event(logger)
        device.connect()
    """

    def __init__(
        self,
        shared: SharedSensorState,
        event_log_path: str,
        session_start: float,
        doorsensor_csv_path: Optional[str] = None,
        table_csv_path: Optional[str] = None,
        door_csv_path: Optional[str] = None,
    ):
        self.shared = shared
        self.event_log_path = event_log_path
        self.session_start = session_start
        self.doorsensor_csv_path = doorsensor_csv_path
        self.table_csv_path = table_csv_path
        self.door_csv_path = door_csv_path
        self._doorsensor_event_start: Optional[float] = None
        self._table_event_start: Optional[float] = None

    # Called by DeviceConnection reader thread for every MSG_EVENT packet
    def __call__(self, register: int, value: int) -> None:
        ts = now()
        t = time.time() - self.session_start

        # ── IR beam-break sensors (ports A / B / C) ───────────────────────────
        if register in _IR_PORT_MAP:
            port = _IR_PORT_MAP[register]
            state = "triggered" if value else "cleared"
            prev, _ = self.shared.get_port(port)
            if prev == state:
                print(f"[WARNING] Duplicate state for {port}: {state}")
            self.shared.update(port, state, ts)
            self._log(ts, t, port, state)

        # ── Door proximity sensor ─────────────────────────────────────────────
        elif register == REG_DOOR_SENSOR:
            state = "triggered" if value else "cleared"
            self.shared.update("doorsensor", state, ts)
            self._log(ts, t, "doorsensor", state)
            if self.doorsensor_csv_path:
                self._interval_csv("doorsensor", self.doorsensor_csv_path, state, t)

        # ── Table proximity sensor ────────────────────────────────────────────
        elif register == REG_TABLE_SENSOR:
            state = "triggered" if value else "cleared"
            self.shared.update("table", state, ts)
            self._log(ts, t, "table", state)
            if self.table_csv_path:
                self._interval_csv("table", self.table_csv_path, state, t)

        # ── Mechanical door status ────────────────────────────────────────────
        elif register == REG_DOOR_STATUS:
            state = DOOR_STATUS_STR.get(value, f"door unknown(0x{value:02X})")
            prev, _ = self.shared.get_port("door")
            if prev != state:
                self.shared.update("door", state, ts)
                self._log(ts, t, "door", state)

        # ── Table motor status (moving / stopped) ─────────────────────────────
        elif register == REG_TABLE_STATUS:
            state = "table moving" if value else "table stopped"
            self.shared.update("table_motor", state, ts)
            self._log(ts, t, "table_motor", state)

        # ── Camera sync pulse (captured separately by CameraTriggerLogger) ────
        elif register in (REG_CAM_A, REG_CAM_B):
            pass

        else:
            print(f"[WARNING] Unhandled event: register=0x{register:02X} value={value}")

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _log(self, ts: datetime, t: float, port: str, state: str) -> None:
        with open(self.event_log_path, "a", encoding="utf-8") as f:
            f.write(f"{ts.strftime('%H:%M:%S.%f')[:-3]},{t:.3f},{port},{state}\n")

    def _interval_csv(self, key: str, path: str, state: str, t: float) -> None:
        attr = f"_{key}_event_start"
        if state == "triggered":
            setattr(self, attr, t)
        elif state == "cleared":
            start = getattr(self, attr, None)
            if start is not None:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(f"{start:.3f},{t:.3f}\n")
                setattr(self, attr, None)


# ── Camera trigger capture ─────────────────────────────────────────────────────

class CameraTriggerLogger:
    """
    Captures camera sync-pulse timestamps (register REG_CAM_A by default).

    The pulse comes from cameracontrol's UserOutput1/Line2 — a brief TTL fired
    once every PULSE_EVERY_N_FRAMES video frames (~1 Hz at 30 fps), not a
    per-frame strobe. It's a checkpoint for relating video frame count to
    wall-clock time (e.g. detecting dropped frames if the interval between
    pulses drifts from the expected N/frame_rate seconds), not a per-frame
    timestamp list.

    The on-event callback is still kept deliberately minimal — it only
    appends a float to an in-memory list under a lock, with no disk I/O —
    since it runs on DeviceConnection's serial reader thread, where any
    blocking work would risk delaying ACK/event processing for the door,
    table and IR sensors.

    Recording is gated by arm()/disarm() so only a bounded window (e.g. one
    stimulus presentation) is kept; call sites elsewhere just call disarm()
    and get back the sync-pulse timestamps for that window.

    Usage:
        camera_logger = CameraTriggerLogger(session_start=session_start)
        device.on_event(camera_logger)
        ...
        camera_logger.arm()
        ... (presentation window) ...
        pulse_times = camera_logger.disarm()
    """

    def __init__(
        self,
        session_start: float,
        register: int = REG_CAM_A,
        edge: str = "rising",
    ):
        if edge not in ("rising", "falling"):
            raise ValueError("edge must be 'rising' or 'falling'")
        self._register = register
        self._trigger_value = 1 if edge == "rising" else 0
        self._session_start = session_start
        self._lock = threading.Lock()
        self._armed = False
        self._prev_value: Optional[int] = None
        self._timestamps: List[float] = []

    def arm(self) -> None:
        """Start keeping sync-pulse timestamps from this point on."""
        with self._lock:
            self._armed = True
            self._timestamps = []

    def disarm(self) -> List[float]:
        """Stop keeping sync-pulse timestamps; return and clear the buffered window."""
        with self._lock:
            self._armed = False
            timestamps, self._timestamps = self._timestamps, []
        return timestamps

    # Called by DeviceConnection's reader thread for every MSG_EVENT packet
    def __call__(self, register: int, value: int) -> None:
        if register != self._register:
            return
        prev_value = self._prev_value
        self._prev_value = value
        if prev_value is None or value == prev_value or value != self._trigger_value:
            return
        t = time.time() - self._session_start
        with self._lock:
            if self._armed:
                self._timestamps.append(t)


# ── Hardware control functions ────────────────────────────────────────────────
#
# All functions accept a DeviceConnection as their first argument.
# Call sites that previously passed a serial.Serial object just need to pass
# the DeviceConnection instead — the rest of the call signature is unchanged.

def deliver_reward(device: DeviceConnection, port: str, valve_time: float = 0.15) -> None:
    """Open valve for valve_time seconds then close."""
    reg = PORT_REGS[port]["valve"]
    device.write_register(reg, 1)
    time.sleep(valve_time)
    device.write_register(reg, 0)


def incremental_reward(
    device: DeviceConnection,
    port: str,
    valve_start: float,
    reward_count: int,
    increment: float = 0.033,
) -> float:
    """Open valve for an incrementally longer time on each reward. Returns actual valve time."""
    valve_time = valve_start + (reward_count * increment)
    reg = PORT_REGS[port]["valve"]
    device.write_register(reg, 1)
    time.sleep(valve_time)
    device.write_register(reg, 0)
    return valve_time


def set_led(device: DeviceConnection, port: str, on: bool) -> None:
    device.write_register(PORT_REGS[port]["led"], 1 if on else 0)


def sensor_held(shared: SharedSensorState, port: str) -> bool:
    """Return True if port sensor stays triggered for SENSOR_HOLD_TIME seconds."""
    start = time.time()
    while time.time() - start < SENSOR_HOLD_TIME:
        if STOP_EVENT.is_set():
            return False
        st, _ = shared.get_port(port)
        if st != "triggered":
            return False
        time.sleep(0.005)
    return True


def shutdown_outputs(device: DeviceConnection) -> None:
    """Turn off all LEDs and valves on ports A, B, C."""
    for p in ("A", "B", "C"):
        device.write_register(PORT_REGS[p]["led"], 0)
        device.write_register(PORT_REGS[p]["valve"], 0)


# ── Motor speed control ────────────────────────────────────────────────────────
#
# Speed values are single bytes (0-255) written to the firmware's speed
# registers. They persist on the device until changed again, so setting them
# once before a session (or once per move) is sufficient.

def set_door_open_speed(device: DeviceConnection, speed: int) -> None:
    device.write_register(REG_DOOR_OPN_SPD, int(speed))


def set_door_close_speed(device: DeviceConnection, speed: int) -> None:
    device.write_register(REG_DOOR_CLS_SPD, int(speed))


def set_table_speed(device: DeviceConnection, speed: int) -> None:
    device.write_register(REG_TABLE_SPD, int(speed))


def apply_motor_speeds(
    device: DeviceConnection,
    door_open_speed: Optional[int] = None,
    door_close_speed: Optional[int] = None,
    table_speed: Optional[int] = None,
) -> None:
    """Write any of the provided motor speeds to the device. None values are skipped."""
    if door_open_speed is not None:
        set_door_open_speed(device, door_open_speed)
    if door_close_speed is not None:
        set_door_close_speed(device, door_close_speed)
    if table_speed is not None:
        set_table_speed(device, table_speed)


# ── Table movement ────────────────────────────────────────────────────────────

def turn_table_degrees(device: DeviceConnection, delta_degrees: int) -> None:
    """
    Turn the table by delta_degrees.

    The new firmware encodes direction + angle in a single byte:
      bit 7 = direction (0 = CW, 1 = CCW)
      bits 6:0 = number of 1/8-turns (45° each)
    """
    if delta_degrees == 0:
        return

    delta = delta_degrees % 360
    if delta > 180:
        delta -= 360

    direction = 0 if delta > 0 else 1   # 0 = CW, 1 = CCW
    angle = abs(delta)
    eighths = angle // 45               # 90° → 2, 180° → 4, 270° → 6

    if eighths == 0:
        raise ValueError(f"Unsupported rotation angle: {angle}° (must be a multiple of 45°)")

    device.write_register(REG_TABLE_CMD, build_table_command(direction, eighths))


def move_table_to_position(device: DeviceConnection, target_position: int) -> None:
    global current_table_position

    if target_position not in TABLE_POSITIONS:
        raise ValueError(f"Unknown table position {target_position}")

    if target_position == current_table_position:
        print(f"Table already at position {target_position}")
        return

    delta = TABLE_POSITIONS[target_position] - TABLE_POSITIONS[current_table_position]
    turn_table_degrees(device, delta)
    current_table_position = target_position


def reset_table_to_default(device: DeviceConnection) -> None:
    move_table_to_position(device, DEFAULT_TABLE_POSITION)


# ── Door control ──────────────────────────────────────────────────────────────

def open_door(device: DeviceConnection) -> None:
    device.write_register(REG_DOOR_CMD, 0x00)


def close_door(
    device: DeviceConnection,
    shared: Optional[SharedSensorState] = None,
    timeout: float = 5,
) -> None:
    """
    Send close command.  If shared state is provided, waits until the door
    has fully opened before issuing the close (same safety logic as old code).
    """
    if shared is not None:
        state, _ = shared.get_port("door")
        if state != "door opened":
            print("[INFO] Waiting for door to reach opened state before closing...")
            success = wait_for_door_state(shared, "door opened", timeout)
            if not success:
                print("[ERROR] Door failed to open; aborting close.")
                return
    device.write_register(REG_DOOR_CMD, 0x01)


def disable_door_interlock(device: DeviceConnection) -> None:
    """
    Stop the door motor (closest equivalent to the old disable-interlock byte).
    The new firmware does not have a dedicated interlock command; stopping the
    door mid-travel is the safe fallback.
    """
    device.write_register(REG_DOOR_CMD, 0x02)


def close_door_safe(
    device: DeviceConnection,
    shared: SharedSensorState,
    poll_interval: float = 0.02,
) -> None:
    """Close the door with active sensor monitoring.

    Sends the close command then continuously monitors the door proximity
    sensor and the table sensor.  If either triggers during closing the door
    is stopped immediately.  Once both sensors are clear again closing
    resumes automatically.  Blocks until the door reaches 'door closed' or
    STOP_EVENT is set.

    Intended to be called inside a daemon thread so the trial loop is not
    blocked:
        threading.Thread(target=close_door_safe, args=(ser, shared), daemon=True).start()
    """
    paused = False
    device.write_register(REG_DOOR_CMD, 0x01)  # initial close command

    while not STOP_EVENT.is_set():
        door_state, _ = shared.get_port("door")
        if door_state == "door closed":
            return

        doorsensor_state, _ = shared.get_port("doorsensor")
        table_state, _ = shared.get_port("table")
        sensors_clear = (doorsensor_state == "cleared" and table_state == "cleared")

        if not sensors_clear and not paused:
            device.write_register(REG_DOOR_CMD, 0x02)  # stop
            paused = True
            print("[INFO] Door paused — sensor triggered during closing")

        elif sensors_clear and paused:
            device.write_register(REG_DOOR_CMD, 0x01)  # resume close
            paused = False
            print("[INFO] Door resuming close — sensors cleared")

        time.sleep(poll_interval)


# ── Waiting helpers ───────────────────────────────────────────────────────────

def wait_for_door_state(
    shared: SharedSensorState,
    target_state: str,
    timeout: Optional[float] = None,
) -> bool:
    """Block until mechanical door reaches target_state ('door opened', 'door closed', …)."""
    start_time = time.time()
    while True:
        if STOP_EVENT.is_set():
            return False
        state, _ = shared.get_port("door")
        if state == target_state:
            return True
        if timeout and (time.time() - start_time) > timeout:
            print(f"[WARNING] Door did not reach '{target_state}' within {timeout}s")
            return False
        time.sleep(0.01)


def wait_for_door_clear(shared: SharedSensorState) -> bool:
    """Block until the door proximity sensor is clear for at least 100 ms."""
    clear_start = None
    while True:
        if STOP_EVENT.is_set():
            return False
        state, _ = shared.get_port("doorsensor")
        if state == "cleared":
            if clear_start is None:
                clear_start = time.time()
            if time.time() - clear_start >= 0.1:
                return True
        else:
            clear_start = None
        time.sleep(0.01)


def wait_for_table_clear(shared: SharedSensorState) -> bool:
    """Block until the table proximity sensor is clear for at least 100 ms."""
    clear_start = None
    while True:
        if STOP_EVENT.is_set():
            return False
        state, _ = shared.get_port("table")
        if state == "cleared":
            if clear_start is None:
                clear_start = time.time()
            if time.time() - clear_start >= 0.1:
                return True
        else:
            clear_start = None
        time.sleep(0.01)


def wait_for_table_stopped(
    shared: SharedSensorState,
    timeout: float = 30.0,
) -> bool:
    """Block until the table motor stops after a move command.

    Waits up to 0.5 s for the motor to start (firmware latency grace period),
    then blocks until 'table stopped' is reported.  Returns True when stopped,
    False on STOP_EVENT or overall timeout.
    """
    deadline = time.time() + timeout

    # Wait briefly for the motor to start (covers firmware event latency)
    move_seen = False
    grace_end = time.time() + 0.5
    while time.time() < grace_end and not STOP_EVENT.is_set():
        state, _ = shared.get_port("table_motor")
        if state == "table moving":
            move_seen = True
            break
        time.sleep(0.01)

    if not move_seen:
        # Motor never started — zero-distance move or already complete
        return True

    while not STOP_EVENT.is_set():
        if time.time() > deadline:
            print("[WARNING] Table did not stop within timeout")
            return False
        state, _ = shared.get_port("table_motor")
        if state == "table stopped":
            return True
        time.sleep(0.01)

    return False


def wait_for_door_and_table_clear(shared: SharedSensorState) -> bool:
    """Block until BOTH door and table proximity sensors are clear for at least 100 ms."""
    clear_start = None
    while True:
        if STOP_EVENT.is_set():
            return False
        door_state, _ = shared.get_port("doorsensor")
        table_state, _ = shared.get_port("table")
        if door_state == "cleared" and table_state == "cleared":
            if clear_start is None:
                clear_start = time.time()
            if time.time() - clear_start >= 0.1:
                return True
        else:
            clear_start = None
        time.sleep(0.01)
