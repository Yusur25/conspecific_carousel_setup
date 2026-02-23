# phase1.py
import random
import time
import pandas as pd
import threading
from hardware import set_led, deliver_reward, SharedSensorState, STOP_EVENT, sensor_held
from utils import now, parse_beambreak, safe_filename
import os

COMMANDS = {
    "C": {"led_on": 0x29, "led_off": 0x2A, "valve_on": 0x2B, "valve_off": 0x2C}
}

ITI_MIN = 5.0
ITI_MAX = 10.0


class Phase1Session:
    def __init__(self, ser, shared: SharedSensorState,
                 save_dir: str, animal_name: str,
                 session_duration: float = 3600):
        self.ser = ser
        self.shared = shared
        self.save_dir = save_dir
        self.animal_name = animal_name
        self.session_duration = session_duration

        self.port = "C"
        self.results_df = pd.DataFrame(columns=[
            "trial_num", "port", "trial_start", "trial_end",
            "rt", "iti", "reward_triggered"
        ])
        self.trial_counter = 0
        self.running = False
        self.thread = None

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run_session, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        STOP_EVENT.set()
        if self.thread is not None:
            self.thread.join()

    def _run_session(self):
        start_time = time.time()
        while self.running and not STOP_EVENT.is_set() and (time.time() - start_time) < self.session_duration:
            self.trial_counter += 1
            trial_start = now()
            set_led(self.ser, self.port, True)
            rewarded = False

            # Wait for poke at port C
            while self.running and not STOP_EVENT.is_set():
                st, _ = self.shared.get_port(self.port)
                if st == "triggered" and sensor_held (self.shared, self.port):
                    rewarded = True
                    trial_end = now()
                    rt = (trial_end - trial_start).total_seconds()
                    deliver_reward(self.ser, self.port)
                    break
                time.sleep(0.01)

            set_led(self.ser, self.port, False)

            if not rewarded:
                trial_end = now()
                rt = 0

            iti = random.uniform(ITI_MIN, ITI_MAX)
            self.results_df.loc[len(self.results_df)] = {
                "trial_num": self.trial_counter,
                "port": self.port,
                "trial_start": trial_start,
                "trial_end": trial_end,
                "rt": rt,
                "iti": iti,
                "reward_triggered": rewarded
            }

            # ITI
            sleep_start = time.time()
            while self.running and not STOP_EVENT.is_set() and (time.time() - sleep_start) < iti:
                time.sleep(0.05)

