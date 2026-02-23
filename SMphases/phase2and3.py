#This is phases two and three of training
#animal has to poke when led comes on to get reward. Animal has to hold poke for 0.1 seconds to get reward.
#phase 2: led ON for 10seconds
#phase 3: led ON for 5 seconds


import random
import time
import threading
import pandas as pd
from datetime import datetime
from hardware import set_led, deliver_reward, SharedSensorState, STOP_EVENT, sensor_held

ITI_MIN = 5.0
ITI_MAX = 10.0


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


class ClassicalConditioning:
    def __init__(self, ser, shared, perf_gui, sensor_gui, led_on_time):
        self.LED_ON_TIME = led_on_time
        self.ser = ser
        self.shared = shared
        self.perf_gui = perf_gui
        self.sensor_gui = sensor_gui

        self.running = False
        self.thread = None

        # Data + state
        self.results_df = pd.DataFrame(columns=[
            "trial_num","port","forced_port","reward_triggered",
            "trial_start","trial_end","rt","iti"
        ])

        self.presentation_history = []
        self.history = {"A": [], "B": []}
        self.forced_port = None
        self.trial_num = 0

    # --------------------
    # Control methods
    # --------------------
    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=1)

    # --------------------
    # Main conditioning loop
    # --------------------
    def _run(self):
        while self.running and not STOP_EVENT.is_set():
            self.trial_num += 1

            # choose port
            port, was_forced = pick_port(
                self.presentation_history,
                self.forced_port
            )

            self.presentation_history.append(port)
            if len(self.presentation_history) > 3:
                self.presentation_history.pop(0)

            # run trial
            trial_start = datetime.now()
            set_led(self.ser, port, True)
            rewarded = False
            deadline = time.time() + self.LED_ON_TIME

            while time.time() < deadline:
                if not self.running or STOP_EVENT.is_set():
                    break

                st, _ = self.shared.get_port(port)
                if st == "triggered" and sensor_held(
                    self.shared, port
                ):
                    rewarded = True
                    break

                time.sleep(0.01)

            set_led(self.ser, port, False)
            trial_end = datetime.now()

            if rewarded:
                deliver_reward(self.ser, port)

            rt = (
                (trial_end - trial_start).total_seconds()
                if rewarded else self.LED_ON_TIME
            )

            iti = random.uniform(ITI_MIN, ITI_MAX)

            self.results_df.loc[len(self.results_df)] = {
                "trial_num": self.trial_num,
                "port": port,
                "forced_port": was_forced,
                "reward_triggered": rewarded,
                "trial_start": trial_start,
                "trial_end": trial_end,
                "rt": rt,
                "iti": iti,
            }

            # update reward history
            self.history[port].append(rewarded)
            if len(self.history[port]) > 3:
                self.history[port].pop(0)

            # anti-camping
            if len(self.history["A"]) == 3 and len(self.history["B"]) == 3:
                if all(x is False for x in self.history["A"]) and all(x is True for x in self.history["B"]):
                    self.forced_port = "A"
                elif all(x is False for x in self.history["B"]) and all(x is True for x in self.history["A"]):
                    self.forced_port = "B"

            if rewarded and self.forced_port == port:
                self.forced_port = None
                self.history = {"A": [], "B": []}

            # ITI
            iti_start = time.time()
            while time.time() - iti_start < iti:
                if not self.running or STOP_EVENT.is_set():
                    return
                time.sleep(0.05)
