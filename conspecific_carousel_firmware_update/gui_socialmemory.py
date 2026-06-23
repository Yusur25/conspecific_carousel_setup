# gui_socialmemory.py — Performance and sensor GUIs for social memory sessions
#
# PerformanceGUI.update(df, conditioning_df=None):
#   conditioning_df=None → training mode (ClassicalConditioningSession)
#   conditioning_df provided → task mode (SocialMemoryTaskSession)
#
# SensorGUI: live sensor state (ports A, B, C, door proximity, table sensor)

import matplotlib.pyplot as plt
from matplotlib.patches import Circle
import numpy as np
import pandas as pd


# ── Helpers ───────────────────────────────────────────────────────────────────

PORT_COLORS = {"A": "#2196F3", "B": "#4CAF50", "C": "#FF9800"}


def _port_color(port):
    return PORT_COLORS.get(port, "gray")


# ── Performance GUI ───────────────────────────────────────────────────────────

class PerformanceGUI:

    def __init__(self, animal_name="Animal", mode="training"):
        plt.ion()
        self._mode = mode  # "training" or "task"
        self._animal_name = animal_name

        self._base_title = f"Social Memory — {animal_name} ({mode})"
        figsize = (10, 8) if mode == "training" else (10, 15)
        self.fig = plt.figure(figsize=figsize)
        self.fig.suptitle(self._base_title, fontsize=13)

        if mode == "training":
            self._build_training_axes()
            plt.tight_layout(rect=[0, 0, 1, 0.96])
        else:
            self._build_task_axes()
            self.fig.subplots_adjust(top=0.94, bottom=0.04, hspace=0.8)

        plt.show(block=False)

    # ── Axis builders ─────────────────────────────────────────────────────────

    def _build_training_axes(self):
        gs = self.fig.add_gridspec(3, 1, hspace=0.55)
        self.ax_rt      = self.fig.add_subplot(gs[0])
        self.ax_ports   = self.fig.add_subplot(gs[1])
        self.ax_block   = self.fig.add_subplot(gs[2])

        self.ax_rt.set_ylabel("RT (s)")
        self.ax_rt.set_xlabel("Trial")
        self.ax_rt.set_title("Reaction time (poke latency)", fontsize=10)
        self.ax_rt.grid(True)

        self.ax_ports.set_ylabel("Port")
        self.ax_ports.set_xlabel("Trial")
        self.ax_ports.set_title("Port choice  (green = rewarded, red = not rewarded)", fontsize=10)
        self.ax_ports.grid(True, axis="x")

        self.ax_block.set_ylabel("Hit rate (%)")
        self.ax_block.set_xlabel("Block (10 trials)")
        self.ax_block.set_title("Block performance", fontsize=10)
        self.ax_block.set_ylim(0, 100)
        self.ax_block.grid(True, axis="y")

    def _build_task_axes(self):
        gs = self.fig.add_gridspec(6, 1, hspace=0.8,
                                    height_ratios=[1, 1, 1, 1.3, 0.4, 1.1])
        self.ax_engage   = self.fig.add_subplot(gs[0])
        self.ax_sampling = self.fig.add_subplot(gs[1])
        self.ax_bouts    = self.fig.add_subplot(gs[2])
        self.ax_cc_rt    = self.fig.add_subplot(gs[3])
        self.ax_cc_miss  = self.fig.add_subplot(gs[4], sharex=self.ax_cc_rt)
        self.ax_cc_block = self.fig.add_subplot(gs[5])

        self.ax_engage.set_ylabel("Time (s)")
        self.ax_engage.set_xlabel("Presentation #")
        self.ax_engage.set_title(
            "Time to engage stimulus  (door open → table sensor triggered; blue = S1, orange = S2)",
            fontsize=10)
        self.ax_engage.grid(True, axis="y")

        self.ax_sampling.set_ylabel("Sampling time (s)")
        self.ax_sampling.set_xlabel("Presentation #")
        self.ax_sampling.set_title("Stimulus sampling time  (blue = S1, orange = S2)", fontsize=10)
        self.ax_sampling.grid(True, axis="y")

        self.ax_bouts.set_ylabel("Bouts")
        self.ax_bouts.set_xlabel("Presentation #")
        self.ax_bouts.set_title("Number of sampling bouts  (blue = S1, orange = S2)", fontsize=10)
        self.ax_bouts.grid(True, axis="y")

        self.ax_cc_rt.set_ylabel("RT (s)")
        self.ax_cc_rt.set_title("Conditioning RT", fontsize=10)
        self.ax_cc_rt.grid(True)
        self.ax_cc_rt.tick_params(labelbottom=False)

        self.ax_cc_miss.set_yticks([])
        self.ax_cc_miss.set_ylabel("Miss", fontsize=8)
        self.ax_cc_miss.set_xlabel("CC trial #")
        self.ax_cc_miss.grid(True, axis="x")

        self.ax_cc_block.set_ylabel("Hit rate (%)")
        self.ax_cc_block.set_xlabel("CC block (10 trials)")
        self.ax_cc_block.set_title("Conditioning block performance", fontsize=10)
        self.ax_cc_block.set_ylim(0, 100)
        self.ax_cc_block.grid(True, axis="y")

    # ── Update ────────────────────────────────────────────────────────────────

    def update(self, df: pd.DataFrame, conditioning_df: pd.DataFrame = None):
        if df is None or df.empty:
            self.fig.canvas.draw()
            self.fig.canvas.flush_events()
            return

        # Training mode: update trial counter in suptitle
        if conditioning_df is None and "trial_num" in df.columns and not df["trial_num"].isna().all():
            trial = int(df["trial_num"].max()) + 1
            self.fig.suptitle(f"{self._base_title}  |  Trial: {trial}", fontsize=13)

        if conditioning_df is None:
            self._update_training(df)
        else:
            self._update_task(df, conditioning_df)

        self.fig.canvas.draw()
        self.fig.canvas.flush_events()

    # ── Training mode ─────────────────────────────────────────────────────────

    def _update_training(self, df: pd.DataFrame):
        ports_present = df["port"].unique().tolist()
        port_to_y = {p: i for i, p in enumerate(sorted(ports_present))}

        # RT scatter
        self.ax_rt.clear()
        valid = df["rt"].notna()
        if valid.any():
            for port in ports_present:
                mask = valid & (df["port"] == port)
                self.ax_rt.scatter(
                    df.loc[mask, "trial_num"], df.loc[mask, "rt"],
                    color=_port_color(port), label=f"Port {port}", s=25, zorder=3
                )
            self.ax_rt.plot(
                df.loc[valid, "trial_num"], df.loc[valid, "rt"],
                color="black", linewidth=0.8, alpha=0.4
            )
        self.ax_rt.set_ylabel("RT (s)")
        self.ax_rt.set_xlabel("Trial")
        self.ax_rt.set_title("Reaction time (poke latency)", fontsize=10)
        self.ax_rt.legend(fontsize=8, loc="upper right")
        self.ax_rt.grid(True)

        # Port choice sequence
        self.ax_ports.clear()
        for _, row in df.iterrows():
            y = port_to_y.get(row["port"], 0)
            color = "green" if row["reward_triggered"] else "red"
            self.ax_ports.scatter(row["trial_num"], y, c=color, s=30, zorder=3)
        self.ax_ports.set_yticks(list(port_to_y.values()))
        self.ax_ports.set_yticklabels(list(port_to_y.keys()))
        self.ax_ports.set_ylabel("Port")
        self.ax_ports.set_xlabel("Trial")
        self.ax_ports.set_title("Port choice  (green = rewarded, red = not rewarded)", fontsize=10)
        self.ax_ports.set_ylim(-0.5, max(port_to_y.values()) + 0.5)
        self.ax_ports.grid(True, axis="x")

        # Block hit rate
        self._draw_block_bars(self.ax_block, df, "reward_triggered")

    # ── Task mode ─────────────────────────────────────────────────────────────

    def _update_task(self, presentations: pd.DataFrame, conditioning: pd.DataFrame):
        self._draw_presentation_bar(
            self.ax_engage, presentations, "time_to_engage",
            "Time (s)",
            "Time to engage stimulus  (door open → table sensor triggered; blue = S1, orange = S2)")
        self._draw_presentation_bar(
            self.ax_sampling, presentations, "sampling_time",
            "Sampling time (s)",
            "Stimulus sampling time  (blue = S1, orange = S2)",
            show_labels=True)
        self._draw_presentation_bar(
            self.ax_bouts, presentations, "bout_count",
            "Bouts",
            "Number of sampling bouts  (blue = S1, orange = S2)")

        if conditioning is None or conditioning.empty:
            self.fig.canvas.draw()
            self.fig.canvas.flush_events()
            return

        valid = conditioning["rt"].notna()
        ports_present = sorted(conditioning["port"].dropna().unique().tolist())

        # CC RT scatter, colored by port
        self.ax_cc_rt.clear()
        for port in ports_present:
            mask = valid & (conditioning["port"] == port)
            if mask.any():
                x = [i + 1 for i, v in enumerate(mask) if v]
                self.ax_cc_rt.scatter(
                    x, conditioning.loc[mask, "rt"],
                    color=_port_color(port), label=f"Port {port}", s=25, zorder=3
                )
        self.ax_cc_rt.set_ylabel("RT (s)")
        self.ax_cc_rt.set_title("Conditioning RT", fontsize=10)
        self.ax_cc_rt.grid(True)
        self.ax_cc_rt.tick_params(labelbottom=False)
        if ports_present:
            self.ax_cc_rt.legend(fontsize=8, loc="upper right")

        # CC misses — narrow row, same x-axis as the RT plot above
        self.ax_cc_miss.clear()
        miss = ~valid
        for port in ports_present:
            mask = miss & (conditioning["port"] == port)
            if mask.any():
                x = [i + 1 for i, v in enumerate(mask) if v]
                self.ax_cc_miss.scatter(
                    x, [0] * len(x), color=_port_color(port), marker="x", s=30, zorder=3
                )
        self.ax_cc_miss.set_yticks([])
        self.ax_cc_miss.set_ylabel("Miss", fontsize=8)
        self.ax_cc_miss.set_xlabel("CC trial #")
        self.ax_cc_miss.grid(True, axis="x")

        # CC block hit rate
        self._draw_block_bars(self.ax_cc_block, conditioning, "reward_triggered")

    # ── Shared helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _draw_presentation_bar(ax, presentations: pd.DataFrame, col: str,
                                ylabel: str, title: str, show_labels: bool = False):
        ax.clear()
        if not presentations.empty:
            colors = [
                "#2196F3" if str(p).startswith("S1") else "#FF9800"
                for p in presentations["period"]
            ]
            ax.bar(presentations["presentation_num"], presentations[col],
                   color=colors, edgecolor="black")
            if show_labels:
                for _, row in presentations.iterrows():
                    ax.text(
                        row["presentation_num"], row[col] + 0.05,
                        row["period"], ha="center", fontsize=7, rotation=45
                    )
        ax.set_ylabel(ylabel)
        ax.set_xlabel("Presentation #")
        ax.set_title(title, fontsize=10)
        ax.grid(True, axis="y")

    @staticmethod
    def _draw_block_bars(ax, df: pd.DataFrame, col: str):
        ax.clear()
        block_size = 10
        blocks, labels = [], []
        for start in range(0, len(df), block_size):
            block = df.iloc[start : start + block_size]
            if block.empty:
                continue
            pct = block[col].mean() * 100
            blocks.append(pct)
            labels.append(f"{start + 1}–{min(start + block_size, len(df))}")
        x = np.arange(len(blocks))
        ax.bar(x, blocks, width=0.6)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=0, fontsize=8)
        ax.set_ylim(0, 100)
        ax.set_ylabel("Hit rate (%)")
        ax.set_xlabel("Block (10 trials)")
        ax.grid(True, axis="y")

    # ── Close ─────────────────────────────────────────────────────────────────

    def close(self, save_path=None):
        if save_path is not None:
            self.fig.savefig(save_path, dpi=300, bbox_inches="tight")
            print(f"[INFO] Performance figure saved: {save_path}")
        plt.ioff()
        plt.close(self.fig)


# ── Sensor GUI ────────────────────────────────────────────────────────────────

class SensorGUI:

    def __init__(self):
        plt.ion()
        self.fig, self.ax = plt.subplots(figsize=(4, 2.2))
        self.fig.canvas.manager.set_window_title("Sensor State")
        self.ax.axis("off")

        def _circle(cx, cy, label, label_cy):
            c = Circle((cx, cy), 0.10, transform=self.ax.transAxes,
                        facecolor="red", edgecolor="black")
            self.ax.add_patch(c)
            self.ax.text(cx, label_cy, label,
                          ha="center", fontsize=9, transform=self.ax.transAxes)
            return c

        self.circle_a    = _circle(0.2, 0.60, "Port A", 0.74)
        self.circle_b    = _circle(0.5, 0.60, "Port B", 0.74)
        self.circle_c    = _circle(0.8, 0.60, "Port C", 0.74)
        self.circle_door = _circle(0.3, 0.22, "Door",   0.09)
        self.circle_tbl  = _circle(0.7, 0.22, "Table",  0.09)

        self.text_a    = self.ax.text(0.2, 0.50, "", ha="center",
                                      fontsize=7, transform=self.ax.transAxes)
        self.text_b    = self.ax.text(0.5, 0.50, "", ha="center",
                                      fontsize=7, transform=self.ax.transAxes)
        self.text_c    = self.ax.text(0.8, 0.50, "", ha="center",
                                      fontsize=7, transform=self.ax.transAxes)
        self.text_door = self.ax.text(0.3, 0.02, "", ha="center",
                                      fontsize=7, transform=self.ax.transAxes)
        self.text_tbl  = self.ax.text(0.7, 0.02, "", ha="center",
                                      fontsize=7, transform=self.ax.transAxes)

        plt.show(block=False)

    def update(self, snapshot):
        def _ts(t):
            return t.strftime("%H:%M:%S") if t else "–"

        self.circle_a.set_facecolor(
            "green" if snapshot.A == "triggered" else "red")
        self.circle_b.set_facecolor(
            "green" if snapshot.B == "triggered" else "red")
        self.circle_c.set_facecolor(
            "green" if snapshot.C == "triggered" else "red")
        self.circle_door.set_facecolor(
            "green" if snapshot.doorsensor == "triggered" else "red")
        self.circle_tbl.set_facecolor(
            "green" if snapshot.table == "triggered" else "red")

        self.circle_a.set_radius(0.12 if snapshot.A == "triggered" else 0.10)
        self.circle_b.set_radius(0.12 if snapshot.B == "triggered" else 0.10)
        self.circle_c.set_radius(0.12 if snapshot.C == "triggered" else 0.10)

        self.text_a.set_text(_ts(snapshot.tA))
        self.text_b.set_text(_ts(snapshot.tB))
        self.text_c.set_text(_ts(snapshot.tC))
        self.text_door.set_text(_ts(snapshot.tDoorsensor))
        self.text_tbl.set_text(_ts(snapshot.tTable))

        self.fig.canvas.draw()
        self.fig.canvas.flush_events()

    def close(self):
        plt.ioff()
        plt.close(self.fig)
