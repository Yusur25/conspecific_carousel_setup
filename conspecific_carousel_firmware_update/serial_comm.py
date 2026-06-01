import serial
import serial.tools.list_ports
import threading
import queue
import time

from protocol import (
    HEADER, MSG_WRITE, MSG_READ, MSG_ACK, MSG_EVENT,
    PACKET_SIZE, build_packet, parse_packet,
)


def list_serial_ports():
    return [p.device for p in serial.tools.list_ports.comports()]


class DeviceConnection:

    def __init__(self, port, baudrate=115200, timeout=1.0, retries=3):
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._retries = retries
        self._serial = None
        self._reader_thread = None
        self._running = False
        self._ack_queue = queue.Queue()
        self._lock = threading.Lock()

        self._event_callbacks = []
        self._ack_callbacks = []
        self._tx_callbacks = []
        self._error_callbacks = []

    # ---- lifecycle ----

    def connect(self):
        self._serial = serial.Serial(self._port, self._baudrate, timeout=0.1)
        self._running = True
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def disconnect(self):
        self._running = False
        if self._reader_thread:
            self._reader_thread.join(timeout=2.0)
            self._reader_thread = None
        if self._serial and self._serial.is_open:
            self._serial.close()
        self._serial = None

    @property
    def is_connected(self):
        return self._serial is not None and self._serial.is_open

    # ---- callback registration ----

    def on_event(self, cb):
        self._event_callbacks.append(cb)

    def on_ack(self, cb):
        self._ack_callbacks.append(cb)

    def on_tx(self, cb):
        self._tx_callbacks.append(cb)

    def on_error(self, cb):
        self._error_callbacks.append(cb)

    # ---- public API ----

    def write_register(self, register, value):
        packet = build_packet(register, MSG_WRITE, value)
        return self._send_with_retry(packet, register)

    def read_register(self, register):
        packet = build_packet(register, MSG_READ)
        return self._send_with_retry(packet, register)

    # ---- internals ----

    def _send_with_retry(self, packet, register):
        with self._lock:
            # drain stale ACKs
            while not self._ack_queue.empty():
                try:
                    self._ack_queue.get_nowait()
                except queue.Empty:
                    break

            last_err = None
            for attempt in range(self._retries):
                try:
                    self._serial.write(packet)
                    for cb in self._tx_callbacks:
                        cb(packet[1], packet[2], packet[3])
                    ack = self._ack_queue.get(timeout=self._timeout)
                    return ack
                except queue.Empty:
                    last_err = f"Timeout (attempt {attempt + 1}/{self._retries}) for 0x{register:02X}"
                    for cb in self._error_callbacks:
                        cb(last_err)

            raise TimeoutError(
                f"No ACK received after {self._retries} attempts for register 0x{register:02X}"
            )

    def _reader_loop(self):
        buf = bytearray()
        while self._running:
            try:
                if self._serial and self._serial.in_waiting:
                    buf.extend(self._serial.read(self._serial.in_waiting))

                while len(buf) >= PACKET_SIZE:
                    try:
                        idx = buf.index(HEADER)
                    except ValueError:
                        buf.clear()
                        break

                    if idx > 0:
                        del buf[:idx]
                    if len(buf) < PACKET_SIZE:
                        break

                    packet = bytes(buf[:PACKET_SIZE])
                    del buf[:PACKET_SIZE]

                    result = parse_packet(packet)
                    if result is None:
                        continue

                    register, msg_type, value = result
                    if msg_type == MSG_ACK:
                        self._ack_queue.put((register, value))
                        for cb in self._ack_callbacks:
                            cb(register, value)
                    elif msg_type == MSG_EVENT:
                        for cb in self._event_callbacks:
                            cb(register, value)

            except serial.SerialException as e:
                if self._running:
                    for cb in self._error_callbacks:
                        cb(f"Serial error: {e}")
                break
            except Exception as e:
                if self._running:
                    for cb in self._error_callbacks:
                        cb(f"Read error: {e}")

            time.sleep(0.01)
