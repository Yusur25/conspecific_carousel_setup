# task.py — Social Memory Task (rat and mouse)
#
# Session sequence:
#   n_s1 presentations of S1 (at s1_angle) with CC during each ITI
#   → CC ITI (transition)
#   → n_s2 presentations of S2 (at s2_angle) with CC during each ITI
#
# Each presentation:
#   1. Turntable rotates to stimulus angle
#   2. Door opens
#   3. Sampling timer starts when table beam first broken
#   4. After presentation_duration s: turntable rotates 45° CCW (removes stimulus)
#   5. Door closes safely (pauses if table or door proximity sensors are active)
#   6. Wait for door fully closed and table motor stopped
#
# Between presentations (CC ITI):
#   Classical conditioning runs for iti_duration seconds.
#   Port selection uses anti-camping + anti-3-in-a-row rules.
#
# Two DataFrames are recorded:
#   presentations_df — one row per stimulus presentation
#   conditioning_df  — one row per CC trial across all ITIs

import random
import threading
import time
import numpy as np
import pandas as pd

from hardware import (
    open_door,
    close_door_safe,
    wait_for_door_state,
    wait_for_table_stopped,
    turn_table_degrees,
    SharedSensorState,
    STOP_EVENT,
)
from .base_session import BaseSMSession
from .training import ClassicalConditioningSession


class SocialMemoryTaskSession(BaseSMSession):

    _session_name = "Social Memory Task"

    def __init__(
        self,
        ser,
        shared: SharedSensorState,
        species: str,
        valve_time: float,
        # S1 parameters
        n_s1: int,
        s1_duration: float,
        s1_angle: int,
        s1_iti_min: float,
        s1_iti_max: float,
        # S2 parameters
        n_s2: int,
        s2_duration: float,
        s2_angle: int,
        s2_iti_min: float,
        s2_iti_max: float,
        # Classical conditioning parameters (applied during all ITIs)
        cc_ports,
        cc_led_on_time: float,
        cc_iti_min: float,
        cc_iti_max: float,
        cc_reward_prob: float = 1.0,
    ):
        super().__init__(ser, shared, species, valve_time)
        self.n_s1 = n_s1
        self.s1_duration = s1_duration
        self.s1_angle = s1_angle
        self.s1_iti_min = s1_iti_min
        self.s1_iti_max = s1_iti_max

        self.n_s2 = n_s2
        self.s2_duration = s2_duration
        self.s2_angle = s2_angle
        self.s2_iti_min = s2_iti_min
        self.s2_iti_max = s2_iti_max

        self.cc_ports = list(cc_ports)
        self.cc_led_on_time = cc_led_on_time
        self.cc_iti_min = cc_iti_min
        self.cc_iti_max = cc_iti_max
        self.cc_reward_prob = cc_reward_prob

        self._current_angle = 0  # local table angle tracking (degrees)

        self.presentations_df = pd.DataFrame(columns=[
            "presentation_num",
            "period",            # S1_1, S1_2, S2_1, ...
            "angle",
            "presentation_duration",   # configured duration (s)
            "sampling_time",           # actual time beam was triggered (s)
            "presentation_start",      # time.time() when timer started (beam first broken)
            "presentation_end",        # time.time() when presentation duration elapsed
        ])

        self.conditioning_df = pd.DataFrame(columns=[
            "trial_num",
            "iti_period",        # CC_S1_1, CC_transition, CC_S2_1, ...
            "port",
            "forced",
            "reward_triggered",
            "reward_prob_applied",
            "trial_start",
            "trial_end",
            "rt",
            "iti",
            "valve_time",
        ])

        self._presentation_counter = 0

    # ── Session loop (override — fixed sequence, not open-ended trials) ───────

    def _run_session(self):
        print(f"[INFO] {self._session_name} started")
        print(f"[INFO] S1: {self.n_s1}× {self.s1_duration} s at {self.s1_angle}°, "
              f"ITI {self.s1_iti_min}–{self.s1_iti_max} s")
        print(f"[INFO] S2: {self.n_s2}× {self.s2_duration} s at {self.s2_angle}°, "
              f"ITI {self.s2_iti_min}–{self.s2_iti_max} s")

        try:
            # ── S1 presentations ─────────────────────────────────────────────
            for i in range(self.n_s1):
                if not self.running or STOP_EVENT.is_set():
                    break
                if i > 0:
                    self._run_cc_iti(
                        self.s1_iti_min, self.s1_iti_max,
                        f"CC_S1_pre{i + 1}"
                    )
                if not self.running or STOP_EVENT.is_set():
                    break
                self._run_presentation(self.s1_angle, self.s1_duration, f"S1_{i + 1}")

            # ── Transition ITI (last S1 → first S2) ──────────────────────────
            if self.n_s2 > 0 and self.running and not STOP_EVENT.is_set():
                self._run_cc_iti(
                    self.s1_iti_min, self.s1_iti_max,
                    "CC_transition"
                )

            # ── S2 presentations ─────────────────────────────────────────────
            for i in range(self.n_s2):
                if not self.running or STOP_EVENT.is_set():
                    break
                if i > 0:
                    self._run_cc_iti(
                        self.s2_iti_min, self.s2_iti_max,
                        f"CC_S2_pre{i + 1}"
                    )
                if not self.running or STOP_EVENT.is_set():
                    break
                self._run_presentation(self.s2_angle, self.s2_duration, f"S2_{i + 1}")

        finally:
            self.running = False
            print(f"[INFO] {self._session_name} ended")

    # Required by base but not used (sequence is managed above)
    def _run_trial(self):
        raise NotImplementedError

    # ── Presentation ──────────────────────────────────────────────────────────

    def _run_presentation(self, angle: int, duration: float, period: str) -> None:
        self._presentation_counter += 1
        print(f"\n--- {period} (#{self._presentation_counter}): "
              f"{angle}° for {duration} s ---")

        # 1. Turntable to stimulus angle
        self._turn_to(angle)
        wait_for_table_stopped(self.shared)

        # 2. Open door (async); wait for fully open
        threading.Thread(target=open_door, args=(self.ser,), daemon=True).start()
        wait_for_door_state(self.shared, "door opened", timeout=None)
        print(f"[INFO] {period}: door opened")

        # 3. Wait for first table beam trigger → start presentation timer
        print(f"[INFO] {period}: waiting for beam break...")
        pres_start = None
        while self.running and not STOP_EVENT.is_set():
            state, _ = self.shared.get_port("table")
            if state == "triggered":
                pres_start = time.time()
                print(f"[INFO] {period}: beam triggered, presentation timer started")
                break
            time.sleep(0.01)

        if pres_start is None:
            # Stopped before any beam contact — close door and return
            threading.Thread(
                target=close_door_safe, args=(self.ser, self.shared), daemon=True
            ).start()
            wait_for_door_state(self.shared, "door closed")
            wait_for_table_stopped(self.shared)
            return

        # 4. Run for presentation duration; track actual contact time
        deadline = pres_start + duration
        contact_time = 0.0
        contact_start = pres_start  # beam is already triggered at pres_start

        while self.running and not STOP_EVENT.is_set() and time.time() < deadline:
            state, _ = self.shared.get_port("table")
            if state == "triggered" and contact_start is None:
                contact_start = time.time()
            elif state != "triggered" and contact_start is not None:
                contact_time += time.time() - contact_start
                contact_start = None
            time.sleep(0.01)

        if contact_start is not None:
            contact_time += time.time() - contact_start

        pres_end = time.time()
        print(f"[INFO] {period}: complete — sampling_time={contact_time:.3f} s")

        # 5. Remove stimulus: 45° CCW (async)
        threading.Thread(
            target=self._turn_ccw_partial, args=(45,), daemon=True
        ).start()

        # 6. Close door safely (pauses if sensors active)
        threading.Thread(
            target=close_door_safe, args=(self.ser, self.shared), daemon=True
        ).start()
        wait_for_door_state(self.shared, "door closed")

        # 7. Ensure table motor stopped before next presentation
        wait_for_table_stopped(self.shared)

        # Log
        self.presentations_df.loc[len(self.presentations_df)] = {
            "presentation_num":    self._presentation_counter,
            "period":              period,
            "angle":               angle,
            "presentation_duration": duration,
            "sampling_time":       contact_time,
            "presentation_start":  pres_start,
            "presentation_end":    pres_end,
        }
        print(f"[INFO] {period}: door closed, table stopped")

    # ── CC ITI ────────────────────────────────────────────────────────────────

    def _run_cc_iti(
        self, iti_min: float, iti_max: float, period_label: str
    ) -> None:
        iti = random.uniform(iti_min, iti_max)
        print(f"\n[INFO] {period_label}: CC ITI = {iti:.1f} s")

        cc = ClassicalConditioningSession(
            ser=self.ser,
            shared=self.shared,
            species=self.species,
            valve_time=self.valve_time,
            ports=self.cc_ports,
            led_on_time=self.cc_led_on_time,
            iti_min=self.cc_iti_min,
            iti_max=self.cc_iti_max,
            reward_prob=self.cc_reward_prob,
            session_duration=iti,
        )
        cc.start()

        while cc.running and self.running and not STOP_EVENT.is_set():
            time.sleep(0.05)

        cc.stop_internal()

        if not cc.results_df.empty:
            df = cc.results_df.copy()
            df["iti_period"] = period_label
            self.conditioning_df = pd.concat(
                [self.conditioning_df, df], ignore_index=True
            )
            # Keep global CC reward count in sync
            self.reward_count = cc.reward_count

    # ── Table helpers ─────────────────────────────────────────────────────────

    def _turn_to(self, target_angle: int) -> str:
        """Turn table to target_angle. Returns 'CW', 'CCW', or 'none'."""
        delta = (target_angle - self._current_angle) % 360
        if delta > 180:
            delta -= 360
        if delta == 0:
            return "none"
        direction = "CW" if delta > 0 else "CCW"
        turn_table_degrees(self.ser, delta)
        self._current_angle = target_angle % 360
        return direction

    def _turn_ccw_partial(self, degrees: int) -> None:
        """Turn CCW by degrees. Called in a daemon thread."""
        turn_table_degrees(self.ser, -degrees)
        self._current_angle = (self._current_angle - degrees) % 360
