# phase234.py
import time
import random
import threading
import numpy as np
import pandas as pd
from hardware import (set_led, sensor_held, deliver_reward, open_door, close_door, wait_for_door_clear, STOP_EVENT)

"""script for phases 2,3,4"""

ITI_MIN = 5.0 #seconds
ITI_MAX = 10.0


class SocialRewardSession:

    def __init__(self, ser, shared, table_hold, led_on_time, valve_time, require_port_a=True, session_duration=None):
        """
        session_duration: seconds (None = run until stopped)
        """
        self.ser = ser
        self.shared = shared
        self.thread = None
        self.table_hold = table_hold
        self.led_on_time = led_on_time
        self.require_port_a = require_port_a
        self.session_duration = session_duration
        self.valve_time = valve_time
        self.running = False
        self.trial_counter = 0
        self.port = "C"
        self.results_df = pd.DataFrame(columns=[
            "trial_num", "port", "trial_start", "trial_end",
            "rt",                    # LED C -> poke C
            "rt_tablehold",          # Door open -> successful table hold/LED C
            "rt_dooropen",           # LED A -> door open
            "iti", "reward_triggered", "sampling_time"
        ])

    # ----------------------------
    # Public API
    # ----------------------------

    def start(self):
        if self.running:
            return  # already running

        self.running = True
        self.thread = threading.Thread(
            target=self._run_session,
            daemon=True
        )
        self.thread.start()

    def stop(self):
        self.running = False
        STOP_EVENT.set()

        if self.thread is not None:
            self.thread.join()

    # ----------------------------
    # Trial Logic
    # ----------------------------
    def _run_session(self):
        start_time = time.time()

        print("[INFO] Social reward session started")

        while self.running and not STOP_EVENT.is_set():

            if self.session_duration is not None:
                if time.time() - start_time >= self.session_duration:
                    print("[INFO] Session duration reached")
                    break

            self.trial_counter += 1
            print(f"\n=== Trial {self.trial_counter} ===")
            self.run_trial()

        self.running = False
        print("[INFO] Session ended")

    def run_trial(self):
        
        # define required table hold for the trial
        if callable(self.table_hold):
            required_hold = self.table_hold(self)
        else:
            required_hold = self.table_hold
        trial_start = None
        trial_end = None
        rt = np.nan
        rt_dooropen = np.nan
        rt_tablehold = np.nan
        sampling_time = np.nan
        rewarded = False

        print("Trial start")

        rt_dooropen = None

        if self.require_port_a:
            # Port A
            set_led(self.ser, "A", True)
            ledA_onset_time = time.time()

            # require port to be cleared before accepting a new poke
            while self.running and not STOP_EVENT.is_set():
                st, _ = self.shared.get_port("A")
                if st == "cleared":
                    break
                time.sleep(0.005)

            pokedA = self.wait_for_poke("A")

            if pokedA:
                rt_dooropen = time.time() - ledA_onset_time

            set_led(self.ser, "A", False)

        open_door(self.ser)
        door_open_time = time.time()
        rt_tablehold = None

        # Table hold
        print("Waiting for table hold...")
        
        while self.running and not STOP_EVENT.is_set():
            sampling_time = self.wait_for_table_hold()

            if sampling_time >= required_hold:
                rt_tablehold = time.time() - door_open_time
                print(f"Table hold successful: {sampling_time:.3f} s")
                break

            print(f"Hold too short ({sampling_time:.3f} s), retrying...")

        # Port C
        set_led(self.ser, "C", True)
        # require port to be cleared before accepting a new poke
        while self.running and not STOP_EVENT.is_set():
            st, _ = self.shared.get_port(self.port)
            if st == "cleared":
                break
            time.sleep(0.005)
        trial_start = time.time()
        ledC_onset_time = trial_start
        
        # wait_for_door_clear(self.shared) <- delayed from here until firmware can be changed
        # close_door(self.ser)

        if self.led_on_time is None:
            deadline = None
        else:
            deadline = ledC_onset_time + self.led_on_time

        threading.Thread(target=close_door, args=(self.ser,), daemon=True).start()

        poked = self.wait_for_poke("C", deadline=deadline)
        trial_end = time.time()
        rt = (trial_end - trial_start) if poked else self.led_on_time
        rewarded = poked

        if poked:
            close_door(self.ser) # <- delayed to here until firmware can be changed
            deliver_reward(self.ser, "C", self.valve_time)
        else:
            if self.led_on_time is not None: # phase 4
                close_door(self.ser) # <- delayed to here until firmware can be changed

        set_led(self.ser, "C", False)

        # ITI
        iti = random.uniform(ITI_MIN, ITI_MAX)

        self.results_df.loc[len(self.results_df)] = {
            "trial_num": self.trial_counter,
            "port": self.port,
            "trial_start": trial_start if trial_start is not None else np.nan,
            "trial_end": trial_end if trial_end is not None else np.nan,
            "rt": rt if rt is not None else np.nan,
            "rt_dooropen": rt_dooropen if rt_dooropen is not None else np.nan,
            "rt_tablehold": rt_tablehold if rt_tablehold is not None else np.nan,
            "iti": iti if iti is not None else np.nan,
            "reward_triggered": rewarded if rewarded is not None else np.nan,
            "sampling_time": sampling_time if sampling_time is not None else np.nan
        }

        print("Trial complete")
        print(self.results_df.iloc[-1].to_dict())
        
        self.run_iti(iti)

    # ----------------------------
    # Helper functions
    # ----------------------------

    def wait_for_poke(self, port, deadline=None):
        while True:
            if not self.running or STOP_EVENT.is_set():
                break

            if deadline is not None and time.time() >= deadline:
                return False
            
            state, _ = self.shared.get_port(port)
            if state == "triggered" and sensor_held(self.shared, port):
                return True
            time.sleep(0.001)

    def wait_for_table_hold(self):
        while self.running and not STOP_EVENT.is_set():
            state, _ = self.shared.get_port("table")
            if state == "triggered":
                start = time.time()
                while self.running and not STOP_EVENT.is_set():
                    state_now, _ = self.shared.get_port("table")
                    if state_now != "triggered":
                        break

                    time.sleep(0.001)
                sampling_time = time.time() - start
                return sampling_time
            time.sleep(0.001)
        return 0  # never triggered

    def run_iti(self, iti=None):
        if iti is None:
            iti = random.uniform(ITI_MIN, ITI_MAX)
        start = time.time()
        while self.running and not STOP_EVENT.is_set() and (time.time() - start < iti):
            time.sleep(0.05)
