# gui_socialreward.py — unified sensor and performance GUIs for social reward
# Used by both rat and mouse sessions; works across all phases and the task.

import matplotlib.pyplot as plt
from matplotlib.patches import Circle
import numpy as np
import pandas as pd


class PerformanceGUI:
    def __init__(self, animal_name="Animal", phase_selection=""):
        plt.ion()

        self.fig = plt.figure(figsize=(8, 10))
        gs = self.fig.add_gridspec(6, 1, height_ratios=[2, 2, 2, 1, 1, 1], hspace=0.7)

        # RT — port C reaction time
        self.ax_rt = self.fig.add_subplot(gs[0])
        self.ax_rt.set_ylabel("Reaction time (s)\n(port C)")
        self.ax_rt.set_xlabel("Trial")
        self.ax_rt.grid(True)
        self.rt_scatter = self.ax_rt.scatter([], [])

        # RT — door open (LED A → poke A)
        self.ax_rtdooropen = self.fig.add_subplot(gs[1])
        self.ax_rtdooropen.set_ylabel("Reaction time (s)\n(door open)")
        self.ax_rtdooropen.set_xlabel("Trial")
        self.ax_rtdooropen.grid(True)
        self.rtdooropen_scatter = self.ax_rtdooropen.scatter([], [])

        # RT — table hold (door open → sensory minimum met)
        self.ax_rttablehold = self.fig.add_subplot(gs[2])
        self.ax_rttablehold.set_ylabel("Reaction time (s)\n(sensory minimum)")
        self.ax_rttablehold.set_xlabel("Trial")
        self.ax_rttablehold.grid(True)
        self.rttablehold_scatter = self.ax_rttablehold.scatter([], [])

        # Trial outcomes
        self.ax_outcome = self.fig.add_subplot(gs[3])
        self.ax_outcome.set_yticks([0, 1, 2])
        self.ax_outcome.set_yticklabels(["A", "B", "C"])
        self.ax_outcome.set_ylabel("Port")
        self.ax_outcome.set_xlabel("Trial")
        self.ax_outcome.set_ylim(-0.5, 2.5)
        self.ax_outcome.grid(True, axis="x")

        # Sampling duration
        self.ax_sampling = self.fig.add_subplot(gs[4])
        self.ax_sampling.set_ylabel("Sampling (s)")
        self.ax_sampling.set_xlabel("Trial")
        self.ax_sampling.grid(True, axis="y")

        # Block performance
        self.ax_block = self.fig.add_subplot(gs[5])
        self.ax_block.set_ylabel("Performance (%)")
        self.ax_block.set_xlabel("Trial block (10)")
        self.ax_block.set_ylim(0, 100)
        self.ax_block.grid(True, axis="y")

        title = f"Performance Summary: {animal_name}"
        if phase_selection:
            title += f" | Phase {phase_selection}"
        self.fig.suptitle(title, fontsize=14)

        plt.show(block=False)

    def update(self, results_df: pd.DataFrame, current_trial_port=None):
        if results_df.empty:
            return

        xmin = results_df["trial_num"].min() - 0.5
        xmax = results_df["trial_num"].max() + 0.5

        # ── RT: port C ───────────────────────────────────────────────────────
        if "rt" in results_df.columns:
            valid = results_df["rt"].notna()
            trials = results_df.loc[valid, "trial_num"]
            rts    = results_df.loc[valid, "rt"]

            colors = []
            if "outcome" in results_df.columns:
                for outcome in results_df.loc[valid, "outcome"]:
                    colors.append(_outcome_color(outcome))
            else:
                colors = ["blue"] * len(trials)

            self.ax_rt.clear()
            self.ax_rt.grid(True)
            self.ax_rt.plot(trials, rts, c="black", linewidth=1, alpha=0.5)
            self.ax_rt.scatter(trials, rts, c=colors, s=30)
            self.ax_rt.set_xlim(xmin, xmax)
            self.ax_rt.set_ylabel("Reaction time (s)\n(port C)")
            self.ax_rt.set_xlabel("Trial")

        # ── RT: door open ─────────────────────────────────────────────────────
        if "rt_dooropen" in results_df.columns:
            valid = results_df["rt_dooropen"].notna()
            trials = results_df.loc[valid, "trial_num"]
            rts    = results_df.loc[valid, "rt_dooropen"]

            self.ax_rtdooropen.clear()
            self.ax_rtdooropen.grid(True)
            self.ax_rtdooropen.plot(trials, rts, c="black", linewidth=1, alpha=0.8)
            self.ax_rtdooropen.scatter(trials, rts, c="black", s=20)
            self.ax_rtdooropen.set_xlim(xmin, xmax)
            self.ax_rtdooropen.set_ylabel("Reaction time (s)\n(door open)")
            self.ax_rtdooropen.set_xlabel("Trial")
        else:
            self.ax_rtdooropen.clear()
            self.ax_rtdooropen.set_ylabel("Reaction time (s)\n(door open)")
            self.ax_rtdooropen.set_xlabel("Trial")

        # ── RT: sensory minimum ───────────────────────────────────────────────
        if "rt_tablehold" in results_df.columns:
            valid = results_df["rt_tablehold"].notna()
            trials = results_df.loc[valid, "trial_num"]
            rts    = results_df.loc[valid, "rt_tablehold"]

            self.ax_rttablehold.clear()
            self.ax_rttablehold.grid(True)
            self.ax_rttablehold.plot(trials, rts, c="black", linewidth=1, alpha=0.8)
            self.ax_rttablehold.scatter(trials, rts, c="black", s=20)
            self.ax_rttablehold.set_xlim(xmin, xmax)
            self.ax_rttablehold.set_ylabel("Reaction time (s)\n(sensory minimum)")
            self.ax_rttablehold.set_xlabel("Trial")
        else:
            self.ax_rttablehold.clear()
            self.ax_rttablehold.set_ylabel("Reaction time (s)\n(sensory minimum)")
            self.ax_rttablehold.set_xlabel("Trial")

        # ── Outcome dots ──────────────────────────────────────────────────────
        self.ax_outcome.clear()

        if "reward_available" in results_df.columns:
            # Task mode: rewarded vs unrewarded stimulus
            self.ax_outcome.set_yticks([0.25, 1.75])
            self.ax_outcome.set_yticklabels(["Unrewarded", "Rewarded"])
            self.ax_outcome.set_ylabel("Stimulus")
            for _, row in results_df.iterrows():
                y = 1.75 if row["reward_available"] else 0.25
                self.ax_outcome.scatter(
                    row["trial_num"], y,
                    c=_outcome_color(row.get("outcome")), s=40
                )
        elif "reward_triggered" in results_df.columns:
            # Training mode: port A / B / C
            self.ax_outcome.set_yticks([0, 1, 2])
            self.ax_outcome.set_yticklabels(["A", "B", "C"])
            self.ax_outcome.set_ylabel("Port")
            for _, row in results_df.iterrows():
                port = row.get("port", "C")
                y = 0 if port == "A" else 1 if port == "B" else 2
                color = "green" if row["reward_triggered"] else "red"
                self.ax_outcome.scatter(row["trial_num"], y, c=color, s=40)

        self.ax_outcome.set_ylim(-0.5, 2.5)
        self.ax_outcome.set_xlim(xmin, xmax)
        self.ax_outcome.set_xlabel("Trial")
        self.ax_outcome.grid(True, axis="x")

        # ── Sampling duration ─────────────────────────────────────────────────
        if "sampling_time" in results_df.columns:
            if not hasattr(self, "_last_sampling_n"):
                self._last_sampling_n = -1

            all_trials = results_df["trial_num"].unique()
            sampling   = results_df.set_index("trial_num")["sampling_time"]
            n_sampling = sampling.notna().sum()

            if n_sampling != self._last_sampling_n:
                self._last_sampling_n = n_sampling
                y = [sampling.get(t, 0) or 0 for t in all_trials]

                self.ax_sampling.clear()
                self.ax_sampling.bar(all_trials, y, color="gold", edgecolor="black")
                self.ax_sampling.set_ylabel("Sampling time (s)")
                self.ax_sampling.set_xlim(xmin, xmax)
                self.ax_sampling.set_xlabel("Trial")
                self.ax_sampling.grid(True, axis="y")
        else:
            self.ax_sampling.clear()
            self.ax_sampling.set_ylabel("Sampling time (s)")
            self.ax_sampling.set_xlabel("Trial")

        # ── Block performance ─────────────────────────────────────────────────
        self.ax_block.clear()
        self.ax_block.set_ylabel("Performance (%)")
        self.ax_block.set_xlabel("Trial block (10)")
        self.ax_block.set_ylim(0, 100)
        self.ax_block.grid(True, axis="y")
        self.ax_block.axhline(50, color="black", linestyle="-",  linewidth=1, alpha=0.4)
        self.ax_block.axhline(75, color="black", linestyle="--", linewidth=1, alpha=0.4)

        block_size = 10
        blocks, labels = [], []
        for start in range(0, len(results_df), block_size):
            block = results_df.iloc[start:start + block_size]
            if len(block) == 0:
                continue
            if "outcome" in results_df.columns:
                pct = block["outcome"].isin(["hit", "correct_rejection"]).mean() * 100
            elif "reward_triggered" in results_df.columns:
                pct = block["reward_triggered"].mean() * 100
            else:
                continue
            blocks.append(pct)
            labels.append(f"{block['trial_num'].iloc[0]}-{block['trial_num'].iloc[-1]}")

        x = np.arange(len(blocks))
        self.ax_block.bar(x, blocks, width=0.6)
        self.ax_block.set_xticks(x)
        self.ax_block.set_xticklabels(labels, rotation=0)

        self.fig.canvas.draw()
        self.fig.canvas.flush_events()

    def close(self, save_path=None):
        if save_path is not None:
            self.fig.savefig(save_path, dpi=300, bbox_inches="tight")
            print(f"[INFO] Performance figure saved: {save_path}")
        plt.ioff()
        plt.close(self.fig)


class SensorGUI:
    def __init__(self):
        plt.ion()
        self.fig, self.ax = plt.subplots(figsize=(4, 2))
        self.ax.axis("off")

        self.circle_a = Circle((0.3, 0.5), 0.12, transform=self.ax.transAxes,
                               facecolor="red", edgecolor="black")
        self.circle_b = Circle((0.7, 0.5), 0.12, transform=self.ax.transAxes,
                               facecolor="red", edgecolor="black")
        self.circle_c = Circle((0.5, 0.8), 0.12, transform=self.ax.transAxes,
                               facecolor="red", edgecolor="black")
        self.circle_door = Circle((0.3, 0.2), 0.12, transform=self.ax.transAxes,
                                  facecolor="red", edgecolor="black")
        self.circle_table = Circle((0.7, 0.2), 0.12, transform=self.ax.transAxes,
                                   facecolor="red", edgecolor="black")

        for patch in (self.circle_a, self.circle_b, self.circle_c,
                      self.circle_door, self.circle_table):
            self.ax.add_patch(patch)

        self.ax.text(0.3, 0.65, "Sensor A", ha="center", fontsize=9, transform=self.ax.transAxes)
        self.ax.text(0.7, 0.65, "Sensor B", ha="center", fontsize=9, transform=self.ax.transAxes)
        self.ax.text(0.5, 0.92, "Sensor C", ha="center", fontsize=9, transform=self.ax.transAxes)
        self.ax.text(0.3, 0.04, "Door",     ha="center", fontsize=9, transform=self.ax.transAxes)
        self.ax.text(0.7, 0.04, "Table",    ha="center", fontsize=9, transform=self.ax.transAxes)

        self.text_a     = self.ax.text(0.3, 0.56, "", ha="center", fontsize=7, transform=self.ax.transAxes)
        self.text_b     = self.ax.text(0.7, 0.56, "", ha="center", fontsize=7, transform=self.ax.transAxes)
        self.text_c     = self.ax.text(0.5, 0.84, "", ha="center", fontsize=7, transform=self.ax.transAxes)
        self.text_door  = self.ax.text(0.3, 0.01, "", ha="center", fontsize=7, transform=self.ax.transAxes)
        self.text_table = self.ax.text(0.7, 0.01, "", ha="center", fontsize=7, transform=self.ax.transAxes)

        plt.show(block=False)

    def update(self, snapshot):
        self.circle_a.set_facecolor("green" if snapshot.A == "triggered" else "red")
        self.circle_b.set_facecolor("green" if snapshot.B == "triggered" else "red")
        self.circle_c.set_facecolor("green" if snapshot.C == "triggered" else "red")
        # doorsensor is the proximity sensor (triggered/cleared), not the door state string
        self.circle_door.set_facecolor("green" if snapshot.doorsensor == "triggered" else "red")
        self.circle_table.set_facecolor("green" if snapshot.table == "triggered" else "red")

        self.circle_a.set_radius(0.14 if snapshot.A == "triggered" else 0.12)
        self.circle_b.set_radius(0.14 if snapshot.B == "triggered" else 0.12)
        self.circle_c.set_radius(0.14 if snapshot.C == "triggered" else 0.12)

        self.text_a.set_text(    snapshot.tA.strftime("%H:%M:%S.%f")[:-3]          if snapshot.tA          else "-")
        self.text_b.set_text(    snapshot.tB.strftime("%H:%M:%S.%f")[:-3]          if snapshot.tB          else "-")
        self.text_c.set_text(    snapshot.tC.strftime("%H:%M:%S.%f")[:-3]          if snapshot.tC          else "-")
        self.text_door.set_text( snapshot.tDoorsensor.strftime("%H:%M:%S.%f")[:-3] if snapshot.tDoorsensor else "-")
        self.text_table.set_text(snapshot.tTable.strftime("%H:%M:%S.%f")[:-3]      if snapshot.tTable      else "-")

        self.fig.canvas.draw()
        self.fig.canvas.flush_events()

    def close(self):
        plt.ioff()
        plt.close(self.fig)


# ── Internal helper ───────────────────────────────────────────────────────────

def _outcome_color(outcome):
    return {
        "hit":               "green",
        "rewarded":          "green",
        "false_alarm":       "red",
        "miss":              "orange",
        "correct_rejection": "blue",
    }.get(outcome, "gray")
