# base_session.py — shared base for all social memory sessions
#
# Key differences from SocialReward/base_session:
#   _deliver_reward(port) takes port as an argument (not fixed to self.port)
#   stop_internal()       stops this session only, without setting global STOP_EVENT

import random
import threading
import time

from hardware import (
    deliver_reward,
    incremental_reward,
    sensor_held,
    SharedSensorState,
    STOP_EVENT,
)


class BaseSMSession:

    _session_name = "Session"
    ITI_MIN = 5.0
    ITI_MAX = 10.0

    def __init__(
        self,
        ser,
        shared: SharedSensorState,
        species: str,
        valve_time: float,
        session_duration: float = None,
    ):
        self.ser = ser
        self.shared = shared
        self.species = species
        self.valve_time = valve_time
        self.session_duration = session_duration

        self.trial_counter = 0
        self.reward_count = 0
        self.max_trials = None
        self.running = False
        self.thread = None

    # ── Session control ───────────────────────────────────────────────────────

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run_session, daemon=True)
        self.thread.start()

    def stop(self):
        """Full stop — also sets global STOP_EVENT to halt all sessions."""
        self.running = False
        STOP_EVENT.set()
        if self.thread is not None:
            self.thread.join()

    def stop_internal(self):
        """Stop only this session; does not affect global STOP_EVENT."""
        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=5)

    # ── Session loop ──────────────────────────────────────────────────────────

    def _run_session(self):
        start_time = time.time()
        print(f"[INFO] {self._session_name} started")

        while self.running and not STOP_EVENT.is_set():
            if self.session_duration is not None:
                if time.time() - start_time >= self.session_duration:
                    print("[INFO] Session duration reached")
                    break
            self.trial_counter += 1
            print(f"\n=== Trial {self.trial_counter} ===")
            self._run_trial()
            if self.max_trials is not None and self.trial_counter >= self.max_trials:
                print(f"[INFO] Trial limit ({self.max_trials}) reached")
                break

        self.running = False
        print(f"[INFO] {self._session_name} ended")

    def _run_trial(self):
        raise NotImplementedError

    # ── Shared helpers ────────────────────────────────────────────────────────

    def _deliver_reward(self, port: str) -> float:
        """Deliver species-appropriate reward at port. Returns valve time used."""
        if self.species == "rat":
            return incremental_reward(
                self.ser, port, self.valve_time, self.reward_count
            )
        deliver_reward(self.ser, port, self.valve_time)
        return self.valve_time

    def _wait_for_table_contact(self):
        """Wait for table sensor to trigger; measure hold duration.
        Returns seconds held, or None if session stopped."""
        while self.running and not STOP_EVENT.is_set():
            state, _ = self.shared.get_port("table")
            if state == "triggered":
                start = time.time()
                while self.running and not STOP_EVENT.is_set():
                    if self.shared.get_port("table")[0] != "triggered":
                        break
                    time.sleep(0.001)
                return time.time() - start
            time.sleep(0.001)
        return None

    def _wait_for_poke(self, port: str, deadline: float = None) -> bool:
        """Block until port is triggered and held. Returns True on poke, False on stop/deadline."""
        while True:
            if not self.running or STOP_EVENT.is_set():
                return False
            if deadline is not None and time.time() >= deadline:
                return False
            state, _ = self.shared.get_port(port)
            if state == "triggered" and sensor_held(self.shared, port):
                return True
            time.sleep(0.001)

    def _wait(self, duration: float) -> None:
        start = time.time()
        while self.running and not STOP_EVENT.is_set() and (time.time() - start < duration):
            time.sleep(0.02)

    def _run_iti(self, iti: float = None) -> None:
        if iti is None:
            iti = random.uniform(self.ITI_MIN, self.ITI_MAX)
        start = time.time()
        while self.running and not STOP_EVENT.is_set() and (time.time() - start < iti):
            time.sleep(0.05)
