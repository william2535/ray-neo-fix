#!/usr/bin/env python3
"""
rayneo_poll.py - exploit the command/response channel found on the RayNeo glasses.

Commands go out as HID SET_REPORT on the control pipe. Replies come back
on interrupt endpoint 0x81. A two-byte payload of 01 01 is known to
produce exactly one reply frame.

    termux-usb -r -e "python -u rayneo_poll.py" /dev/bus/usb/001/002

Modes:
    (default)     poll the known command repeatedly, show changing bytes
    --sweep       try every second byte 00-FF, list which ones answer
    --sweep-first try every first byte 00-FF with second byte 01

Options:
    --cmd 0101    payload to poll, hex        (default 0101)
    --wvalue 0301 control wValue, hex         (default 0301 = feature, id 1)
    --seconds 20  poll duration               (default 20)
    --rate 20     polls per second            (default 20)
"""

import sys
import time
import ctypes
import ctypes.util

NO_DISCOVERY = 2

ERRORS = {
    0: "success", -1: "io error", -2: "invalid param", -3: "access denied",
    -4: "no device", -5: "not found", -6: "busy", -7: "timeout",
    -8: "overflow", -9: "pipe (refused)", -10: "interrupted",
    -11: "no memory", -12: "not supported", -99: "other",
}


def strerror(c):
    return ERRORS.get(c, "code %d" % c)


def load():
    for n in ("libusb-1.0.so", "libusb-1.0.so.0", ctypes.util.find_library("usb-1.0")):
        if not n:
            continue
        try:
            return ctypes.CDLL(n)
        except OSError:
            continue
    sys.exit("libusb not found. Run: pkg install libusb")


def open_handle(lib, fd):
    lib.libusb_set_option(None, ctypes.c_int(NO_DISCOVERY))
    ctx = ctypes.c_void_p()
    if lib.libusb_init(ctypes.byref(ctx)) != 0:
        sys.exit("libusb_init failed")
    lib.libusb_wrap_sys_device.argtypes = [
        ctypes.c_void_p, ctypes.c_ssize_t, ctypes.POINTER(ctypes.c_void_p)
    ]
    h = ctypes.c_void_p()
    rc = lib.libusb_wrap_sys_device(ctx, ctypes.c_ssize_t(fd), ctypes.byref(h))
    if rc != 0:
        sys.exit("Could not wrap descriptor: %s" % strerror(rc))
    return ctx, h


def send_cmd(lib, h, wvalue, iface, payload):
    buf = (ctypes.c_ubyte * len(payload))(*payload)
    rc = lib.libusb_control_transfer(
        h, ctypes.c_ubyte(0x21), ctypes.c_ubyte(0x09),
        ctypes.c_uint16(wvalue), ctypes.c_uint16(iface),
        buf, ctypes.c_uint16(len(payload)), ctypes.c_uint(800)
    )
    return rc


def read_frame(lib, h, ep=0x81, length=64, timeout=250):
    buf = (ctypes.c_ubyte * length)()
    n = ctypes.c_int(0)
    rc = lib.libusb_interrupt_transfer(
        h, ctypes.c_ubyte(ep), buf, ctypes.c_int(length),
        ctypes.byref(n), ctypes.c_uint(timeout)
    )
    if rc == 0 and n.value:
        return bytes(buf[:n.value])
    return None


def show(frame, prev, width=16):
    cells = []
    for i, b in enumerate(frame[:width]):
        if prev is not None and i < len(prev) and prev[i] != b:
            cells.append("[%02X]" % b)
        else:
            cells.append(" %02X " % b)
    return "".join(cells)


def parse_hex(s):
    s = s.replace(" ", "").replace(",", "")
    return [int(s[i:i + 2], 16) for i in range(0, len(s), 2)]


# --------------------------------------------------------------------- modes

def mode_poll(lib, h, wvalue, iface, cmd, seconds, rate):
    print("Polling %s at %d/s for %ds." % (
        " ".join("%02X" % b for b in cmd), rate, seconds))
    print("MOVE YOUR HEAD the whole time. Brackets mark bytes that changed.\n")

    interval = 1.0 / max(1, rate)
    deadline = time.time() + seconds
    prev = None
    replies = 0
    shown = 0
    changing = set()

    while time.time() < deadline:
        t0 = time.time()
        if send_cmd(lib, h, wvalue, iface, cmd) < 0:
            time.sleep(interval)
            continue
        frame = read_frame(lib, h)
        if frame:
            replies += 1
            if prev is not None:
                for i in range(min(len(frame), len(prev))):
                    if frame[i] != prev[i]:
                        changing.add(i)
            if shown < 25 and frame != prev:
                print("  %s" % show(frame, prev))
                shown += 1
            prev = frame
        dt = time.time() - t0
        if dt < interval:
            time.sleep(interval - dt)

    print("\n---- poll summary ----")
    print("replies ......... %d" % replies)
    print("byte positions that changed: %s"
          % (sorted(changing) if changing else "none - response is constant"))
    if changing:
        print("\nThat is live data. Send this list back.")
    elif replies:
        print("\nConstant reply. It answers, but this command is not the sensor.")
        print("Run again with --sweep to map the command set.")
    else:
        print("\nNo replies at all this time. Unplug, replug and retry.")


def mode_sweep(lib, h, wvalue, iface, first_byte, vary_first):
    label = "XX 01" if vary_first else "01 XX"
    print("Sweeping %s across 00-FF.\n" % label)
    hits = []
    for b in range(256):
        cmd = [b, 0x01] if vary_first else [first_byte, b]
        if send_cmd(lib, h, wvalue, iface, cmd) < 0:
            continue
        frame = read_frame(lib, h, timeout=120)
        if frame and any(frame):
            head = " ".join("%02X" % x for x in frame[:12])
            print("  %02X -> %s" % (b, head))
            hits.append(b)
        time.sleep(0.01)

    print("\n---- sweep summary ----")
    print("commands answered: %d" % len(hits))
    if hits:
        print("bytes: %s" % " ".join("%02X" % b for b in hits))
        print("\nSend this list back.")
    else:
        print("nothing answered")


def main():
    argv = sys.argv[1:]
    digits = [a for a in argv if a.isdigit()]
    if not digits:
        sys.exit("No descriptor found. Launch through termux-usb -r -e.")
    fd = int(digits[-1])

    def opt(name, default):
        return argv[argv.index(name) + 1] if name in argv else default

    cmd = parse_hex(opt("--cmd", "0101"))
    wvalue = int(opt("--wvalue", "0301"), 16)
    iface = 0
    seconds = int(opt("--seconds", "20"))
    rate = int(opt("--rate", "20"))
    sweep = "--sweep" in argv
    sweep_first = "--sweep-first" in argv

    print("RayNeo command/response probe")
    print("  descriptor %d, wValue 0x%04X, iface %d\n" % (fd, wvalue, iface))

    lib = load()
    ctx, h = open_handle(lib, fd)
    lib.libusb_set_auto_detach_kernel_driver(h, 1)
    rc = lib.libusb_claim_interface(h, iface)
    print("Claim: %s\n" % ("ok" if rc == 0 else strerror(rc)))

    # drain anything stale
    for _ in range(3):
        read_frame(lib, h, timeout=100)

    if sweep or sweep_first:
        mode_sweep(lib, h, wvalue, iface, cmd[0] if cmd else 0x01, sweep_first)
    else:
        mode_poll(lib, h, wvalue, iface, cmd, seconds, rate)

    lib.libusb_release_interface(h, iface)
    lib.libusb_close(h)
    lib.libusb_exit(ctx)


if __name__ == "__main__":
    main()
