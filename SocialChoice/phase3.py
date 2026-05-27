import time
import random
import threading
import pandas as pd
from hardware import (set_led, sensor_held, deliver_reward, incremental_reward, open_door, close_door, wait_for_door_clear, wait_for_door_state, reset_table_to_default, move_table_to_position, STOP_EVENT)

#both A and B LED comes on. If A chosen -> C comes on and reward becomes available. If B chosen -> conspecific presented for 10seconds


ITI_MIN = 6.0 #seconds
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
        self.reward_count = 0
        table_position = 1
        self.port = "C"
        self.results_df = pd.DataFrame(columns=[
            "trial_num", "port", "trial_start", "trial_end",
            "rt", "rt_initial", "iti", "reward_triggered", "sampling_time", "valve_time", "reward_probability"
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
        reset_table_to_default(self.ser)
        self.wait(8) # wait for table to go back to default position

        sampling_time = 0
        valve_time_used = None
        trial_start = None
        trial_end = None
        rt = None
        rewarded = False

        print("Trial start")

        # --- Turn BOTH LEDs ON ---
        set_led(self.ser, "A", True)
        set_led(self.ser, "B", True)

        led_onset_time = time.time()

        # Ensure both ports are cleared first
        for port in ["A", "B"]:
            while self.running and not STOP_EVENT.is_set():
                st, _ = self.shared.get_port(port)
                if st == "cleared":
                    break
                time.sleep(0.005)

        chosen_port = None

        # --- Wait for FIRST poke (A or B) ---
        while self.running and not STOP_EVENT.is_set():
            for port in ["A", "B"]:
                state, _ = self.shared.get_port(port)
                if state == "triggered" and sensor_held(self.shared, port):
                    chosen_port = port
                    break
            if chosen_port:
                break
            time.sleep(0.001)

        if chosen_port is None:
            return

        rt_initial = time.time() - led_onset_time

            # Turn LEDs OFF
        set_led(self.ser, "A", False)
        set_led(self.ser, "B", False)

        # --- Small reward for poke ---
        SMALL_REWARD_TIME = 0.15
        deliver_reward(self.ser, chosen_port, SMALL_REWARD_TIME)

        print(f"Chose port {chosen_port}")

        if chosen_port == "A":

            self.port = "C"
            set_led(self.ser, "C", True)
            trial_start = time.time()
            # require port to be cleared before accepting a new poke
            while self.running and not STOP_EVENT.is_set():
                st, _ = self.shared.get_port(self.port)
                if st == "cleared":
                    break
                time.sleep(0.005)
            
            if self.led_on_time is None:
                deadline = None
            else:
                deadline = trial_start + self.led_on_time


            poked = self.wait_for_poke("C", deadline=deadline)
            trial_end = time.time()
            rt = (trial_end - trial_start) if poked else self.led_on_time
            rewarded = poked

            prob = None  # <-- initialize it

            if chosen_port == "A":
                prob = self.get_c_reward_probability()

            if poked:
                if random.random() < prob:
                    rewarded = True
                    valve_time_used = incremental_reward(self.ser, "C", self.valve_time, self.reward_count)
                    self.reward_count += 1
                else:
                    print(f"[INFO] No reward delivered (p={prob})")

            set_led(self.ser, "C", False)

        elif chosen_port == "B":
            open_door(self.ser)
           
            start_time_10s = time.time()
            end_time_10s = start_time_10s + 10

            sampling_time = 0
            table_start_time = None
            sampling = False

            while self.running and not STOP_EVENT.is_set():

                now = time.time()

                # end exactly at 10s
                if now >= end_time_10s:
                    break

                state, _ = self.shared.get_port("table")

                # --- Sampling START ---
                if state == "triggered" and not sampling:
                    sampling = True
                    sampling_start = now

                    # first time touching table sensor → RT 
                    if table_start_time is None:
                        table_start_time = now

                # --- Sampling END ---
                elif state != "triggered" and sampling:
                    sampling = False
                    sampling_time += (now - sampling_start) #total sampling time

                time.sleep(0.001)

            # if still sampling when time ends
            if sampling:
                sampling_time += (time.time() - sampling_start)

            #move table
            move_table_to_position(self.ser, 1)
            #closedoor after animal clears 
            wait_for_door_clear(self.shared)
            threading.Thread(target=close_door, args=(self.ser, self.shared), daemon=True).start()
            wait_for_door_state(self.shared, "door closed")
            trial_end = time.time()

            # RT for B
            if table_start_time is not None:
                rt = table_start_time - start_time_10s
            else:
                rt = None



        iti = random.uniform(ITI_MIN, ITI_MAX)
        self.results_df.loc[len(self.results_df)] = {
            "trial_num": self.trial_counter,
            "port": chosen_port,
            "trial_start": trial_start,
            "trial_end": trial_end,
            "rt": rt,
            "rt_initial": rt_initial,
            "iti": iti,
            "reward_triggered": rewarded,
            "sampling_time": sampling_time,
            "valve_time": valve_time_used,
            "reward_probability": prob if chosen_port == "A" else None
        }


        # ITI
        self.run_iti(iti)

        print("Trial complete")

    # ----------------------------
    # Helper Methods
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
        


    def wait_for_table_hold(self, timeout=None):
        start_wait = time.time ()
        while self.running and not STOP_EVENT.is_set():
            if timeout and (time.time() - start_wait > timeout):
                return None
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

    def wait(self, duration):
        start = time.time()
        while self.running and not STOP_EVENT.is_set():
            if time.time() - start >= duration:
                break
            time.sleep(0.02)


    def get_c_reward_probability(self):
        # each block is 20 trials
        block = (self.trial_counter - 1) // 20

        schedule = [
            1.0,   # trials 1–20
            0.75,  # 21–40
            0.5,   # 41–60
            0.25,  # 61–80
            0.0    # 81+
        ]

        if block < len(schedule):
            return schedule[block]
        else:
            return 0.0