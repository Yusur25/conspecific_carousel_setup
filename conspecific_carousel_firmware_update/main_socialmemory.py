# main_socialmemory.py
# Unified entry point for social memory training and task (rat and mouse).
# Run from the project root: python main_socialmemory.py
#
# A setup GUI opens first to collect all session parameters.
# Parameters are saved as metadata.json in the session output folder.
#
# Modes:
#   training — classical conditioning (port A/B/C, led_on_time, ITI, reward prob)
#   task     — stimulus presentations (S1 + S2) with CC during each ITI

import time
import signal
import os
import json
from datetime import datetime

from serial_comm import DeviceConnection
from hardware import SharedSensorState, EventLogger, STOP_EVENT, shutdown_outputs
from sm_setup_gui import SMSetupDialog


def handle_sigint(_sig, _frame):
    STOP_EVENT.set()
    print("[INFO] Stopping...")


signal.signal(signal.SIGINT, handle_sigint)


def _save_metadata(save_dir, params):
    meta = {k: v for k, v in params.items()}
    meta["timestamp"] = datetime.now().isoformat()
    path = os.path.join(save_dir, "metadata.json")
    with open(path, "w") as f:
        json.dump(meta, f, indent=2, default=str)
    print(f"[INFO] Metadata saved: {path}")


def _run_loop_training(session, shared, sensor_gui, perf_gui,
                       session_duration_s=None):
    """Update GUIs every 50 ms while training session runs."""
    start = time.time()
    while session.running and not STOP_EVENT.is_set():
        if session_duration_s and (time.time() - start) >= session_duration_s:
            print(f"[INFO] Session duration ({session_duration_s} s) reached")
            STOP_EVENT.set()
            break
        snap = shared.get()
        sensor_gui.update(snap)
        perf_gui.update(session.results_df)
        time.sleep(0.05)


def _run_loop_task(session, shared, sensor_gui, perf_gui):
    """Update GUIs every 50 ms while task session runs."""
    while session.running and not STOP_EVENT.is_set():
        snap = shared.get()
        sensor_gui.update(snap)
        perf_gui.update(session.presentations_df, session.conditioning_df)
        time.sleep(0.05)


def main():
    # ── Setup GUI ─────────────────────────────────────────────────────────────
    dialog = SMSetupDialog()
    params = dialog.run()

    if params is None:
        print("[INFO] Setup cancelled.")
        return

    mode      = params["mode"]
    species   = params["species"]
    animal    = params["animal"]
    session_n = params["session_n"]
    port      = params["port"]
    baud      = params["baud"]

    from SocialMemory.training import ClassicalConditioningSession
    from SocialMemory.task     import SocialMemoryTaskSession
    from gui_socialmemory      import SensorGUI, PerformanceGUI

    # ── Output directory + metadata ───────────────────────────────────────────
    date_str = datetime.now().strftime("%Y-%m-%d")
    BASE_SAVE_DIR = os.path.join(
        "SocialMemoryData",
        f"{animal}_{session_n}_{mode}_{date_str}_{species}",
    )
    os.makedirs(BASE_SAVE_DIR, exist_ok=True)
    print(f"[INFO] Saving to: {BASE_SAVE_DIR}")

    params["date"]     = date_str
    params["save_dir"] = BASE_SAVE_DIR
    _save_metadata(BASE_SAVE_DIR, params)

    sensor_log   = os.path.join(BASE_SAVE_DIR, "sensor_events.csv")
    perf_fig     = os.path.join(BASE_SAVE_DIR, "performance.png")

    # ── Connect to device ─────────────────────────────────────────────────────
    try:
        device = DeviceConnection(port, baudrate=baud)
        device.connect()
        time.sleep(2)
    except Exception as e:
        print(f"[ERROR] Cannot open serial port: {e}")
        return

    # ── Shared state + event logger ───────────────────────────────────────────
    shared = SharedSensorState()
    session_start = time.time()
    logger = EventLogger(
        shared,
        event_log_path=sensor_log,
        session_start=session_start,
    )
    device.on_event(logger)

    # ── GUIs ──────────────────────────────────────────────────────────────────
    sensor_gui = SensorGUI()
    perf_gui   = PerformanceGUI(animal_name=animal, mode=mode)

    session = None

    # ── Run session ───────────────────────────────────────────────────────────
    try:
        if mode == "training":
            session = ClassicalConditioningSession(
                ser=device,
                shared=shared,
                species=species,
                valve_time=params["valve_time"],
                ports=params["ports"],
                led_on_time=params["led_on_time"],
                iti_min=params["iti_min"],
                iti_max=params["iti_max"],
                reward_prob=params["reward_prob"],
                session_duration=params.get("session_duration"),
            )
            session.start()
            print(f"[INFO] Training started on ports {params['ports']} — "
                  f"Ctrl+C to stop")
            _run_loop_training(
                session, shared, sensor_gui, perf_gui,
                session_duration_s=params.get("session_duration"),
            )

        elif mode == "task":
            session = SocialMemoryTaskSession(
                ser=device,
                shared=shared,
                species=species,
                valve_time=params["valve_time"],
                n_s1=params["s1_n"],
                s1_duration=params["s1_duration"],
                s1_angle=params["s1_angle"],
                s1_iti_min=params["s1_iti_min"],
                s1_iti_max=params["s1_iti_max"],
                n_s2=params["s2_n"],
                s2_duration=params["s2_duration"],
                s2_angle=params["s2_angle"],
                s2_iti_min=params["s2_iti_min"],
                s2_iti_max=params["s2_iti_max"],
                cc_ports=params["cc_ports"],
                cc_led_on_time=params["cc_led_on_time"],
                cc_iti_min=params["cc_iti_min"],
                cc_iti_max=params["cc_iti_max"],
                cc_reward_prob=params["cc_reward_prob"],
            )
            session.start()
            print("[INFO] Task started — Ctrl+C to stop")
            _run_loop_task(session, shared, sensor_gui, perf_gui)

        else:
            print(f"[ERROR] Unknown mode: {mode}")

    finally:
        print("[INFO] Shutting down...")
        STOP_EVENT.set()

        if session is not None:
            session.stop_internal()

            if mode == "training":
                csv_path = os.path.join(BASE_SAVE_DIR, "trials.csv")
                session.results_df.to_csv(csv_path, index=False)
                print(f"[INFO] Trials saved: {csv_path}")
                # Final GUI update
                perf_gui.update(session.results_df)

            elif mode == "task":
                pres_path = os.path.join(BASE_SAVE_DIR, "presentations.csv")
                cc_path   = os.path.join(BASE_SAVE_DIR, "conditioning_trials.csv")
                session.presentations_df.to_csv(pres_path, index=False)
                session.conditioning_df.to_csv(cc_path, index=False)
                print(f"[INFO] Presentations saved: {pres_path}")
                print(f"[INFO] Conditioning trials saved: {cc_path}")
                perf_gui.update(session.presentations_df, session.conditioning_df)

        sensor_gui.update(shared.get())
        shutdown_outputs(device)
        device.disconnect()
        perf_gui.close(save_path=perf_fig)
        sensor_gui.close()
        print("[INFO] Clean shutdown complete")


if __name__ == "__main__":
    main()
