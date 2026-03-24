#!/usr/bin/env python3
"""
Basic serial control + event monitor for your device.
Protocol assumptions (from your notes):
- Commands: single-byte hex values written to serial (e.g., 0x01, 0x10)
- Events: newline-terminated ASCII strings coming back (e.g., "BEAMBREAK 3 1\n")
Usage examples:
  python control_board_serial.py --port COM3
  python control_board_serial.py --port /dev/ttyACM0
While running, type:
  01      -> sends 0x01
  0x10    -> sends 0x10
  10      -> sends 0x10
  quit    -> exit
"""
import argparse
import sys
import threading
import time
from typing import Optional
import serial
def parse_hex_byte(s: str) -> int:
    """Parse user input like '01', '0x01', '10' into a single byte (0-255)."""
    s = s.strip().lower()
    if not s:
        raise ValueError("Empty command")
    if s.startswith("0x"):
        s = s[2:]
    value = int(s, 16)
    if not (0 <= value <= 0xFF):
        raise ValueError(f"Out of range (0x00-0xFF): 0x{value:X}")
    return value
def reader_loop(ser: serial.Serial, stop_flag: threading.Event) -> None:
    """
    Continuously read newline-terminated ASCII event messages.
    Prints each line as it arrives.
    """
    # Using readline() because events are newline-terminated ASCII
    while not stop_flag.is_set():
        try:
            line = ser.readline()  # returns b"" on timeout
            if not line:
                continue
            text = line.decode("ascii", errors="replace").rstrip("\r\n")
            if text:
                print(f"\n[EVENT] {text}")
                # re-print prompt nicely
                print("> ", end="", flush=True)
        except serial.SerialException as e:
            print(f"\n[ERROR] Serial read error: {e}")
            stop_flag.set()
            break
def send_command(ser: serial.Serial, cmd_byte: int) -> None:
    """Send a single-byte command."""
    ser.write(bytes([cmd_byte]))
    ser.flush()
def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, help="Serial port (e.g., COM3 or /dev/ttyACM0)")
    parser.add_argument("--baud", type=int, default=9600, help="Baud rate (default: 9600)")
    parser.add_argument("--timeout", type=float, default=0.2, help="Read timeout seconds (default: 0.2)")
    parser.add_argument("--startup-delay", type=float, default=2.0,
                        help="Delay after opening port (helps if device resets on connect)")
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
    # Many boards reset when you open the serial port
    time.sleep(args.startup_delay)
    print(f"[INFO] Connected to {args.port} @ {args.baud} baud")
    print("[INFO] Type a hex byte to send (e.g. 01, 0x01, 10, 0x10). Type 'quit' to exit.")
    print("[INFO] Example: 01 = LED on, 10 = open door")
    stop_flag = threading.Event()
    t = threading.Thread(target=reader_loop, args=(ser, stop_flag), daemon=True)
    t.start()
    try:
        while True:
            # Simple interactive prompt
            user = input("> ").strip()
            if not user:
                continue
            if user.lower() in ("q", "quit", "exit"):
                break
            try:
                cmd = parse_hex_byte(user)
            except ValueError as e:
                print(f"[WARN] {e}")
                continue
            try:
                send_command(ser, cmd)
                print(f"[TX] 0x{cmd:02X}")
            except serial.SerialTimeoutException:
                print("[ERROR] Write timed out")
            except serial.SerialException as e:
                print(f"[ERROR] Serial write error: {e}")
                break
    except KeyboardInterrupt:
        pass
    finally:
        stop_flag.set()
        try:
            ser.close()
        except Exception:
            pass
        print("\n[INFO] Disconnected")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
