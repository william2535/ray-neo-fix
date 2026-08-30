#!/usr/bin/env python3
"""
rayneo_track.py - wake the RayNeo sensor mode, then guide a tilt test.

Sensor mode is not persistent. Sweeping 01 00 through 01 FF switches the
device into emitting type-0x65 frames; a fresh process has to do it again.
This wakes it, then walks you through four held positions and averages
each channel per position, so the axes can be identified properly.

    termux-usb -r -e "python -u rayneo_track.py" /dev/bus/usb/001/002

Options:
    --cmd FF01     command polled during the test  (default FF01)
    --free         skip the guided phases, just stream
    --hold 6       seconds per position            (default 6)
    --n 6          channels decoded                (default 6)
    --raw          also print raw hex
"""

import sys
import time
import struct
import ctypes
import ctypes.util

NO_DISCOVERY = 2


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
    if lib.libusb_wrap_sys_device(ctx, ctypes.c_ssize_t(fd), ctypes.byref(h)) != 0:
        sys.exit("Could not wrap descriptor")
    return ctx, h


def send(lib, h, payload):
    buf = (ctypes.c_ubyte * len(payload))(*payload)
    return lib.libusb_control_transfer(
        h, ctypes.c_ubyte(0x21), ctypes.c_ubyte(0x09),
        ctypes.c_uint16(0x0301), ctypes.c_uint16(0),
        buf, ctypes.c_uint16(len(payload)), ctypes.c_uint(600)
    )


def read(lib, h, timeout=150):
    buf = (ctypes.c_ubyte * 64)()
    n = ctypes.c_int(0)
    rc = lib.libusb_interrupt_transfer(
        h, ctypes.c_ubyte(0x81), buf, ctypes.c_int(64),
        ctypes.byref(n), ctypes.c_uint(timeout)
    )
    return bytes(buf[:n.value]) if rc == 0 and n.value else None


def decode(frame, count):
    out = []
    for i in range(count):
        a = 8 + i * 4
        if a + 4 > len(frame):
            break
        (v,) = struct.unpack("<f", frame[a:a + 4])
        out.append(None if (v != v or abs(v) > 1e6) else v)
    return out


def row(vals):
    return "".join("   ----" if v is None else "%8.2f" % v for v in vals)


def parse_hex(s):
    s = s.replace(" ", "").replace(",", "")
    return [int(s[i:i + 2], 16) for i in range(0, len(s), 2)]


def wake(lib, h):
    """Replay the sweep that flips the device into sensor mode."""
    print("Waking sensor mode", end="")
    seen65 = 0
    for b in range(256):
        send(lib, h, [0x01, b])
        f = read(lib, h, 20)
        if f and len(f) > 1 and f[1] == 0x65:
            seen65 += 1
        if b % 32 == 0:
            print(".", end="")
    print(" done (%d sensor frames during wake)" % seen65)
    return seen65


def sample(lib, h, cmd, seconds, count, show=True, raw=False):
    """Poll for a while, return per-channel averages and the sample count."""
    deadline = time.time() + seconds
    totals = [0.0] * count
    hits = [0] * count
    n = 0
    last = 0.0
    while time.time() < deadline:
        send(lib, h, cmd)
        f = read(lib, h)
        if f and len(f) > 1 and f[1] == 0x65:
            vals = decode(f, count)
            n += 1
            for i, v in enumerate(vals):
                if v is not None:
                    totals[i] += v
                    hits[i] += 1
            if show and time.time() - last > 0.4:
                print("   " + row(vals))
                if raw:
                    print("      " + " ".join("%02X" % x for x in f[:20]))
                last = time.time()
        time.sleep(0.04)
    avg = [(totals[i] / hits[i]) if hits[i] else None for i in range(count)]
    return avg, n


def countdown(label, secs=3):
    print("\n>>> %s" % label)
    for i in range(secs, 0, -1):
        print("    starting in %d..." % i)
        time.sleep(1)
    print("    HOLD STILL")


def main():
    argv = sys.argv[1:]
    digits = [a for a in argv if a.isdigit()]
    if not digits:
        sys.exit("No descriptor. Launch through termux-usb -r -e.")
    fd = int(digits[-1])

    def opt(name, default):
        return argv[argv.index(name) + 1] if name in argv else default

    cmd = parse_hex(opt("--cmd", "FF01"))
    hold = int(opt("--hold", "6"))
    count = int(opt("--n", "6"))
    free = "--free" in argv
    raw = "--raw" in argv

    lib = load()
    ctx, h = open_handle(lib, fd)
    lib.libusb_set_auto_detach_kernel_driver(h, 1)
    rc = lib.libusb_claim_interface(h, 0)
    print("RayNeo tracker - claim %s\n" % ("ok" if rc == 0 else "failed"))

    got = wake(lib, h)
    if not got:
        print("\nWake produced no sensor frames. Unplug, replug and retry.")
        return

    if free:
        print("\nFree run, 30s. Channels:")
        sample(lib, h, cmd, 30, count, show=True, raw=raw)
        lib.libusb_release_interface(h, 0)
        lib.libusb_close(h)
        lib.libusb_exit(ctx)
        return

    phases = [
        ("Lay the glasses FLAT, lenses facing down, on the table", "flat"),
        ("Stand them NOSE DOWN, as if looking at your feet", "nose down"),
        ("Lay them on their LEFT side", "left side"),
        ("Back to FLAT again", "flat again"),
    ]

    results = []
    for label, short in phases:
        countdown(label, 3)
        avg, n = sample(lib, h, cmd, hold, count, show=True, raw=raw)
        results.append((short, avg, n))
        print("    avg: %s  (%d samples)" % (row(avg), n))

    print("\n---- axis map ----")
    print("%-12s%s" % ("position", "".join("%8s" % ("ch%d" % i) for i in range(count))))
    for short, avg, n in results:
        print("%-12s%s" % (short, row(avg)))

    print("\nWhichever channel holds about 9.8 or -9.8 in a position is the")
    print("axis pointing at the ground. If that moves between channels as")
    print("the glasses rotate, it is a working three-axis accelerometer.")

    flat = results[0][1]
    mag = sum(v * v for v in flat[:3] if v is not None) ** 0.5
    print("\nflat vector magnitude: %.2f  (gravity is 9.81)" % mag)

    lib.libusb_release_interface(h, 0)
    lib.libusb_close(h)
    lib.libusb_exit(ctx)


if __name__ == "__main__":
    main()
