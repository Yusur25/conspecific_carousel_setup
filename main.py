# main.py
import argparse
import serial
import time
import signal
import os
from datetime import datetime

from hardware import SharedSensorState, SerialListener, shutdown_outputs, STOP_EVENT
from gui import PerformanceGUI, SensorGUI
from utils import now, safe_filename

from SMphases.phase1 import run_phase1
from SMphases.phase2and3 import ClassicalConditioning


def handle_sigint(sig, frame):
    STOP_EVENT.set()
    print("[INFO] Stopping...")
signal.signal(signal.SIGINT, handle_sigint)

def main():
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

    #select phase
    phase = input("Which phase? (1/2/3): ").strip()

    
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=9600)
    args = parser.parse_args()

    
    # initialise serial
    try:
        ser = serial.Serial(args.port, baudrate=args.baud, timeout=0.05)
        time.sleep(2)
    except Exception as e:
        print(f"Cannot open serial: {e}")
        return
        
    # shared state + listener + GUI (for all phases)
    shared = SharedSensorState()
    listener = SerialListener(ser, shared, sensor_log)
    listener.start()

    perf_gui = PerformanceGUI()
    sensor_gui = SensorGUI()

    try:
        if phase == "1":
            run_phase1(ser, shared, perf_gui, sensor_gui, save_dir=BASE_SAVE_DIR, animal_name=animal)
        elif phase in ("2", "3"):
            if phase == "2":
                led_time = 10 # seconds
            else: #phase 3
                led_time = 5 # seconds
            conditioning = ClassicalConditioning(ser, shared,
                perf_gui, sensor_gui, led_on_time=led_time)

            conditioning.start()
            print(f"[INFO] Phase {phase} running — press Ctrl+C to stop")

            while not STOP_EVENT.is_set():
                snap = shared.get()
                perf_gui.update(conditioning.results_df, None)
                sensor_gui.update(snap)
                time.sleep(0.1)

            conditioning.stop()
        else:
            print("Invalid phase selected")

    finally:
        STOP_EVENT.set()

        if phase in ("2", "3") and 'conditioning' in locals():
            conditioning.results_df.to_csv(trial_csv, index=False)
            print(f"[INFO] Trials saved: {trial_csv}")

        shutdown_outputs(ser)
        ser.close()
        perf_gui.close(save_path=perf_fig_path)
        sensor_gui.close()
        print("[INFO] Clean shutdown complete")

if __name__ == "__main__":
    main()
