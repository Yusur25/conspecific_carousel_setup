# social_task.py
import time
import random
import threading
import numpy as np
import pandas as pd
from hardware import set_led, sensor_held, deliver_reward, open_door, close_door, reset_table_to_default, move_table_to_position, wait_for_door_clear, wait_for_door_and_table_clear, wait_for_door_state, current_table_position, STOP_EVENT, disable_door_interlock

ITI_MIN = 5.0
ITI_MAX = 10.0

class SocialTestSession:

    def __init__(self, ser, shared, valve_time, session_duration=None):

        self.ser = ser
        self.shared = shared
        self.valve_time = valve_time
        self.session_duration = session_duration
        self.block_size = 10
        self.position_block = []

        self.thread = None
        self.running = False

        self.trial_counter = 0
        self.port = "C"

        # Table positions
        self.rewarded_position = 1
        self.unrewarded_position = 3

        self.results_df = pd.DataFrame(columns=[
            "trial_num",
            "port",
            "trial_start",
            "trial_end",
            "rt",
            "rt_dooropen",
            "rt_tablehold",
            "auto_dooropen", # Always set to False in social_task
            "table_position",
            "reward_available",
            "reward_triggered",
            "outcome",
            "sampling_time",
            "iti",
        ])

    # Session control
    def start(self):

        if self.running:
            return

        self.running = True

        self.thread = threading.Thread(
            target=self._run_session,
            daemon=True
        )
        self.thread.start()

    def stop(self):

        self.running = False
        STOP_EVENT.set()

        if self.thread:
            self.thread.join()

    # --------------------------
    # Main loop
    # --------------------------

    def _run_session(self):

        start_time = time.time()
        print("[INFO] Social task session started")

        while self.running and not STOP_EVENT.is_set():

            if self.session_duration:
                if time.time() - start_time >= self.session_duration:
                    print("[INFO] Session duration reached")
                    break

            self.trial_counter += 1
            print(f"\n=== Trial {self.trial_counter} ===")

            self.run_trial()

        self.running = False
        print("[INFO] Social task session ended")

    # Trial logic
    def run_trial(self):

        # disable_door_interlock(self.ser)

        trial_start = None
        trial_end = None
        rt = np.nan
        rt_dooropen = np.nan
        rt_tablehold = np.nan
        sampling_time = np.nan
        iti = np.nan
        poked = False

        reset_table_to_default(self.ser) # the box the session starts with (which can be any box) becomes the default box
        self.wait(9) # wait for table to return to default position before the next command

        # Choose table position
        if not self.position_block:
            self.refill_position_block()

        table_position = self.position_block.pop()
        print(f"Current position: {current_table_position}, Target position: {table_position}")

        move_table_to_position(self.ser, table_position)
        print("Table command sent")
        self.wait(6) # wait for table to turn to target position before the next command
        print("Table reached target position")

        reward_available = table_position == self.rewarded_position

        print(f"[INFO] Table position {table_position} | rewarded = {reward_available}")

        # Port A
        set_led(self.ser, "A", True)
        ledA_onset_time = time.time()
        
        while self.running and not STOP_EVENT.is_set():
            state, _ = self.shared.get_port("A")
            if state == "triggered" and sensor_held(self.shared, "A"):
                break
            time.sleep(0.01)
        rt_dooropen = time.time() - ledA_onset_time
        set_led(self.ser, "A", False)
        #open_door(self.ser)
        threading.Thread(target=open_door, args=(self.ser,), daemon=True).start()
        wait_for_door_state(self.shared, target_state="door opened", timeout=None)
        print("Door opened, ready for trial")
        door_open_time = time.time()

        # Table hold (2 seconds minimum)
        print("Waiting for table hold...")
        while self.running and not STOP_EVENT.is_set():
            sampling_time = self.wait_for_table_hold()
            if sampling_time >= 2:
                rt_tablehold = time.time() - door_open_time
                print(f"Table hold successful: {sampling_time:.3f}s")
                break

            print(f"Hold too short ({sampling_time:.3f}s), retrying...")

        # Port C
        set_led(self.ser, "C", True)
        while self.running and not STOP_EVENT.is_set():
            state, _ = self.shared.get_port("C")
            if state == "cleared":
                break
            time.sleep(0.005)

        # threading.Thread(target=close_door, args=(self.ser,), daemon=True).start()

        trial_start = time.time()
        print("Trial start")

        poked = self.wait_for_poke("C")
        if poked and reward_available:
            deliver_reward(self.ser, "C", self.valve_time)

        set_led(self.ser, "C", False)
        print("Trial end")
        
        wait_for_door_and_table_clear(self.shared)
        #close_door(self.ser) # <- Delayed to here until firmware can be changed
        threading.Thread(target=close_door, args=(self.ser,), daemon=True).start()
        trial_end = time.time()

        rt = (trial_end - trial_start) if poked else 5

        # Reward delivery

        # ITI
        iti = random.uniform(ITI_MIN, ITI_MAX)

        # --------------------------
        # Outcome classification
        # --------------------------
        if reward_available and poked:
            outcome = "hit"
        elif reward_available and not poked:
            outcome = "miss"
        elif not reward_available and poked:
            outcome = "false_alarm"
        else:
            outcome = "correct_rejection"

        print(f"[INFO] Outcome: {outcome}")

        self.results_df.loc[len(self.results_df)] = {
            "trial_num": self.trial_counter,
            "port": self.port,
            "trial_start": trial_start if trial_start is not None else np.nan,
            "trial_end": trial_end if trial_end is not None else np.nan,
            "rt": rt if rt is not None else np.nan,
            "rt_dooropen": rt_dooropen,
            "rt_tablehold": rt_tablehold if rt_tablehold is not None else np.nan,
            "auto_dooropen": rt_dooropen if rt_dooropen is not None else np.nan,
            "table_position": table_position,
            "reward_available": reward_available,
            "poked": poked if poked is not None else np.nan,
            "outcome": outcome if outcome is not None else np.nan,
            "sampling_time": sampling_time if sampling_time is not None else np.nan,
            "iti": iti if iti is not None else np.nan
        }

        # Wait for door to be fully closed from previous trial
        wait_for_door_state(self.shared, target_state="door closed", timeout=None)
        print("Door closed, ready for next trial")

        self.wait(iti)

    # --------------------------
    # Helper functions
    # --------------------------

    def wait_for_poke(self, port):
        deadline = time.time() + 5
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
                    state, _ = self.shared.get_port("table")
                    if state != "triggered":
                        break
                    time.sleep(0.001)
                sampling_time = time.time() - start
                return sampling_time
            time.sleep(0.001)
        return 0

    def wait(self, duration):
        start = time.time()
        while self.running and not STOP_EVENT.is_set():
            if time.time() - start >= duration:
                break
            time.sleep(0.02)

    def refill_position_block(self):
        half = self.block_size // 2

        block = (
                [self.rewarded_position] * half +
                [self.unrewarded_position] * half
        )

        random.shuffle(block)

        self.position_block = block
