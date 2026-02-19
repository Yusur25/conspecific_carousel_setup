import time
import threading
import pandas as pd
from utils import now

from datetime import datetime

from SMphases.phase2and3 import ClassicalConditioning
from hardware import (
    SharedSensorState, set_led, deliver_reward, STOP_EVENT,
    open_door, close_door, move_table_to_position, reset_table_to_default,
    wait_for_door_clear,
)

"""
    Phase 4 experiment:
    - Initial 5 min classical conditioning
    - Sampling 5 min with door/table
    - 10 min classical conditioning
    - Repeat 4x with first animal, then 5th presentation with new position
    """

class Phase4Experiment:
    def __init__(self, ser, shared: SharedSensorState, perf_gui, sensor_gui, led_on_time=5):
        self.ser = ser
        self.shared = shared
        self.perf_gui = perf_gui
        self.sensor_gui = sensor_gui
        self.led_on_time = led_on_time

        self.running = False
        self.thread = None

        # shared results_df with all required columns
        if not hasattr(self.perf_gui, "results_df"):
            self.perf_gui.results_df = pd.DataFrame(columns=[
                "trial_num", "period", "port", "forced_port", "reward_triggered", "rt", "sampling_time",
                "trial_start", "trial_end", "iti"
            ])
        self.trial_num = self.perf_gui.results_df["trial_num"].max() if not self.perf_gui.results_df.empty else 0



    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1)

    def run_classical_conditioning(self, duration_minutes, period_name):
        conditioning = ClassicalConditioning(
            self.ser,
            self.shared,
            self.perf_gui,
            self.sensor_gui,
            led_on_time=self.led_on_time
        )

        conditioning.start()
        start_time = time.time()
        last_trial_num = 0
        while time.time() - start_time < duration_minutes * 60 and not STOP_EVENT.is_set():
            # Append CC trials to main results_df
            if len(conditioning.results_df) > last_trial_num:
                new_trials = conditioning.results_df.iloc[last_trial_num:].copy()
                new_trials["trial_num"] += self.trial_num
                new_trials["period"] = period_name

                # Append
                self.perf_gui.results_df = pd.concat(
                    [self.perf_gui.results_df, new_trials],
                    ignore_index=True
                )
                last_trial_num = len(conditioning.results_df)  # update tracker
            time.sleep(0.1)

        conditioning.stop()

        # Update Phase4 trial_num to last used
        self.trial_num = self.trial_num + len(conditioning.results_df)




    def run_sampling(self, sample_minutes, table_position, period_name):
        """
        Move table, open door, let animal sample for sample_minutes.
        Wait for door to clear before closing.
        """
        # Move table before door opens
        move_table_to_position(self.ser, table_position)
        open_door(self.ser)
        t0 = time.time()

        sampling_durations = []
        prev_trigger = None

        while (time.time() - t0) < (sample_minutes * 60) and not STOP_EVENT.is_set():
            state, ts = self.shared.get_port("table")
            if state == "triggered" and prev_trigger is None:
                prev_trigger = ts
            elif state == "cleared" and prev_trigger is not None:
                sampling_durations.append((ts - prev_trigger).total_seconds())
                prev_trigger = None

            time.sleep(0.05)


        # add any ongoing trigger at end of sampling
        if prev_trigger is not None:
            sampling_durations.append((now() - prev_trigger).total_seconds())

        sampling_duration = sum(sampling_durations)

        # Wait until rat clears doorway
        print("[INFO] Waiting for rat to leave doorway...")
        wait_for_door_clear(self.shared)

        # Close door, reset table
        close_door(self.ser)
        reset_table_to_default(self.ser)

        # append to results_df
        self.trial_num += 1
        self.perf_gui.results_df.loc[len(self.perf_gui.results_df)] = {
            "trial_num": self.trial_num,
            "period": period_name,
            "port": None,
            "forced_port": None,
            "reward_triggered": None,
            "trial_start": None,
            "trial_end": None,
            "rt": None,
            "iti": None,
            "sampling_time": sampling_duration
        }


    #run full phase 4 (main experiment loop)
    def _run(self):
        try:
            # Initial classical conditioning
            self.run_classical_conditioning(duration_minutes=1, period_name="CC1")

            for i in range(4):
                if not self.running or STOP_EVENT.is_set():
                    return

                sampling_name = f"Sampling_{i+1}"
                self.run_sampling(sample_minutes=1, table_position=1, period_name=sampling_name)
                cc_name = f"CC{i + 2}"
                self.run_classical_conditioning(duration_minutes=1, period_name=cc_name)

            # Final sampling with new table position
            self.run_sampling(sample_minutes=1, table_position=4, period_name="Sampling_5")

        finally:
            reset_table_to_default(self.ser)
            close_door(self.ser)
            self.running = False