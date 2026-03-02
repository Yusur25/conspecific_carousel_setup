# test_table_input.py
import time
import serial
from hardware import move_table_to_position, reset_table_to_default, current_table_position, TABLE_POSITIONS

# -------------------------
# CONFIGURE YOUR SERIAL PORT
# -------------------------
SERIAL_PORT = "COM3"   # replace with your serial port
BAUDRATE = 57600

# -------------------------
# HELPER FUNCTION
# -------------------------
def print_table_status():
    print(f"[INFO] Current table position index: {current_table_position}, "
          f"angle: {TABLE_POSITIONS[current_table_position]}°")

# -------------------------
# MAIN LOOP
# -------------------------
def main():
    try:
        ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=0.1)
        time.sleep(2)  # allow serial to initialize

        print("[INFO] Table test ready. Box numbers: ", list(TABLE_POSITIONS.keys()))
        reset_table_to_default(ser)
        print_table_status()

        while True:
            user_input = input("Enter box number to move to (or 'q' to quit): ").strip()
            if user_input.lower() == "q":
                break
            if not user_input.isdigit():
                print("[WARN] Enter a valid number!")
                continue

            box = int(user_input)
            if box not in TABLE_POSITIONS:
                print(f"[WARN] Invalid box. Valid numbers: {list(TABLE_POSITIONS.keys())}")
                continue

            move_table_to_position(ser, box)
            print_table_status()

    finally:
        ser.close()
        print("[INFO] Serial closed, test ended.")

if __name__ == "__main__":
    main()