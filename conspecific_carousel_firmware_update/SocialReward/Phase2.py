# Phase2.py — Phase 2 social reward training (rat and mouse)
#
# Door opens automatically → animal holds table sensor >= sensory_minimum s
# → animal clears table sensor → LED C on → poke C → reward
#
# Sensory minimum: 200 s timeout from door open — missed trial if not met.
# LED C: turns on once the animal clears the table sensor.
# Door: closes safely after port C poke (or miss), waits for fully closed.
#
# Species differences:
#   rat   — reward volume scales incrementally (incremental_reward)
#   mouse — fixed reward volume (deliver_reward)

import random
import threading
import time
import numpy as np
import pandas as pd

from hardware import (
    set_led,
    open_door,
    close_door_safe,
    wait_for_door_state,
    wait_for_table_clear,
    SharedSensorState,
    STOP_EVENT,
)
from .base_session import BaseSocialSession

TABLE_SENSOR_TIMEOUT = 200  # s — missed trial if sensory minimum not met


class Phase2Session(BaseSocialSession):

    _session_name = "Phase 2 Session"

    def __init__(
        self,
        ser,
        shared: SharedSensorState,
        species: str,
        sensory_minimum: float,
        valve_time: float,
        session_duration: float = None,
    ):
        super().__init__(ser, shared, species, valve_time, session_duration)
        self.sensory_minimum = sensory_minimum

        self.results_df = pd.DataFrame(columns=[
            "trial_num",
            "port",
            "trial_start",
            "trial_end",
            "rt",              # LED C on → port C poke
            "rt_dooropen",     # N/A for phase 2 (no port A); always NaN
            "rt_tablehold",    # door open → sensory minimum met
            "sampling_time",   # duration of table contact
            "iti",
            "reward_triggered",
            "reward_count",
            "valve_time",
            "outcome",         # "rewarded" / "missed"
        ])

    def _run_trial(self):
        rt              = np.nan
        rt_dooropen     = np.nan   # always NaN — no port A in phase 2
        rt_tablehold    = np.nan
        sampling_time   = np.nan
        trial_start     = np.nan
        trial_end       = np.nan
        valve_time_used = np.nan
        rewarded        = False
        outcome         = "missed"

        # ── 1. Open door automatically ────────────────────────────────────────
        threading.Thread(target=open_door, args=(self.ser,), daemon=True).start()
        wait_for_door_state(self.shared, target_state="door opened", timeout=None)
        door_open_time = time.time()
        print("Door opened")

        # ── 2. Wait for sensory minimum (200 s timeout) ───────────────────────
        print(f"Waiting for sensory minimum ({self.sensory_minimum:.3f} s)...")
        sm_met = False

        while self.running and not STOP_EVENT.is_set():
            if time.time() - door_open_time >= TABLE_SENSOR_TIMEOUT:
                print(f"Sensory minimum not met within {TABLE_SENSOR_TIMEOUT} s → missed trial")
                break

            s_time = self._wait_for_table_contact()
            if s_time is None:
                break

            if s_time >= self.sensory_minimum:
                rt_tablehold  = time.time() - door_open_time
                sampling_time = s_time
                print(f"Sensory minimum met: {s_time:.3f} s")
                sm_met = True
                break

            print(f"Sensory minimum too short ({s_time:.3f} s), retrying...")

        if not sm_met:
            iti = random.uniform(self.ITI_MIN, self.ITI_MAX)
            threading.Thread(
                target=close_door_safe, args=(self.ser, self.shared), daemon=True
            ).start()
            wait_for_door_state(self.shared, "door closed")
            self._log(trial_start, trial_end, rt, rt_dooropen, rt_tablehold,
                      sampling_time, iti, False, "missed", np.nan)
            self._run_iti(iti)
            print("Trial complete (missed)")
            return

        # ── 3. Wait for animal to clear table sensor ──────────────────────────
        print("Waiting for animal to clear table sensor...")
        wait_for_table_clear(self.shared)

        # ── 4. LED C on ───────────────────────────────────────────────────────
        set_led(self.ser, self.port, True)
        print("LED C on — waiting for port C poke")

        while self.running and not STOP_EVENT.is_set():
            if self.shared.get_port(self.port)[0] == "cleared":
                break
            time.sleep(0.005)

        trial_start = time.time()

        # ── 5. Wait for poke at port C (no deadline) ──────────────────────────
        poked     = self._wait_for_poke(self.port)
        trial_end = time.time()
        set_led(self.ser, self.port, False)

        if poked:
            rt       = trial_end - trial_start
            rewarded = True
            outcome  = "rewarded"
            valve_time_used = self._deliver_reward()
            self.reward_count += 1
            print(f"Reward delivered "
                  f"(reward #{self.reward_count}, valve={valve_time_used:.3f} s)")

        iti = random.uniform(self.ITI_MIN, self.ITI_MAX)

        # ── 6. Close door; wait for fully closed before ITI ───────────────────
        threading.Thread(
            target=close_door_safe, args=(self.ser, self.shared), daemon=True
        ).start()
        wait_for_door_state(self.shared, "door closed")
        print("Door closed, ready for next trial")

        self._log(trial_start, trial_end, rt, rt_dooropen, rt_tablehold,
                  sampling_time, iti, rewarded, outcome, valve_time_used)
        self._run_iti(iti)
        print("Trial complete")

    def _log(self, trial_start, trial_end, rt, rt_dooropen, rt_tablehold,
             sampling_time, iti, reward_triggered, outcome, valve_time_used):
        self.results_df.loc[len(self.results_df)] = {
            "trial_num":        self.trial_counter,
            "port":             self.port,
            "trial_start":      trial_start,
            "trial_end":        trial_end,
            "rt":               rt,
            "rt_dooropen":      rt_dooropen,
            "rt_tablehold":     rt_tablehold,
            "sampling_time":    sampling_time,
            "iti":              iti,
            "reward_triggered": reward_triggered,
            "reward_count":     self.reward_count,
            "valve_time":       valve_time_used,
            "outcome":          outcome,
        }
        print(self.results_df.iloc[-1].to_dict())
