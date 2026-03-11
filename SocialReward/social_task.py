import time
import random
import threading
import pandas as pd
from hardware import set_led, sensor_held,deliver_reward, STOP_EVENT, open_door, close_door, reset_table_to_default, move_table_to_position, current_table_position, wait_for_door_clear

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

        # table positions
        self.rewarded_position = 1
        self.unrewarded_position = 3

        self.results_df = pd.DataFrame(columns=[
            "trial_num",
            "table_position",
            "reward_available",
            "outcome",
            "trial_start",
            "trial_end",
            "rt",
            "iti",
            "sampling_time"
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
        print("[INFO] Test session ended")

    # Trial logic
    def run_trial(self):

        trial_start = None
        trial_end = None
        sampling_time = 0
        rt = None

        reset_table_to_default(self.ser)
        self.wait(9) # 9 seconds wait for table to go back to default position

        # Choose table position
        if not self.position_block:
            self.refill_position_block()

        table_position = self.position_block.pop()
        print(f"Current table position: {current_table_position}, Target: {table_position}")
        
        move_table_to_position(self.ser, table_position)
        print("MOVE COMMAND SENT")

        reward_available = table_position == self.rewarded_position

        print(f"[INFO] Table position {table_position} | reward={reward_available}")

        #  moved iti to after table move so table has to time to finish moving before start of next trial
        iti = random.uniform(ITI_MIN, ITI_MAX)
        self.wait(iti)

        # Port A
        set_led(self.ser, "A", True)
        while self.running and not STOP_EVENT.is_set():
            state, _ = self.shared.get_port("A")
            if state == "triggered" and sensor_held(self.shared, "A"):
                print ("Port A poked, starting trial")
                break
            time.sleep(0.01)
        set_led(self.ser, "A", False)

        # Door open
        open_door(self.ser)

        # Table hold (2 seconds)
        print("Waiting for table hold...")
        while self.running and not STOP_EVENT.is_set():
            sampling_time = self.wait_for_table_hold()
            if sampling_time >= 2:
                print(f"Table hold successful: {sampling_time:.3f}s")
                break

            print(f"Hold too short ({sampling_time:.3f}s), retrying...")


        # Port C
        set_led(self.ser, "C", True)
        while self.running and not STOP_EVENT.is_set():
            st, _ = self.shared.get_port("C")
            if st == "cleared":
                break
            time.sleep(0.005)

        door_started = threading.Event()
        threading.Thread(target=close_door, args=(self.ser, self.shared), daemon=True).start()
        door_started.wait()   # waits until close command is sent

        trial_start = time.time()

        poked = self.wait_for_poke("C")

        trial_end = time.time()

        rt = (trial_end - trial_start) if poked else 5

        # Reward delivery
        if poked and reward_available:
            deliver_reward(self.ser, "C", self.valve_time)

        set_led(self.ser, "C", False)

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
            "table_position": table_position,
            "reward_available": reward_available,
            "outcome": outcome,
            "trial_start": trial_start,
            "trial_end": trial_end,
            "rt": rt,
            "iti": iti,
            "sampling_time": sampling_time
        }

        # wait for door to be fully closed from previous trial
        wait_for_door_clear(self.shared)

        print("Trial complete")

    # --------------------------
    # Helpers
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
                    state_now, _ = self.shared.get_port("table")
                    if state_now != "triggered":
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
