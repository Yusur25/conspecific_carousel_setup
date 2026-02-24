import time
import random
import threading
import pandas as pd
from hardware import (set_led, sensor_held, deliver_reward, open_door,close_door, wait_for_door_clear, STOP_EVENT)

"""script for phases 2,3,4"""


ITI_MIN = 5.0 #seconds
ITI_MAX = 10.0


class SocialRewardSession:

    def __init__(self, ser, shared, table_hold, led_on_time, session_duration=None):
        """
        session_duration: seconds (None = run until stopped)
        """
        self.ser = ser
        self.shared = shared
        self.thread = None
        self.table_hold = table_hold
        self.led_on_time = led_on_time
        self.session_duration = session_duration
        self.running = False
        self.trial_counter = 0
        self.port = "C"
        self.results_df = pd.DataFrame(columns=[
            "trial_num", "port", "trial_start", "trial_end",
            "rt", "iti", "reward_triggered", "sampling_time"
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
        trial_start = None
        trial_end = None
        rt = None
        rewarded = False

        print("Trial start")

        # Port A
        set_led(self.ser, "A", True)
        if not self.wait_for_poke("A"):
            return
        set_led(self.ser, "A", False)

        open_door(self.ser)

        # Table hold
        print("Waiting for table hold...")
        while self.running and not STOP_EVENT.is_set():
            sampling_time = self.wait_for_table_hold()

            if sampling_time >= self.table_hold:
                print(f"Table hold successful: {sampling_time:.3f}s")
                break

            print(f"Hold too short ({sampling_time:.3f}s), retrying...")

        # Port C
        set_led(self.ser, "C", True)
        trial_start = time.time()
        
        wait_for_door_clear(self.shared)
        close_door(self.ser)

        poked = self.wait_for_poke("C")
        trial_end = time.time()
        rt = (trial_end - trial_start) if poked else self.led_on_time
        rewarded = poked

        if poked:
            deliver_reward(self.ser, "C")

        set_led(self.ser, "C", False)

        iti = random.uniform(ITI_MIN, ITI_MAX)
        self.results_df.loc[len(self.results_df)] = {
            "trial_num": self.trial_counter,
            "port": self.port,
            "trial_start": trial_start,
            "trial_end": trial_end,
            "rt": rt,
            "iti": iti,
            "reward_triggered": rewarded,
            "sampling_time": sampling_time
        }

        # ITI
        self.run_iti()

        print("Trial complete")

    # ----------------------------
    # Helper Methods
    # ----------------------------

    def wait_for_poke(self, port):
        if port == "C" and self.led_on_time is not None:
            deadline = time.time() + self.led_on_time
        else:
            deadline = float('inf')  # no limit

        while time.time() < deadline:
            if not self.running or STOP_EVENT.is_set():
                break

            state, _ = self.shared.get_port(port)
            if state == "triggered" and sensor_held(self.shared, port):
                return True
            time.sleep(0.001)
        return False


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
