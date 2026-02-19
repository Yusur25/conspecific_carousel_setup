import time
import serial
import hardware

# -------------------------
# CONFIG
# -------------------------
SERIAL_PORT = "COM3"
BAUDRATE = 115200


def print_position():
    print(f"\n[LOGICAL POSITION] {hardware.current_table_position}")
    print(f"[STEP VALUE] {hardware.TABLE_POSITIONS[hardware.current_table_position]}")
    print("-" * 50)


def main():
    print("Opening serial connection...")
    ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=1)
    time.sleep(2)  # allow Arduino to reset

    print("Starting at default position.")
    hardware.reset_table_to_default(ser)
    print_position()

    while True:
        print("\nEnter table position (0–4)")
        print("0 = Default")
        print("1 = 90° CW")
        print("2 = 180° CW")
        print("3 = 270° CW")
        print("4 = 90° CCW")
        print("q = Quit")

        user_input = input("Move to position: ")

        if user_input.lower() == "q":
            break

        try:
            pos = int(user_input)
            hardware.move_table_to_position(ser, pos)
            print_position()
        except Exception as e:
            print(f"Error: {e}")

    print("\nResetting to default before exit...")
    hardware.reset_table_to_default(ser)
    print_position()

    ser.close()
    print("Done.")


if __name__ == "__main__":
    main()
