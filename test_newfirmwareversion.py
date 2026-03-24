#!/usr/bin/env python3

# type 1 (value) to turn LED on
# type 0 (value) to turn LED off

import argparse
import time
from typing import Optional

import serial


HEADER = 0xCC
MSG_WRITE = 0x01
REGISTER = 0x24  # LEDA


def build_packet(register: int, msg_type: int, value: int = 0) -> bytes:
    """Build a 4-byte packet: [HEADER, register, msg_type, value]."""
    for name, v in {
        "register": register,
        "msg_type": msg_type,
        "value": value,
    }.items():
        if not 0 <= v <= 0xFF:
            raise ValueError(f"{name} must be in range 0..255, got {v}")
    return bytes((HEADER, register, msg_type, value))


def send_command(ser: serial.Serial, packet: bytes) -> None:
    """Send a 4-byte packet."""
    ser.write(packet)
    ser.flush()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, help="Serial port (e.g., COM3 or /dev/ttyACM0)")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate (default: 115200)")
    parser.add_argument("--timeout", type=float, default=0.2, help="Read timeout seconds (default: 0.2)")
    parser.add_argument(
        "--startup-delay",
        type=float,
        default=2.0,
        help="Delay after opening port (helps if device resets on connect)",
    )
    args = parser.parse_args(argv)

    try:
        ser = serial.Serial(
            port=args.port,
            baudrate=args.baud,
            timeout=args.timeout,
            write_timeout=1.0,
        )
    except serial.SerialException as e:
        print(f"[ERROR] Could not open port {args.port}: {e}")
        return 1

    time.sleep(args.startup_delay)
    print(f"[INFO] Connected to {args.port} @ {args.baud} baud")
    print("Type 0 or 1 to control LEDA, or q to quit.")

    try:
        while True:
            user = input("> ").strip().lower()

            if user in ("q", "quit", "exit"):
                break
            if user not in ("0", "1"):
                print("[ERROR] Enter 0, 1, or q")
                continue

            value = int(user)
            packet = build_packet(REGISTER, MSG_WRITE, value)

            try:
                send_command(ser, packet)
                print(f"[INFO] Sent: {[hex(b) for b in packet]}")
            except serial.SerialTimeoutException:
                print("[ERROR] Write timed out")
            except serial.SerialException as e:
                print(f"[ERROR] Serial write error: {e}")
                break

    except KeyboardInterrupt:
        pass
    finally:
        try:
            ser.close()
        except Exception:
            pass
        print("\n[INFO] Disconnected")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())