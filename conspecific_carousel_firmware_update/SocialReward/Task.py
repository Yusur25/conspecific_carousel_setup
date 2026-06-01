# Task.py — Social Reward Task (rat and mouse)
#
# Trial sequence:
#   1. Turntable moves to presentation position (90° or 270°, balanced block)
#   2. LED A on → animal pokes A (no deadline) → rt_dooropen recorded
#   3. Door opens → wait for fully open → sensory timer starts
#   4. Animal holds table sensor >= sensory_minimum (indefinite — no timeout)
#   5. Animal clears table sensor →
#      a. LED C on, decision window starts
#      b. Turntable rotates 45° CCW in parallel (stimulus removed from view)
#   6. Animal pokes C within decision_window → outcome classified
#   7. Reward if hit + reward_available (rat: incremental; mouse: fixed)
#   8. LED C off → close_door_safe → wait for fully closed
#   9. Turntable returns to 0° or 180° (random — balances turn direction)
#  10. Log → ITI (2–7 s)
#
# Outcomes: hit / miss / false_alarm / correct_rejection
# Recorded: turn_direction (CW/CCW) of each presentation move at trial start
#
# Species differences:
#   rat   — reward volume scales incrementally (incremental_reward)
#   mouse — fixed reward volume (deliver_reward)

import random
import threading
import time
import numpy as np
import pandas as pd

from hardware import (
    set_led,
    open_door,
    close_door_safe,
    wait_for_door_state,
    wait_for_table_clear,
    wait_for_table_stopped,
    turn_table_degrees,
    SharedSensorState,
    STOP_EVENT,
)
from .base_session import BaseSocialSession


class SocialTaskSession(BaseSocialSession):

    _session_name = "Social Task Session"
    ITI_MIN = 2.0
    ITI_MAX = 7.0

    def __init__(
        self,
        ser,
        shared: SharedSensorState,
        species: str,
        valve_time: float,
        sensory_minimum: float = 2.0,
        decision_window: float = 10.0,
        rewarded_angle: int = 90,      # degrees; presentation angle with reward animal
        unrewarded_angle: int = 270,
        session_duration: float = None,
    ):
        super().__init__(ser, shared, species, valve_time, session_duration)
        self.sensory_minimum  = sensory_minimum
        self.decision_window  = decision_window
        self.rewarded_angle   = rewarded_angle
        self.unrewarded_angle = unrewarded_angle

        self.block_size     = 10
        self.position_block = []

        # Track actual table angle in degrees locally (starts at home = 0°)
        self._current_angle = 0

        self.results_df = pd.DataFrame(columns=[
            "trial_num",
            "port",
            "trial_start",        # LED C on
            "trial_end",          # poke C or decision window elapsed
            "rt",                 # LED C on → poke C (nan if miss)
            "rt_dooropen",        # LED A on → poke A
            "rt_tablehold",       # door fully open → sensory minimum met
            "sampling_time",      # duration of table contact that met threshold
            "presentation_angle",
            "start_angle",        # table position at trial start (0 or 180)
            "turn_direction",     # CW or CCW for presentation move
            "reward_available",
            "reward_triggered",
            "outcome",            # hit / miss / false_alarm / correct_rejection
            "reward_count",
            "valve_time",
            "iti",
        ])

    # ── Trial logic ───────────────────────────────────────────────────────────

    def _run_trial(self):
        rt              = np.nan
        rt_dooropen     = np.nan
        rt_tablehold    = np.nan
        sampling_time   = np.nan
        trial_start     = np.nan
        trial_end       = np.nan
        valve_time_used = np.nan
        rewarded        = False

        # ── 1. Choose presentation position from balanced block ───────────────
        if not self.position_block:
            self._refill_position_block()

        presentation_angle = self.position_block.pop()
        reward_available   = (presentation_angle == self.rewarded_angle)
        print(f"Presentation: {presentation_angle}° | reward_available={reward_available}")

        # ── 2. Move turntable to presentation position ────────────────────────
        start_angle    = self._current_angle
        turn_direction = self._turn_to(presentation_angle)
        print(f"Table: {turn_direction} from {start_angle}° → {presentation_angle}°")
        wait_for_table_stopped(self.shared)

        # ── 3. LED A on → wait for port A poke (no deadline) ─────────────────
        set_led(self.ser, "A", True)
        print("Waiting for port A poke...")
        ledA_onset = time.time()

        while self.running and not STOP_EVENT.is_set():
            if self.shared.get_port("A")[0] == "cleared":
                break
            time.sleep(0.005)

        poked_a = self._wait_for_poke("A")

        if not poked_a:
            set_led(self.ser, "A", False)
            return  # session stopped

        rt_dooropen = time.time() - ledA_onset
        set_led(self.ser, "A", False)
        print(f"Port A poked (rt_dooropen={rt_dooropen:.3f} s)")

        # ── 4. Open door — wait for fully open; sensory timer starts ──────────
        threading.Thread(target=open_door, args=(self.ser,), daemon=True).start()
        wait_for_door_state(self.shared, target_state="door opened", timeout=None)
        door_open_time = time.time()
        print("Door opened — sensory timer started")

        # ── 5. Sensory minimum (indefinite — loops until met) ─────────────────
        print(f"Waiting for sensory minimum ({self.sensory_minimum:.3f} s)...")
        while self.running and not STOP_EVENT.is_set():
            s_time = self._wait_for_table_contact()
            if s_time is None:
                return  # session stopped

            if s_time >= self.sensory_minimum:
                rt_tablehold  = time.time() - door_open_time
                sampling_time = s_time
                print(f"Sensory minimum met: {s_time:.3f} s")
                break

            print(f"Sensory minimum too short ({s_time:.3f} s), retrying...")

        if not self.running or STOP_EVENT.is_set():
            return

        # ── 6. Wait for animal to clear table sensor ──────────────────────────
        print("Waiting for animal to clear table sensor...")
        wait_for_table_clear(self.shared)

        # ── 7. LED C on + 45° CCW turn in parallel ────────────────────────────
        set_led(self.ser, self.port, True)
        print("LED C on — 45° CCW turn to remove stimulus (async)")
        threading.Thread(
            target=self._turn_ccw_partial, args=(45,), daemon=True
        ).start()

        while self.running and not STOP_EVENT.is_set():
            if self.shared.get_port(self.port)[0] == "cleared":
                break
            time.sleep(0.005)

        trial_start = time.time()
        deadline_c  = trial_start + self.decision_window

        # ── 8. Wait for poke C within decision window ─────────────────────────
        poked     = self._wait_for_poke(self.port, deadline=deadline_c)
        trial_end = time.time()
        set_led(self.ser, self.port, False)

        if poked:
            rt = trial_end - trial_start
            if reward_available:
                rewarded = True
                valve_time_used = self._deliver_reward()
                self.reward_count += 1
                print(f"Reward delivered "
                      f"(reward #{self.reward_count}, valve={valve_time_used:.3f} s)")

        # ── 9. Outcome ────────────────────────────────────────────────────────
        if reward_available and poked:
            outcome = "hit"
        elif reward_available and not poked:
            outcome = "miss"
        elif not reward_available and poked:
            outcome = "false_alarm"
        else:
            outcome = "correct_rejection"
        print(f"Outcome: {outcome}")

        # ── 10. Close door safely ─────────────────────────────────────────────
        threading.Thread(
            target=close_door_safe, args=(self.ser, self.shared), daemon=True
        ).start()
        wait_for_door_state(self.shared, "door closed")
        print("Door closed")

        # ── 11. Turntable returns to 0° or 180° (random) ──────────────────────
        # Ensure the 45° CCW partial turn motor has stopped before the return move.
        wait_for_table_stopped(self.shared)
        return_angle = random.choice([0, 180])
        self._turn_to(return_angle)
        print(f"Table returning to {return_angle}°")
        wait_for_table_stopped(self.shared)

        iti = random.uniform(self.ITI_MIN, self.ITI_MAX)
        self._log(
            trial_start, trial_end, rt, rt_dooropen, rt_tablehold,
            sampling_time, presentation_angle, start_angle, turn_direction,
            reward_available, rewarded, outcome, valve_time_used, iti,
        )
        self._run_iti(iti)
        print("Trial complete")

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
        """Turn CCW by degrees. Called in a daemon thread for async execution."""
        turn_table_degrees(self.ser, -degrees)
        self._current_angle = (self._current_angle - degrees) % 360

    def _refill_position_block(self) -> None:
        half  = self.block_size // 2
        block = [self.rewarded_angle] * half + [self.unrewarded_angle] * half
        random.shuffle(block)
        self.position_block = block

    def _log(self, trial_start, trial_end, rt, rt_dooropen, rt_tablehold,
             sampling_time, presentation_angle, start_angle, turn_direction,
             reward_available, reward_triggered, outcome, valve_time_used, iti):
        self.results_df.loc[len(self.results_df)] = {
            "trial_num":          self.trial_counter,
            "port":               self.port,
            "trial_start":        trial_start,
            "trial_end":          trial_end,
            "rt":                 rt,
            "rt_dooropen":        rt_dooropen,
            "rt_tablehold":       rt_tablehold,
            "sampling_time":      sampling_time,
            "presentation_angle": presentation_angle,
            "start_angle":        start_angle,
            "turn_direction":     turn_direction,
            "reward_available":   reward_available,
            "reward_triggered":   reward_triggered,
            "outcome":            outcome,
            "reward_count":       self.reward_count,
            "valve_time":         valve_time_used,
            "iti":                iti,
        }
        print(self.results_df.iloc[-1].to_dict())
