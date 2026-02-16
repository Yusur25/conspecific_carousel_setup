# gui.py
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
import numpy as np
import pandas as pd


class PerformanceGUI:
    def __init__(self):
        plt.ion()

        self.fig = plt.figure(figsize=(8, 8))
        gs = self.fig.add_gridspec(3, 1, height_ratios=[3, 1, 2], hspace=0.35)

        # --- Top: Reaction Time ---
        self.ax_rt = self.fig.add_subplot(gs[0])
        self.ax_rt.set_ylabel("Reaction time (s)")
        self.ax_rt.set_xlabel("Trial")
        self.ax_rt.grid(True)

        self.rt_scatter = self.ax_rt.scatter([], [])

        # --- Middle: Trial outcomes ---
        self.ax_outcome = self.fig.add_subplot(gs[1])
        self.ax_outcome.set_yticks([0, 1])
        self.ax_outcome.set_yticklabels(["A", "B"])
        self.ax_outcome.set_ylabel("Port")
        self.ax_outcome.set_xlabel("Trial")
        self.ax_outcome.set_ylim(-0.5, 1.5)
        self.ax_outcome.grid(True, axis="x")

        # --- Bottom: Block performance ---
        self.ax_block = self.fig.add_subplot(gs[2])
        self.ax_block.set_ylabel("Hit rate (%)")
        self.ax_block.set_xlabel("Trial block (10)")
        self.ax_block.set_ylim(0, 100)
        self.ax_block.grid(True, axis="y")

        self.fig.suptitle("Performance Summary", fontsize=14)

        plt.show(block=False)

    def update(self, results_df: pd.DataFrame, current_trial_port=None):
        if results_df.empty:
            return

        # =========================
        # Reaction time plot
        # =========================
        valid = results_df["reward_triggered"].notna()
        trials = results_df.loc[valid, "trial_num"]
        rts = results_df.loc[valid, "rt"]

        self.ax_rt.clear()
        self.ax_rt.plot(trials, rts, c="blue", alpha=0.7, linewidth=1)
        self.ax_rt.scatter(trials, rts, c="black", s=30)
        self.ax_rt.set_ylabel("Reaction time (s)")
        self.ax_rt.set_xlabel("Trial")
        self.ax_rt.grid(True)

        # =========================
        # Outcome dots
        # =========================
        self.ax_outcome.clear()
        self.ax_outcome.set_yticks([0, 1])
        self.ax_outcome.set_yticklabels(["A", "B"])
        self.ax_outcome.set_ylim(-0.5, 1.5)
        self.ax_outcome.set_ylabel("Port")
        self.ax_outcome.set_xlabel("Trial")
        self.ax_outcome.grid(True, axis="x")

        for _, row in results_df.iterrows():
            y = 0 if row["port"] == "A" else 1
            color = "green" if row["reward_triggered"] else "red"
            self.ax_outcome.scatter(row["trial_num"], y, c=color, s=40)

        # =========================
        # Block performance (10 trials)
        # =========================
        self.ax_block.clear()
        self.ax_block.set_ylabel("Hit rate (%)")
        self.ax_block.set_xlabel("Trial block (10)")
        self.ax_block.set_ylim(0, 100)
        self.ax_block.grid(True, axis="y")

        block_size = 10
        blocks = []
        labels = []

        for i, start in enumerate(range(0, len(results_df), block_size)):
            block = results_df.iloc[start:start + block_size]
            if len(block) == 0:
                continue

            pct = block["reward_triggered"].mean() * 100
            blocks.append(pct)

            t_start = block["trial_num"].iloc[0]
            t_end = block["trial_num"].iloc[-1]
            labels.append(f"{t_start}-{t_end}")

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

        # Circles
        self.circle_a = Circle((0.3, 0.5), 0.12, transform=self.ax.transAxes,
                               facecolor="red", edgecolor="black")
        self.circle_b = Circle((0.7, 0.5), 0.12, transform=self.ax.transAxes,
                               facecolor="red", edgecolor="black")

        self.ax.add_patch(self.circle_a)
        self.ax.add_patch(self.circle_b)

        # Labels
        self.ax.text(0.3, 0.8, "Sensor A", ha="center", transform=self.ax.transAxes)
        self.ax.text(0.7, 0.8, "Sensor B", ha="center", transform=self.ax.transAxes)

        # Optional timestamps
        self.text = self.ax.text(0.5, 0.1, "", ha="center",
                                 transform=self.ax.transAxes)

        plt.show(block=False)

    def update(self, snapshot):
        self.circle_a.set_facecolor(
            "green" if snapshot.A == "triggered" else "red")
        self.circle_b.set_facecolor(
            "green" if snapshot.B == "triggered" else "red")

        # Pulse effect
        self.circle_a.set_radius(0.14 if snapshot.A == "triggered" else 0.12)
        self.circle_b.set_radius(0.14 if snapshot.B == "triggered" else 0.12)

        a_age = snapshot.tA.strftime("%H:%M:%S.%f")[:-3] if snapshot.tA else "-"
        b_age = snapshot.tB.strftime("%H:%M:%S.%f")[:-3] if snapshot.tB else "-"

        self.text.set_text(f"A since: {a_age}    B since: {b_age}")

        self.fig.canvas.draw()
        self.fig.canvas.flush_events()

    def close(self):
        plt.ioff()
        plt.close(self.fig)