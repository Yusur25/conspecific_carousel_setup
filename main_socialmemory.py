# main.py
import argparse
import serial
import time
import signal
import os
import matplotlib.pyplot as plt
from datetime import datetime

from hardware import SharedSensorState, SerialListener, shutdown_outputs, STOP_EVENT
from gui import PerformanceGUI, SensorGUI
from utils import now, safe_filename

from SMphases.phase1 import run_phase1
from SMphases.phase2and3 import ClassicalConditioning
from SMphases.phase4 import Phase4Experiment


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

    table_csv = os.path.join(BASE_SAVE_DIR, "table_events.csv")
    door_csv = os.path.join(BASE_SAVE_DIR, "door_events.csv")

    #select phase
    phase = input("Which phase? (1/2/3/4): ").strip()

    
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=57600)
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
    listener = SerialListener(
        ser,
        shared,
        event_log_path=sensor_log,
        table_csv_path=table_csv,
        door_csv_path=door_csv
    )
    listener.start()

    perf_gui = PerformanceGUI(animal_name=animal)
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

        elif phase == "4":
            phase4 = Phase4Experiment(ser, shared, perf_gui, sensor_gui, led_on_time=5)
            phase4.start()
            print(f"[INFO] Phase {phase} running — press Ctrl+C to stop")


            while phase4.running and not STOP_EVENT.is_set():
                plt.pause(0.05)  # allows GUI to update
                perf_gui.update(phase4.perf_gui.results_df)
                sensor_gui.update(shared.get())


        else:
            print("Invalid phase selected")

    finally:
        STOP_EVENT.set()

        if phase in ("2", "3") and 'conditioning' in locals():
            conditioning.stop()
            # final GUI update
            snap = shared.get()
            perf_gui.update(conditioning.results_df, None)
            sensor_gui.update(snap)
            conditioning.results_df.to_csv(trial_csv, index=False)
            print(f"[INFO] Trials saved: {trial_csv}")

        if phase == "4" and hasattr(phase4.perf_gui, "results_df"):
            phase4.stop()
            snap = shared.get()
            perf_gui.update(phase4.perf_gui.results_df)
            sensor_gui.update(snap)
            phase4.perf_gui.results_df.to_csv(trial_csv, index=False)
            print(f"[INFO] Trials saved: {trial_csv}")

        listener.join(timeout=1) #added recently - could remove previous gui update blocks
        shutdown_outputs(ser)
        ser.close()
        perf_gui.close(save_path=perf_fig_path)
        sensor_gui.close()
        print("[INFO] Clean shutdown complete")

if __name__ == "__main__":
    main()
