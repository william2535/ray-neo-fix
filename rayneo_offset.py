#!/usr/bin/env python3
"""
rayneo_offset.py - settle where the accelerometer triple starts.

Two competing readings of the 0x65 sensor frame:

    A (offset 4)   accel = floats at 4, 8, 12    gyro = 16, 20, 24
    B (offset 8)   accel = floats at 8, 12, 16   gyro = 20, 24, 28

Both look like gravity when the glasses lie flat, because the third axis
is near zero there. They separate on the left side, where gravity leaves
the 8/12 plane: A should hold 9.8, B should collapse to about 4.3.

Polls properly at ~20/s rather than waiting for a stream that never comes.

    termux-usb -r -e "python -u rayneo_offset.py" /dev/bus/usb/001/002

Options:
    --secs 8      sampling seconds       (default 8)
    --cmd 6601    start command, hex     (default 6601)
    --frames 3    raw frames printed     (default 3)
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


def f32(frame, off):
    if off + 4 > len(frame):
        return None
    (v,) = struct.unpack("<f", frame[off:off + 4])
    return None if (v != v or abs(v) > 1e6) else v


def triple(frame, start):
    return [f32(frame, start), f32(frame, start + 4), f32(frame, start + 8)]


def mag(t):
    if any(v is None for v in t):
        return float("nan")
    return sum(v * v for v in t) ** 0.5


def parse_hex(s):
    s = s.replace(" ", "")
    return [int(s[i:i + 2], 16) for i in range(0, len(s), 2)]


def main():
    argv = sys.argv[1:]
    digits = [a for a in argv if a.isdigit()]
    if not digits:
        sys.exit("No descriptor. Launch through termux-usb -r -e.")
    fd = int(digits[-1])

    def opt(n, d):
        return argv[argv.index(n) + 1] if n in argv else d

    secs = int(opt("--secs", "8"))
    cmd = parse_hex(opt("--cmd", "6601"))
    show = int(opt("--frames", "3"))

    lib = load()
    ctx, h = open_handle(lib, fd)
    lib.libusb_set_auto_detach_kernel_driver(h, 1)
    rc = lib.libusb_claim_interface(h, 0)
    print("RayNeo offset test - claim %s" % ("ok" if rc == 0 else "failed"), flush=True)

    got = None
    for _ in range(15):
        send(lib, h, cmd)
        f = read(lib, h, 60)
        if f and len(f) > 1 and f[1] == 0x65:
            got = f
            break
        time.sleep(0.03)
    if not got:
        print("No sensor frame from %s. Unplug, replug, retry."
              % " ".join("%02X" % b for b in cmd))
        return
    print("Sensor mode live via %s\n" % " ".join("%02X" % b for b in cmd), flush=True)

    print("Sampling %ds. HANDS OFF NOW.\n" % secs, flush=True)
    frames = []
    deadline = time.time() + secs
    last = 0.0
    print("        A: off 4,8,12          |A|      B: off 8,12,16         |B|")
    while time.time() < deadline:
        send(lib, h, cmd)
        f = read(lib, h)
        if f and len(f) >= 32 and f[1] == 0x65:
            frames.append(f)
            A = triple(f, 4)
            B = triple(f, 8)
            if time.time() - last > 0.6:
                print("   %7.2f%7.2f%7.2f  %6.2f   %7.2f%7.2f%7.2f  %6.2f"
                      % (A[0], A[1], A[2], mag(A), B[0], B[1], B[2], mag(B)),
                      flush=True)
                last = time.time()
        time.sleep(0.04)

    if not frames:
        print("no frames captured")
        return

    print("\ncaptured %d frames" % len(frames))

    print("\n---- raw frames, bytes 0-31 (note bytes 4-7) ----")
    for f in frames[:show]:
        print("   " + " ".join("%02X" % b for b in f[:16]))
        print("   " + " ".join("%02X" % b for b in f[16:32]))
        print()

    def stats(start):
        ms = [mag(triple(f, start)) for f in frames]
        ms = [m for m in ms if m == m]
        chans = [[], [], []]
        for f in frames:
            t = triple(f, start)
            for i, v in enumerate(t):
                if v is not None:
                    chans[i].append(v)
        avg = [sum(c) / len(c) if c else float("nan") for c in chans]
        return avg, sum(ms) / len(ms), min(ms), max(ms)

    for name, start in (("A  offset 4", 4), ("B  offset 8", 8)):
        avg, mean, lo, hi = stats(start)
        print("---- %s ----" % name)
        print("   mean axes  %7.2f %7.2f %7.2f" % tuple(avg))
        print("   |v|        mean %.2f   min %.2f   max %.2f" % (mean, lo, hi))
        verdict = "MATCHES GRAVITY" if abs(mean - 9.81) < 0.7 else "does not match 9.81"
        print("   %s\n" % verdict)

    print("Gravity is 9.81. In this position, whichever layout holds 9.81")
    print("is the correct one - provided you kept the glasses still.")

    lib.libusb_release_interface(h, 0)
    lib.libusb_close(h)
    lib.libusb_exit(ctx)


if __name__ == "__main__":
    main()
