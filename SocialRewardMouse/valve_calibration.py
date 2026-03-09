# valve_calibration.py

"""
Water calibration script for a single port.

1) Send a 10 s long pulse x1
2) Record end volume and calculate change; user input flow volume (ml)
3) Calculate flow rate (ml per s) = volume/total flow duration
4) Return 0.001/flow rate = pulse duration (s) to set for this port so that 1 pulse/"drop" is 1 ul
"""

import argparse
import time
import serial

COMMANDS = {
    "A": {
        "led_on":  0x21,
        "led_off": 0x22,
        "valve_on": 0x23,
        "valve_off": 0x24,
    },
    "B": {
        "led_on":  0x25,
        "led_off": 0x26,
        "valve_on": 0x27,
        "valve_off": 0x28,
    },
    "C": {
        "led_on":  0x29,
        "led_off": 0x2A,
        "valve_on": 0x2B,
        "valve_off": 0x2C,
    },
}

def flush(ser: serial.Serial, port: str, time_s: float = 10, n: int = 1) -> float:
    
    port = port.upper()
    if port not in COMMANDS:
        raise ValueError(f"Invalid port. Must be A, B, or C.")

    cmds = COMMANDS[port]

    # LED ON
    ser.write(bytes([cmds["led_on"]]))
    ser.flush()
    time.sleep(0.1)

    for _ in range(n):
        ser.write(bytes([cmds["valve_on"]]))
        ser.flush()
        time.sleep(time_s)
        ser.write(bytes([cmds["valve_off"]]))
        ser.flush()
        time.sleep(0.1)

    # LED OFF
    ser.write(bytes([cmds["led_off"]]))
    ser.flush()

    total_flow_duration = time_s * n
    return total_flow_duration

def main():
    parser = argparse.ArgumentParser(description="Water calibration script")
    parser.add_argument("--port", required=True, help="Serial COM port (e.g., COM3)")
    args = parser.parse_args()

    # Open serial port
    try:
        ser = serial.Serial(port=args.port, baudrate=9600, timeout=0.2)
        print(f"Serial port open.")
    except Exception as e:
        print(f"[ERROR] Could not open port {args.port}: {e}")
        return

    # Ask for flush port (A/B/C)
    port = input("Enter flush port (A/B/C): ").strip().upper()
    start_ml = float(input("Enter START volume (ml): ").strip())

    if port not in ["A", "B", "C"]:
        print("[ERROR] Invalid port. Must be A, B, or C.")
        ser.close()
        return
    
    try:
        print("Flowing... (10 s)")
        # Send 1-second pulses x 10
        total_flow_duration = flush(ser, port, time_s=10, n=1)
        print(f"Total flow duration: {total_flow_duration:.2f} s")

        end_ml = float(input("Enter END volume (ml): ").strip())

        # Calculate collected volume
        water_ml = start_ml - end_ml

        if water_ml <= 0:
            print("[ERROR] End volume must be smaller than start volume.")
            ser.close()
            return
        
        print(f"Flow volume: {water_ml:.3f} ml")

        # Calculate flow rate (ml per s)
        flow_rate = water_ml / total_flow_duration
        print(f"Flow rate: {flow_rate:.3f} ml/s")

        # Pulse duration for 1 ul (0.001 ml)
        duration_per_ul = 0.001 / flow_rate
        print(f"Pulse duration per 1 ul for port {port}: {duration_per_ul:.6f} s")
        
    except Exception as e:
        print(f"[ERROR] {e}")
    finally:
        ser.close()
        print("Serial port closed.")

if __name__ == "__main__":
    main()
