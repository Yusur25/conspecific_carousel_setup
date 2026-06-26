# base_session.py — shared base for all social memory sessions
#
# Key differences from SocialReward/base_session:
#   _deliver_reward(port) takes port as an argument (not fixed to self.port)
#   stop_internal()       stops this session only, without setting global STOP_EVENT
#
# _run_presentation / _run_cc_iti / _turn_to / _turn_ccw_partial are shared by any
# subclass that presents a stimulus on the turntable with a CC-filled ITI between
# presentations (SocialMemoryTaskSession, PassiveTestSession). Such subclasses must
# create self.presentations_df / self.conditioning_df (matching the columns written
# below) and set self.cc_ports / cc_led_on_time / cc_iti_min / cc_iti_max /
# cc_reward_prob / cc_delay before calling _run_cc_iti.

import random
import threading
import time

import pandas as pd

from hardware import (
    deliver_reward,
    incremental_reward,
    sensor_held,
    shutdown_outputs,
    open_door,
    close_door_safe,
    wait_for_door_state,
    wait_for_table_stopped,
    turn_table_degrees,
    SharedSensorState,
    STOP_EVENT,
)


class BaseSMSession:

    _session_name = "Session"
    ITI_MIN = 5.0
    ITI_MAX = 10.0

    # Pause after the table fully stops before issuing the next table move, so
    # the motor settles (no residual momentum/backlash) instead of one move
    # bleeding into the next — keeps repeated moves better aligned over time.
    TABLE_SETTLE_DELAY = 0.3

    def __init__(
        self,
        ser,
        shared: SharedSensorState,
        species: str,
        valve_times: dict,
        session_duration: float = None,
    ):
        self.ser = ser
        self.shared = shared
        self.species = species
        self.valve_times = valve_times
        self.session_duration = session_duration

        self.trial_counter = 0
        self.reward_count = 0
        self.max_trials = None
        self.running = False
        self.thread = None

        # Used by subclasses that present stimuli on the turntable
        self._current_angle = 0
        self._presentation_counter = 0

        # Guards reads/writes of results dataframes shared between the
        # session thread (appends rows) and the main thread (polls for the GUI).
        self._df_lock = threading.Lock()

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
            try:
                self._run_trial()
            except TimeoutError as e:
                print(f"[ERROR] Trial {self.trial_counter} aborted — serial timeout: {e}")
                try:
                    shutdown_outputs(self.ser)
                except TimeoutError:
                    print("[ERROR] Device unresponsive — could not confirm outputs off")
            if self.max_trials is not None and self.trial_counter >= self.max_trials:
                print(f"[INFO] Trial limit ({self.max_trials}) reached")
                break

        self.running = False
        print(f"[INFO] {self._session_name} ended")

    def _run_trial(self):
        raise NotImplementedError

    def snapshot(self, df: pd.DataFrame) -> pd.DataFrame:
        """Thread-safe copy of a results dataframe, for reading from the main thread
        while the session thread may be appending rows to it."""
        with self._df_lock:
            return df.copy()

    # ── Shared helpers ────────────────────────────────────────────────────────

    def _deliver_reward(self, port: str) -> float:
        """Deliver species-appropriate reward at port. Returns valve time used."""
        vt = self.valve_times[port]
        if self.species == "rat":
            return incremental_reward(self.ser, port, vt, self.reward_count)
        deliver_reward(self.ser, port, vt)
        return vt

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

    # ── Turntable stimulus presentation (shared by task/passive-test sessions) ──

    def _turn_to(self, target_angle: int) -> str:
        """Turn table to target_angle. Returns 'CW', 'CCW', or 'none'."""
        delta = (target_angle - self._current_angle) % 360
        if delta > 180:
            delta -= 360
        if delta == 0:
            return "none"
        direction = "CW" if delta > 0 else "CCW"
        turn_table_degrees(self.ser, -delta)   # negate: firmware positive = physical CCW
        self._current_angle = target_angle % 360
        return direction

    def _turn_ccw_partial(self, degrees: int) -> None:
        """Turn CCW by degrees. Called in a daemon thread."""
        turn_table_degrees(self.ser, degrees)   # positive: physical CCW (see _turn_to)
        self._current_angle = (self._current_angle - degrees) % 360

    def _turn_home_opposite(self, arrival_direction: str) -> None:
        """Return to home (0°) turning the opposite rotational direction from
        `arrival_direction` (the direction _turn_to used to reach the box just
        presented) — i.e. retrace the outbound path rather than shortest-path,
        which could pick either direction depending on the angle."""
        if self._current_angle == 0:
            return
        if arrival_direction == "CW":
            degrees = self._current_angle          # CCW back down to 0
            turn_table_degrees(self.ser, degrees)  # positive = physical CCW
        else:  # "CCW" or "none" (already-home arrival, e.g. box 0) → force CW
            degrees = 360 - self._current_angle
            turn_table_degrees(self.ser, -degrees)  # negative = physical CW
        self._current_angle = 0

    def _run_presentation(self, angle: int, duration: float, period: str,
                           extra_fields: dict = None) -> None:
        """Present a stimulus at `angle` for `duration` seconds, logging a row to
        self.presentations_df. Ends by turning the stimulus away (45° CCW), closing
        the door safely, then returning the table to home (0°) for the ITI — turning
        the opposite direction from the outbound trip — before the next presentation
        turns from home into position before its door opens."""
        self._presentation_counter += 1
        print(f"\n--- {period} (#{self._presentation_counter}): "
              f"{angle}° for {duration} s ---")

        # 1. Turntable to stimulus angle
        arrival_direction = self._turn_to(angle)
        wait_for_table_stopped(self.shared)

        # 2. Open door (async); wait for fully open
        threading.Thread(target=open_door, args=(self.ser,), daemon=True).start()
        wait_for_door_state(self.shared, "door opened", timeout=None)
        door_open_time = time.time()
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
        bout_count = 1              # the initial contact counts as the first bout

        while self.running and not STOP_EVENT.is_set() and time.time() < deadline:
            state, _ = self.shared.get_port("table")
            if state == "triggered" and contact_start is None:
                contact_start = time.time()
                bout_count += 1
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

        # 8. Let the motor fully settle before the next move (no residual
        # momentum/backlash carrying into the home turn), then return home
        # (0°) for the ITI, turning the opposite direction from the outbound
        # trip. The next presentation turns from home into position before
        # its door opens (see step 1).
        time.sleep(self.TABLE_SETTLE_DELAY)
        self._turn_home_opposite(arrival_direction)
        wait_for_table_stopped(self.shared)

        # Log
        row = {
            "presentation_num":    self._presentation_counter,
            "period":              period,
            "angle":               angle,
            "presentation_duration": duration,
            "door_open_time":      door_open_time,
            "time_to_engage":      pres_start - door_open_time,
            "sampling_time":       contact_time,
            "bout_count":          bout_count,
            "presentation_start":  pres_start,
            "presentation_end":    pres_end,
        }
        if extra_fields:
            row.update(extra_fields)
        with self._df_lock:
            self.presentations_df.loc[len(self.presentations_df)] = row
        print(f"[INFO] {period}: door closed, table at home")

    def _run_cc_iti(self, iti_min: float, iti_max: float, period_label: str) -> None:
        """Run classical conditioning for a random duration in [iti_min, iti_max],
        appending trials to self.conditioning_df. Requires self.cc_ports,
        cc_led_on_time, cc_iti_min, cc_iti_max, cc_reward_prob, cc_delay."""
        # Deferred import: training.py imports BaseSMSession from this module.
        from .training import ClassicalConditioningSession

        iti = random.uniform(iti_min, iti_max)
        print(f"\n[INFO] {period_label}: CC ITI = {iti:.1f} s"
              + (f" (CC starts after {self.cc_delay:.1f} s delay)" if self.cc_delay > 0 else ""))

        # Idle delay before conditioning begins
        if self.cc_delay > 0:
            delay_deadline = time.time() + self.cc_delay
            while self.running and not STOP_EVENT.is_set() and time.time() < delay_deadline:
                time.sleep(0.05)
            if not self.running or STOP_EVENT.is_set():
                return

        cc_duration = max(0.0, iti - self.cc_delay)
        if cc_duration <= 0:
            return

        cc = ClassicalConditioningSession(
            ser=self.ser,
            shared=self.shared,
            species=self.species,
            valve_times=self.valve_times,
            ports=self.cc_ports,
            led_on_time=self.cc_led_on_time,
            iti_min=self.cc_iti_min,
            iti_max=self.cc_iti_max,
            reward_prob=self.cc_reward_prob,
            session_duration=cc_duration,
        )
        cc.start()

        while cc.running and self.running and not STOP_EVENT.is_set():
            time.sleep(0.05)

        cc.stop_internal()

        if not cc.results_df.empty:
            df = cc.results_df.copy()  # cc's thread already joined above, safe to read directly
            df["iti_period"] = period_label
            with self._df_lock:
                self.conditioning_df = pd.concat(
                    [self.conditioning_df, df], ignore_index=True
                )
            # Keep global CC reward count in sync
            self.reward_count = cc.reward_count
