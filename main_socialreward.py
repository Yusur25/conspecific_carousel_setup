import serial
import threading
import argparse
import time
import signal
import os
import matplotlib.pyplot as plt
from datetime import datetime
from hardware import SharedSensorState, SerialListener, STOP_EVENT, shutdown_outputs
from gui import SensorGUI, PerformanceGUI
from SocialReward.phase234 import SocialRewardSession
from SocialReward.phase1 import Phase1Session


"""All phases of social reward training in one script 
 Run with --phase 1, 2, 3 or 4 to select phase.
# Phase 1: learn to poke port C for reward 
# Phase 2: learn to poke port A when LED is on, then hold table_sensor for 100 ms to get reward at port C
# Phase 3: same as phase 2 but table hold is 2 seconds
# Phase 4: same as phase 3 but restrict port C led to 5 seconds
#
"""


def handle_sigint(sig, frame):
    STOP_EVENT.set()
    print("[INFO] Stopping...")
signal.signal(signal.SIGINT, handle_sigint)


def main():
    # --- Base folder for all outputs ---
    animal = input("Enter animal name/ID: ").strip() or "unknown"
    date_str = datetime.now().strftime("%Y-%m-%d")

    BASE_SAVE_DIR = os.path.join("SocialRewardDATA", f"{animal}_{date_str}")
    os.makedirs(BASE_SAVE_DIR, exist_ok=True)
    print(f"[INFO] Saving all files to: {BASE_SAVE_DIR}")

    trial_csv = os.path.join(BASE_SAVE_DIR, "trials.csv")
    sensor_log = os.path.join(BASE_SAVE_DIR, "sensor_events.csv")
    perf_fig_path = os.path.join(BASE_SAVE_DIR, "performance.png")

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
    )
    listener.start()

    sensor_gui = SensorGUI()
    perf_gui = PerformanceGUI(animal_name=animal)

    session = None


    # --------------------------
    # Run trials in a loop
    # --------------------------
    try:
        if phase == "1":
            session = Phase1Session(
                ser,
                shared,
                save_dir=BASE_SAVE_DIR,
                animal_name=animal,
                session_duration=3600  # 1 hour
            )
            session.start()
            print("[INFO] Phase 1 running — press Ctrl+C to stop")

            # GUI update loop
            while session.running and not STOP_EVENT.is_set():
                snap = shared.get()
                sensor_gui.update(snap)
                perf_gui.update(session.results_df, current_trial_port="C")
                time.sleep(0.05)

            print("[INFO] Phase 1 session finished")

        elif phase in ("2", "3", "4"):
            if phase == "2":
                table_hold = 0.100 # seconds
                led_time = None # unlimited time
            elif phase == "3":
                table_hold = 2 # seconds
                led_time = None  # unlimited time
            else: # phase 4
                table_hold = 2  # seconds
                led_time = 5  # seconds

            session = SocialRewardSession(
                ser,
                shared,
                table_hold=table_hold,
                led_on_time= led_time,  # unlimited time
                session_duration=3600  # 1 hour
            )
            print(f"[INFO] Phase {phase} running — press Ctrl+C to stop")
            session.start()

            # GUI update loop
            while session.running and not STOP_EVENT.is_set():
                snap = shared.get()
                sensor_gui.update(snap)
                perf_gui.update(session.results_df, current_trial_port="C")
                time.sleep(0.05)

        else:
            print("Invalid phase selection")


    finally:
        print("Shutting down...")
        STOP_EVENT.set()
        if session is not None:
            session.stop()
            session.results_df.to_csv(trial_csv, index=False)
            print(f"[INFO] Trials saved: {trial_csv}")
        listener.join(timeout=1)
        shutdown_outputs(ser)
        ser.close()
        perf_gui.close(save_path=perf_fig_path)
        sensor_gui.close()
        print("[INFO] Clean shutdown complete")

if __name__ == "__main__":
    main()
