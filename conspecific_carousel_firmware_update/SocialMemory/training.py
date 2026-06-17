# training.py — Classical conditioning training for social memory (rat and mouse)
#
# Trial sequence:
#   Random port LED on (from selected ports) → animal pokes within led_on_time → reward
#
# Port selection rules (applied in priority order):
#   1. Anti-camping forced port — if animal camps at one port (last 3 hits there,
#      last 3 misses at another), the neglected port is forced next.
#   2. Anti-3-in-a-row — if last 3 picks were the same port, exclude it.
#   3. Random from remaining valid ports.
#
# Reward probability:
#   reward_prob < 1.0 enables partial reinforcement — reward delivered only on a
#   proportion of pokes (e.g., 0.75 → 75 % of pokes rewarded).
#
# Species differences:
#   rat   — incremental_reward (volume scales with reward count)
#   mouse — fixed deliver_reward

import random
import time
import numpy as np
import pandas as pd

from hardware import set_led, STOP_EVENT
from .base_session import BaseSMSession


class ClassicalConditioningSession(BaseSMSession):

    _session_name = "Classical Conditioning"

    def __init__(
        self,
        ser,
        shared,
        species: str,
        valve_times: dict,
        ports,               # list — e.g. ["A", "B"] or ["A", "B", "C"]
        led_on_time: float,
        iti_min: float,
        iti_max: float,
        reward_prob: float = 1.0,
        session_duration: float = None,
    ):
        super().__init__(ser, shared, species, valve_times, session_duration)
        self.ports = list(ports)
        self.led_on_time = led_on_time
        self.ITI_MIN = iti_min
        self.ITI_MAX = iti_max
        self.reward_prob = reward_prob

        self._presentation_history = []          # last 3 port choices
        self._reward_history = {p: [] for p in self.ports}  # last 3 outcomes per port
        self._forced_port = None

        self.results_df = pd.DataFrame(columns=[
            "trial_num",
            "port",
            "forced",
            "reward_triggered",
            "reward_prob_applied",  # True if reward was withheld by probability
            "trial_start",
            "trial_end",
            "rt",
            "iti",
            "valve_time",
        ])

    # ── Port selection ────────────────────────────────────────────────────────

    def _pick_port(self):
        if self._forced_port is not None:
            return self._forced_port, True

        # anti-3-in-a-row: if last 3 picks were the same, exclude that port
        excluded = set()
        if len(self._presentation_history) >= 3:
            last3 = self._presentation_history[-3:]
            if len(set(last3)) == 1:
                excluded.add(last3[0])

        choices = [p for p in self.ports if p not in excluded]
        if not choices:
            choices = list(self.ports)  # fallback (only one port available)

        return random.choice(choices), False

    def _update_anti_camping(self, port: str, rewarded: bool) -> None:
        self._reward_history[port].append(rewarded)
        if len(self._reward_history[port]) > 3:
            self._reward_history[port].pop(0)

        # Clear forced port once animal pokes it successfully
        if rewarded and port == self._forced_port:
            self._forced_port = None
            for p in self.ports:
                self._reward_history[p] = []
            return

        if self._forced_port is not None:
            return

        # Check for camping: one port always missed, another always hit
        always_miss = [
            p for p in self.ports
            if len(self._reward_history[p]) == 3 and not any(self._reward_history[p])
        ]
        always_hit = [
            p for p in self.ports
            if len(self._reward_history[p]) == 3 and all(self._reward_history[p])
        ]

        if always_miss and always_hit:
            self._forced_port = always_miss[0]
            print(f"[INFO] Anti-camping: forcing port {self._forced_port}")

    # ── Trial ─────────────────────────────────────────────────────────────────

    def _run_trial(self):
        port, was_forced = self._pick_port()

        self._presentation_history.append(port)
        if len(self._presentation_history) > 3:
            self._presentation_history.pop(0)

        trial_start = time.time()
        deadline = trial_start + self.led_on_time
        set_led(self.ser, port, True)
        print(f"Port {port} LED on (forced={was_forced})")

        poked = self._wait_for_poke(port, deadline=deadline)
        trial_end = time.time()
        set_led(self.ser, port, False)

        rewarded = False
        prob_withheld = False
        valve_time_used = np.nan
        rt = np.nan

        if poked:
            rt = trial_end - trial_start
            if random.random() < self.reward_prob:
                rewarded = True
                valve_time_used = self._deliver_reward(port)
                self.reward_count += 1
                print(f"Reward at port {port} (#{self.reward_count}, "
                      f"valve={valve_time_used:.3f} s)")
            else:
                prob_withheld = True
                print(f"Poked port {port} — reward withheld (prob={self.reward_prob:.2f})")
        else:
            print(f"Port {port} — no poke within {self.led_on_time:.1f} s")

        self._update_anti_camping(port, rewarded)

        iti = random.uniform(self.ITI_MIN, self.ITI_MAX)
        self._log(port, was_forced, rewarded, prob_withheld,
                  trial_start, trial_end, rt, iti, valve_time_used)
        self._run_iti(iti)

    def _log(self, port, forced, reward_triggered, reward_prob_applied,
             trial_start, trial_end, rt, iti, valve_time_used):
        self.results_df.loc[len(self.results_df)] = {
            "trial_num":           self.trial_counter,
            "port":                port,
            "forced":              forced,
            "reward_triggered":    reward_triggered,
            "reward_prob_applied": reward_prob_applied,
            "trial_start":         trial_start,
            "trial_end":           trial_end,
            "rt":                  rt,
            "iti":                 iti,
            "valve_time":          valve_time_used,
        }
        print(self.results_df.iloc[-1].to_dict())
