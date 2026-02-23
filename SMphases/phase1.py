# phase1.py
import random
import time
import pandas as pd
from datetime import datetime
from hardware import set_led, deliver_reward, SharedSensorState, STOP_EVENT
from gui import PerformanceGUI, SensorGUI
from utils import now, parse_beambreak, safe_filename
import os

COMMANDS = {
    "A": {"led_on": 0x21, "led_off": 0x22, "valve_on": 0x23, "valve_off": 0x24},
    "B": {"led_on": 0x25, "led_off": 0x26, "valve_on": 0x27, "valve_off": 0x28},
}

#add sensor_held?

VALVE_OPEN_TIME = 0.150
ITI_MIN = 3.0
ITI_MAX = 6.0
MAX_TRIALS = 60
MAX_CONSECUTIVE = 3

def pick_port(last_port, same_port_count):
    """Pick next port respecting max consecutive rule."""
    if last_port is not None and same_port_count >= MAX_CONSECUTIVE:
        return "B" if last_port == "A" else "A", True
    return random.choice(["A", "B"]), False

def run_phase1(ser, shared: SharedSensorState, perf_gui: PerformanceGUI, sensor_gui: SensorGUI,
               save_dir: str, animal_name: str):
    results_df = pd.DataFrame(columns=["trial_num", "port", "trial_start", "trial_end", "rt", "iti", "reward_triggered"])
    trial_counter = 0
    last_port = None
    same_port_count = 0


    while not STOP_EVENT.is_set() and trial_counter < MAX_TRIALS:
        trial_counter += 1

        # --- choose port ---
        port, forced = pick_port(last_port, same_port_count)
        same_port_count = same_port_count + 1 if port == last_port else 1
        last_port = port

        cmds = COMMANDS[port]
        trial_start = now()
        set_led(ser, port, True)

        rewarded = False

        # Wait for poke
        while not STOP_EVENT.is_set():
            snapshot = shared.get()
            perf_gui.update(results_df, current_trial_port=port)
            sensor_gui.update(snapshot)

            st, _ = shared.get_port(port)
            if st == "triggered":
                rewarded = True
                trial_end = now()
                rt = (trial_end - trial_start).total_seconds()
                deliver_reward(ser, port)
                break
            time.sleep(0.01)

        # LED off after reward
        set_led(ser, port, False)
        if not rewarded:
            trial_end = now()
            rt = 0

        iti = random.uniform(ITI_MIN, ITI_MAX)


        results_df.loc[len(results_df)] = {
            "trial_num": trial_counter,
            "port": port,
            "trial_start": trial_start,
            "trial_end": trial_end,
            "rt": rt,
            "iti": iti,
            "reward_triggered": rewarded,
        }

        # Update GUI
        perf_gui.update(results_df, current_trial_port=port)
        sensor_gui.update(shared.get())

        # Inter-trial interval
        sleep_start = time.time()
        while not STOP_EVENT.is_set() and (time.time() - sleep_start) < iti:
            sensor_gui.update(shared.get())
            time.sleep(0.05)


    # Save results
    os.makedirs(save_dir, exist_ok=True)
    filename = safe_filename(os.path.join(save_dir, f"{animal_name}_phase1"), "csv")
    results_df.to_csv(filename, index=False)
    print(f"[INFO] Phase 1 results saved: {filename}")
    return results_df
