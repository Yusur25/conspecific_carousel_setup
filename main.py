# main.py
import argparse
import serial
import time
import signal
from hardware import SharedSensorState, SerialListener, shutdown_outputs
from gui import PerformanceGUI, SensorGUI
from utils import now, safe_filename
import os
from datetime import datetime
from hardware import STOP_EVENT


# --- User / experiment info ---
animal = input("Enter animal name/ID: ").strip() or "unknown"
date_str = datetime.now().strftime("%Y-%m-%d")

# --- Base folder for all outputs ---
BASE_SAVE_DIR = os.path.join("data", f"{animal}_{date_str}")
os.makedirs(BASE_SAVE_DIR, exist_ok=True)
print(f"[INFO] Saving all files to: {BASE_SAVE_DIR}")

trial_csv = os.path.join(BASE_SAVE_DIR, "trials.csv")
sensor_log = os.path.join(BASE_SAVE_DIR, "sensor_events.csv")
perf_fig_path = os.path.join(BASE_SAVE_DIR, "performance.png")


def handle_sigint(sig, frame):
    STOP_EVENT.set()
    print("[INFO] Stopping...")
signal.signal(signal.SIGINT, handle_sigint)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=9600)
    args = parser.parse_args()

    try:
        ser = serial.Serial(args.port, baudrate=args.baud, timeout=0.05)
        time.sleep(2)
    except Exception as e:
        print(f"Cannot open serial: {e}")
        return

    shared = SharedSensorState()
    listener = SerialListener(ser, shared, sensor_log)
    listener.start()

    perf_gui = PerformanceGUI()
    sensor_gui = SensorGUI()

    from SMphases.phase2and3 import run_classical

    try:
         results_df = run_classical(ser, shared, perf_gui, sensor_gui,
                               save_trial_path=trial_csv,
                               save_sensor_path=sensor_log
                )

    finally:
        STOP_EVENT.set()
        shutdown_outputs(ser)
        ser.close()
        perf_gui.close(save_path=perf_fig_path)
        sensor_gui.close()
        print("[INFO] Clean shutdown complete")

if __name__ == "__main__":
    main()