# setup_gui.py — Pre-session configuration dialog
import tkinter as tk
from tkinter import ttk, messagebox

SPECIES_DEFAULTS = {
    "rat": {
        "valve_time": 0.30,
        "session_duration_s": 3600,
        "session_duration_trials": "",
        "sensory_minimum": 0.100,          # phases 2 and 3a
        "phase4_sensory_min": 2.0,
        "phase4_decision_window": 5.0,
        "phase3b_thresholds": [15, 30, 50],
        "phase3b_holds": [0.5, 1.0, 1.5, 2.0],
        "task_sensory_min": 2.0,
        "task_decision_window": 10.0,
    },
    "mouse": {
        "valve_time": 0.20,
        "session_duration_s": 3600,
        "session_duration_trials": "",
        "sensory_minimum": 0.100,          # phases 2 and 3a
        "phase4_sensory_min": 1.5,
        "phase4_decision_window": 5.0,
        "phase3b_thresholds": [15, 30],
        "phase3b_holds": [0.5, 1.0, 1.5],
        "task_sensory_min": 2.0,
        "task_decision_window": 5.0,
    },
}


class SetupDialog:
    """Tkinter dialog that collects session parameters and returns them as a dict."""

    def __init__(self):
        self.result = None
        self.root = tk.Tk()
        self.root.title("Social Reward Task — Session Setup")
        self.root.resizable(False, False)

        self._species_var = tk.StringVar(value="rat")
        self._vars = {}
        self._timing_vars = {}
        self._phase3b_threshold_vars = []
        self._phase3b_hold_vars = []
        self._sm_frame = None    # sensory minimum only (phases 2, 3a)
        self._p4_frame = None    # phase 4
        self._p3b_frame = None   # phase 3b
        self._task_frame = None  # task

        self._build_ui()
        self._on_species_change()
        self._on_phase_change()

    def _row(self, parent, label_text, var, row, width=20):
        pad = {"padx": 8, "pady": 3}
        tk.Label(parent, text=label_text, anchor="w").grid(
            row=row, column=0, sticky="w", **pad)
        tk.Entry(parent, textvariable=var, width=width).grid(
            row=row, column=1, sticky="w", **pad)

    def _build_ui(self):
        root = self.root
        pad = {"padx": 8, "pady": 3}

        # ── Header ────────────────────────────────────────────────────────────
        tk.Label(root, text="Social Reward Task — Session Setup",
                 font=("Arial", 13, "bold")).grid(
            row=0, column=0, columnspan=4, pady=(12, 4))

        # ── Species ───────────────────────────────────────────────────────────
        tk.Label(root, text="Species:", anchor="w").grid(
            row=1, column=0, sticky="w", **pad)
        sf = tk.Frame(root)
        sf.grid(row=1, column=1, columnspan=3, sticky="w", **pad)
        for species in ("Rat", "Mouse"):
            tk.Radiobutton(sf, text=species,
                           variable=self._species_var, value=species.lower(),
                           command=self._on_species_change).pack(side="left", padx=4)

        ttk.Separator(root, orient="horizontal").grid(
            row=2, column=0, columnspan=4, sticky="ew", padx=8, pady=6)

        # ── Core session fields ───────────────────────────────────────────────
        core_fields = [
            ("Animal ID:",   "animal",    ""),
            ("Session #:",   "session_n", "1"),
            ("Serial Port:", "port",      "COM3"),
            ("Baud Rate:",   "baud",      "115200"),
        ]
        for i, (label, key, default) in enumerate(core_fields):
            var = tk.StringVar(value=default)
            self._vars[key] = var
            self._row(root, label, var, row=3 + i)

        # Phase dropdown
        tk.Label(root, text="Phase:", anchor="w").grid(
            row=7, column=0, sticky="w", **pad)
        self._vars["phase"] = tk.StringVar(value="1")
        phase_cb = ttk.Combobox(root, textvariable=self._vars["phase"],
                                values=["1", "2", "3a", "3b", "4", "task"],
                                state="readonly", width=10)
        phase_cb.grid(row=7, column=1, sticky="w", **pad)
        phase_cb.bind("<<ComboboxSelected>>", lambda _e: self._on_phase_change())

        ttk.Separator(root, orient="horizontal").grid(
            row=8, column=0, columnspan=4, sticky="ew", padx=8, pady=6)

        # ── Timing parameters (always visible) ───────────────────────────────
        timing_frame = tk.LabelFrame(root, text="Timing Parameters", padx=8, pady=4)
        timing_frame.grid(row=9, column=0, columnspan=4, sticky="ew", padx=8, pady=4)

        # Valve time
        var = tk.StringVar()
        self._timing_vars["valve_time"] = var
        self._row(timing_frame, "Valve Time (s):", var, row=0)

        # Session duration — time OR trials
        tk.Label(timing_frame, text="Session Duration:", anchor="w").grid(
            row=1, column=0, sticky="w", padx=8, pady=3)

        dur_frame = tk.Frame(timing_frame)
        dur_frame.grid(row=1, column=1, sticky="w", pady=3)

        self._timing_vars["session_duration_s"] = tk.StringVar()
        self._timing_vars["session_duration_trials"] = tk.StringVar()

        tk.Entry(dur_frame, textvariable=self._timing_vars["session_duration_s"],
                 width=7).pack(side="left")
        tk.Label(dur_frame, text=" s  OR ").pack(side="left")
        tk.Entry(dur_frame, textvariable=self._timing_vars["session_duration_trials"],
                 width=5).pack(side="left")
        tk.Label(dur_frame, text=" trials  (first reached ends session)").pack(side="left")

        # ── Sensory Minimum only (phases 2 and 3a) ───────────────────────────
        self._sm_frame = tk.LabelFrame(root, text="Phase Parameters", padx=8, pady=4)
        self._sm_frame.grid(row=10, column=0, columnspan=4, sticky="ew", padx=8, pady=4)

        var = tk.StringVar()
        self._timing_vars["sensory_minimum"] = var
        self._row(self._sm_frame, "Sensory Minimum (s):", var, row=0)

        # ── Phase 4 parameters ────────────────────────────────────────────────
        self._p4_frame = tk.LabelFrame(root, text="Phase Parameters", padx=8, pady=4)
        self._p4_frame.grid(row=10, column=0, columnspan=4, sticky="ew", padx=8, pady=4)

        for i, (label, key) in enumerate([
            ("Sensory Minimum (s):", "phase4_sensory_min"),
            ("Decision Window (s):", "phase4_decision_window"),
        ]):
            var = tk.StringVar()
            self._timing_vars[key] = var
            self._row(self._p4_frame, label, var, row=i)

        # ── Task parameters ───────────────────────────────────────────────────
        self._task_frame = tk.LabelFrame(root, text="Phase Parameters", padx=8, pady=4)
        self._task_frame.grid(row=10, column=0, columnspan=4, sticky="ew", padx=8, pady=4)

        for i, (label, key) in enumerate([
            ("Sensory Minimum (s):", "task_sensory_min"),
            ("Decision Window (s):", "task_decision_window"),
        ]):
            var = tk.StringVar()
            self._timing_vars[key] = var
            self._row(self._task_frame, label, var, row=i)

        # ── Phase 3b gradual sensory minimum ─────────────────────────────────
        self._p3b_frame = tk.LabelFrame(
            root,
            text="Phase 3b Gradual Sensory Minimum  (leave blank to remove a step)",
            padx=8, pady=4)
        self._p3b_frame.grid(row=10, column=0, columnspan=4, sticky="ew", padx=8, pady=4)

        tk.Label(self._p3b_frame, text="Trial threshold (<)", anchor="w").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=4)
        tk.Label(self._p3b_frame, text="Sensory Min (s)", anchor="w").grid(
            row=0, column=2, sticky="w", padx=4)

        self._phase3b_threshold_vars = [tk.StringVar() for _ in range(3)]
        self._phase3b_hold_vars = [tk.StringVar() for _ in range(4)]

        for i in range(3):
            tk.Label(self._p3b_frame, text=f"Step {i+1}:").grid(
                row=1 + i, column=0, sticky="e", padx=4, pady=2)
            tk.Entry(self._p3b_frame, textvariable=self._phase3b_threshold_vars[i],
                     width=6).grid(row=1 + i, column=1, sticky="w", padx=4, pady=2)
            tk.Entry(self._p3b_frame, textvariable=self._phase3b_hold_vars[i],
                     width=6).grid(row=1 + i, column=2, sticky="w", padx=4, pady=2)

        tk.Label(self._p3b_frame, text="Final (≥ last threshold):").grid(
            row=4, column=0, columnspan=2, sticky="e", padx=4, pady=2)
        tk.Entry(self._p3b_frame, textvariable=self._phase3b_hold_vars[3],
                 width=6).grid(row=4, column=2, sticky="w", padx=4, pady=2)

        # ── Notes ─────────────────────────────────────────────────────────────
        ttk.Separator(root, orient="horizontal").grid(
            row=11, column=0, columnspan=4, sticky="ew", padx=8, pady=6)

        tk.Label(root, text="Notes:", anchor="w").grid(
            row=12, column=0, sticky="nw", **pad)
        self._notes = tk.Text(root, width=36, height=3, font=("Arial", 9))
        self._notes.grid(row=12, column=1, columnspan=3, sticky="ew", **pad)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_frame = tk.Frame(root)
        btn_frame.grid(row=13, column=0, columnspan=4, pady=(8, 14))
        tk.Button(btn_frame, text="Start Session", bg="#4CAF50", fg="white",
                  font=("Arial", 11, "bold"), width=18,
                  command=self._on_start).pack(side="left", padx=8)
        tk.Button(btn_frame, text="Cancel", width=10,
                  command=self.root.destroy).pack(side="left", padx=8)

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _on_species_change(self):
        species = self._species_var.get()
        d = SPECIES_DEFAULTS[species]
        self._timing_vars["valve_time"].set(str(d["valve_time"]))
        self._timing_vars["session_duration_s"].set(str(d["session_duration_s"]))
        self._timing_vars["session_duration_trials"].set(str(d["session_duration_trials"]))
        self._timing_vars["sensory_minimum"].set(str(d["sensory_minimum"]))
        self._timing_vars["phase4_sensory_min"].set(str(d["phase4_sensory_min"]))
        self._timing_vars["phase4_decision_window"].set(str(d["phase4_decision_window"]))
        self._timing_vars["task_sensory_min"].set(str(d["task_sensory_min"]))
        self._timing_vars["task_decision_window"].set(str(d["task_decision_window"]))

        thresholds = d["phase3b_thresholds"]
        holds = d["phase3b_holds"]
        for i in range(3):
            self._phase3b_threshold_vars[i].set(
                str(thresholds[i]) if i < len(thresholds) else "")
        for i in range(4):
            self._phase3b_hold_vars[i].set(
                str(holds[i]) if i < len(holds) else "")

    def _on_phase_change(self):
        phase = self._vars["phase"].get()
        for frame in (self._sm_frame, self._p4_frame, self._task_frame, self._p3b_frame):
            frame.grid_remove()
        if phase in ("2", "3a"):
            self._sm_frame.grid()
        elif phase == "4":
            self._p4_frame.grid()
        elif phase == "task":
            self._task_frame.grid()
        elif phase == "3b":
            self._p3b_frame.grid()
        self.root.update_idletasks()

    def _on_start(self):
        errors = []
        phase = self._vars["phase"].get().strip()

        animal = self._vars["animal"].get().strip() or "unknown"
        session_n = self._vars["session_n"].get().strip() or "1"
        port = self._vars["port"].get().strip()
        if not port:
            errors.append("Serial port is required.")

        try:
            baud = int(self._vars["baud"].get().strip())
        except ValueError:
            errors.append("Baud rate must be an integer.")
            baud = None

        try:
            valve_time = float(self._timing_vars["valve_time"].get())
        except ValueError:
            errors.append("Valve time must be a number.")
            valve_time = None

        # Session duration — at least one of time or trials must be set
        duration_s_str = self._timing_vars["session_duration_s"].get().strip()
        duration_t_str = self._timing_vars["session_duration_trials"].get().strip()
        session_duration_s = session_duration_trials = None
        if not duration_s_str and not duration_t_str:
            errors.append("Set at least one session duration (time in seconds or number of trials).")
        else:
            if duration_s_str:
                try:
                    session_duration_s = int(duration_s_str)
                except ValueError:
                    errors.append("Session duration (s) must be an integer.")
            if duration_t_str:
                try:
                    session_duration_trials = int(duration_t_str)
                except ValueError:
                    errors.append("Session duration (trials) must be an integer.")

        # Sensory minimum (phases 2, 3a)
        sensory_minimum = None
        if phase in ("2", "3a"):
            try:
                sensory_minimum = float(self._timing_vars["sensory_minimum"].get())
            except ValueError:
                errors.append("Sensory Minimum must be a number.")

        # Phase 4 params
        phase4_sensory_min = phase4_decision_window = None
        if phase == "4":
            try:
                phase4_sensory_min = float(self._timing_vars["phase4_sensory_min"].get())
                phase4_decision_window = float(self._timing_vars["phase4_decision_window"].get())
            except ValueError:
                errors.append("Phase 4 Sensory Minimum and Decision Window must be numbers.")

        # Task params
        task_sensory_min = task_decision_window = None
        if phase == "task":
            try:
                task_sensory_min = float(self._timing_vars["task_sensory_min"].get())
                task_decision_window = float(self._timing_vars["task_decision_window"].get())
            except ValueError:
                errors.append("Task Sensory Minimum and Decision Window must be numbers.")

        # Phase 3b gradual sensory minimum
        thresholds, holds = [], []
        if phase == "3b":
            try:
                for i in range(3):
                    t = self._phase3b_threshold_vars[i].get().strip()
                    h = self._phase3b_hold_vars[i].get().strip()
                    if t and h:
                        thresholds.append(int(t))
                        holds.append(float(h))
                    elif t or h:
                        errors.append(
                            f"Phase 3b step {i+1}: fill both threshold and sensory minimum, or leave both blank.")
                final_h = self._phase3b_hold_vars[3].get().strip()
                if final_h:
                    holds.append(float(final_h))
                else:
                    errors.append("Phase 3b final sensory minimum (s) is required.")
            except ValueError:
                errors.append("Phase 3b values must be numbers.")

        if errors:
            messagebox.showerror("Input Error", "\n".join(errors))
            return

        self.result = {
            "species": self._species_var.get(),
            "animal": animal,
            "session_n": session_n,
            "phase": phase,
            "port": port,
            "baud": baud,
            "valve_time": valve_time,
            "session_duration_s": session_duration_s,
            "session_duration_trials": session_duration_trials,
            "sensory_minimum": sensory_minimum,
            "phase4_sensory_min": phase4_sensory_min,
            "phase4_decision_window": phase4_decision_window,
            "task_sensory_min": task_sensory_min,
            "task_decision_window": task_decision_window,
            "phase3b_thresholds": thresholds,
            "phase3b_holds": holds,
            "notes": self._notes.get("1.0", "end").strip(),
        }
        self.root.destroy()

    # ── Public ────────────────────────────────────────────────────────────────

    def run(self):
        """Block until the dialog closes; returns the params dict or None."""
        self.root.mainloop()
        return self.result
