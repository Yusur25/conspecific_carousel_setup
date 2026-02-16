#This is phases two and three of training
#animal has to poke when led comes on to get reward. Animal has to hold poke for 0.1 seconds to get reward.
#phase 2: led ON for 10seconds
#phase 3: led ON for 5 seconds
#CHANGE PARAMETERS IN THIS FILE TO CHANGE PHASE 2 AND 3

import random
import time
import pandas as pd
from datetime import datetime
from hardware import set_led, deliver_reward, shutdown_outputs, SharedSensorState, STOP_EVENT

LED_ON_TIME = 10 #change to 5 for phase 3
SENSOR_HOLD_TIME = 0.1
ITI_MIN = 3.0
ITI_MAX = 6.0


def pick_port(presentation_history, forced_port):
    """
    Priority:
    1) Forced port (anti-camping)
    2) Anti-3-in-a-row
    3) Random
    """
    if forced_port is not None:
        return forced_port, True

    # Anti-3-in-a-row rule
    if len(presentation_history) >= 3 and \
       presentation_history[-1] == presentation_history[-2] == presentation_history[-3]:
        last = presentation_history[-1]
        return ("B" if last == "A" else "A"), True

    return random.choice(["A", "B"]), False


def held_triggered(shared: SharedSensorState, port: str, hold_time: float) -> bool:
    start = time.time()
    while time.time() - start < hold_time:
        if STOP_EVENT.is_set():
            return False
        st, _ = shared.get_port(port)
        if st != "triggered":
            return False
        time.sleep(0.005)
    return True

def run_classical(ser, shared, perf_gui, sensor_gui, max_trials=60,
                  save_trial_path=None, save_sensor_path=None):
    results_df = pd.DataFrame(columns=["trial_num","port","forced_port","reward_triggered","trial_start","trial_end","rt","iti"])
    # anti-camping + presentation history
    presentation_history = []
    history = {"A": [], "B": []}
    forced_port = None

    for trial_num in range(1, max_trials+1):
        if STOP_EVENT.is_set():
            print("[INFO] STOP detected, exiting classical conditioning phase.")
            break

        #choose port
        port, was_forced = pick_port(presentation_history, forced_port)
        presentation_history.append(port)
        if len(presentation_history) > 3: presentation_history.pop(0)

        # Run trial
        trial_start = datetime.now()
        set_led(ser, port, True)
        rewarded = False
        t0 = time.time()

        while (time.time() - t0) < LED_ON_TIME:
            if STOP_EVENT.is_set():
                break
            snap = shared.get()
            perf_gui.update(results_df, port)
            sensor_gui.update(snap)
            st, _ = shared.get_port(port)
            if st == "triggered" and held_triggered(shared, port, SENSOR_HOLD_TIME):
                rewarded = True
                break
            time.sleep(0.01)

        set_led(ser, port, False)
        trial_end = datetime.now()
        if rewarded: deliver_reward(ser, port)
        rt = (trial_end - trial_start).total_seconds() if rewarded else LED_ON_TIME
        iti = random.uniform(ITI_MIN, ITI_MAX)

        results_df.loc[len(results_df)] = {
            "trial_num": trial_num,
            "port": port,
            "forced_port": was_forced,
            "reward_triggered": rewarded,
            "trial_start": trial_start,
            "trial_end": trial_end,
            "rt": rt,
            "iti": iti,
        }

        #update reward history
        history[port].append(rewarded)
        if len(history[port]) > 3:
            history[port].pop(0)

        # anti-camping rule
        if len(history["A"]) == 3 and len(history["B"]) == 3:

            if all(x is False for x in history["A"]) and all(x is True for x in history["B"]):
                forced_port = "A"
                print("[ANTI-CAMPING] Forcing Port A (missed 3, other rewarded 3)")

            elif all(x is False for x in history["B"]) and all(x is True for x in history["A"]):
                forced_port = "B"
                print("[ANTI-CAMPING] Forcing Port B (missed 3, other rewarded 3)")

        #release forced port on success

        if rewarded and forced_port == port:
            print("[ANTI-CAMPING] Forced port rewarded — returning to normal selection")
            forced_port = None
            history = {"A": [], "B": []}

        #ITI
        sleep_start = time.time()
        while (time.time() - sleep_start) < iti:
            if STOP_EVENT.is_set():
                break
            snap = shared.get()
            perf_gui.update(results_df, port)
            sensor_gui.update(snap)
            time.sleep(0.05)

        # at the end, save files if paths are provided
        if save_trial_path is not None:
            results_df.to_csv(save_trial_path, index=False)
            print(f"[INFO] Trials saved: {save_trial_path}")

    return results_df