import time
import

conditioning = ClassicalConditioning(
    ser,
    shared_state,
    perf_gui,
    sensor_gui
)

conditioning.start()
time.sleep(600)   # 10 minutes of conditioning
conditioning.stop()
