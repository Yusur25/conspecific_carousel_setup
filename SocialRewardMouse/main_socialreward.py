# main_socialreward.py
import serial
import argparse
import time
import signal
import os
from datetime import datetime
from hardware import SharedSensorState, SerialListener, STOP_EVENT, shutdown_outputs
from gui import SensorGUI, PerformanceGUI
from SocialRewardPhases.social_task import SocialTestSession
from SocialRewardPhases.phase234 import SocialRewardSession
from SocialRewardPhases.phase1 import Phase1Session

"""All phases of social reward training in one script 

# Phase 1: port C LED -> rat pokes -> reward
# Phase 2: door automatically opens -> rat holds table sensor for 100 ms -> port C LED -> rat pokes -> reward
# Phase 3a: port A LED -> rat pokes -> door opens -> rat hold table sensor for 100 ms -> port C LED -> rat pokes -> reward
# Phase 3b: port A LED -> rat pokes -> door opens -> rat hold table sensor for 100-2000 ms -> port C LED -> rat pokes -> reward
# Phase 4: port A LED -> rat pokes -> door opens -> rat hold table sensor for 100 ms -> port C LED -> rat pokes within 5 s -> reward

"""

valve_time = 0.30  # <- change based on calibration, aim for 10-15 ul per poke

def handle_sigint(sig, frame):
    STOP_EVENT.set()
    print("[INFO] Stopping...")
signal.signal(signal.SIGINT, handle_sigint)

def main():
    # --- Base folder for all outputs ---
    animal = input("Enter animal name/ID: ").strip() or "unknown"
    session_n = input("Enter session number for the animal today: ").strip() or "1"
    phase = input("Which phase? (1/2/3a/3b/4/task): ").strip()
    date_str = datetime.now().strftime("%Y-%m-%d")

    BASE_SAVE_DIR = os.path.join("SocialRewardData", f"{animal}_{session_n}_{phase}_{date_str}")
    os.makedirs(BASE_SAVE_DIR, exist_ok=True)
    print(f"[INFO] Saving all files to: {BASE_SAVE_DIR}")

    trial_csv = os.path.join(BASE_SAVE_DIR, "trials.csv")
    sensor_log = os.path.join(BASE_SAVE_DIR, "sensor_events.csv")
    perf_fig_path = os.path.join(BASE_SAVE_DIR, "performance.png")

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
    perf_gui = PerformanceGUI(animal_name=animal, phase_selection=phase)

    session = None

    # --------------------------
    # RUN TRIALS
    # --------------------------

    try:
        if phase == "1":
            session = Phase1Session(
                ser,
                shared,
                save_dir=BASE_SAVE_DIR,
                animal_name=animal,
                valve_time=valve_time,
                session_duration=3600  # 1 hr
            )
            session.start()
            print("[INFO] Phase 1 running — press Ctrl+C to stop")

            # GUI update
            while session.running and not STOP_EVENT.is_set():
                snap = shared.get()
                sensor_gui.update(snap)
                perf_gui.update(session.results_df, current_trial_port="C")
                time.sleep(0.05)

            print("[INFO] Phase 1 session finished")

        elif phase in ("2", "3a", "3b", "4"):
            if phase == "2":
                table_hold = 0.100
                led_time = None
                require_port_a = False
            elif phase == "3a":
                table_hold = 0.100 # seconds
                led_time = None # unlimited time
                require_port_a = True
            elif phase == "3b":
                def gradual_hold(session):
                    trial = session.trial_counter
                    if trial < 15:
                        return 0.5
                    elif trial < 30:
                        return 1.0
                    elif trial < 50:
                        return 1.5
                    else:
                        return 2.0
                table_hold = gradual_hold
                led_time = None  # unlimited time
                require_port_a = True
            else: # phase 4
                table_hold = 2  # seconds
                led_time = 5  # seconds
                require_port_a = True

            session = SocialRewardSession(
                ser,
                shared,
                table_hold=table_hold,
                led_on_time= led_time,  # unlimited time
                require_port_a=require_port_a,
                valve_time=valve_time,
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
        
        elif phase == "task":
            session = SocialTestSession(
                ser,
                shared,
                valve_time=valve_time,
                session_duration=3600
            )

            session.start()

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
