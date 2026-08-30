#!/usr/bin/env python3
"""
rayneo_axes.py - sample one held position and report averages plus magnitude.

Run it once per orientation. Each run wakes sensor mode (stopping as soon
as it works, which also identifies the enabling command), samples for a few
seconds, then prints per-channel averages and the vector magnitude of
ch0-2. If ch0-2 really are an accelerometer, that magnitude stays near 9.81
in every orientation while the individual channels move.

    termux-usb -r -e "python -u rayneo_axes.py" /dev/bus/usb/001/002

Options:
    --secs 6    sampling seconds        (default 6)
    --n 10      channels decoded        (default 10)
    --quiet     averages only, no rows
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


def mag(vals):
    xs = [v for v in vals[:3] if v is not None]
    return sum(v * v for v in xs) ** 0.5 if len(xs) == 3 else float("nan")


def fast_wake(lib, h):
    """Sweep XX 01 but stop the moment sensor mode kicks in."""
    print("Waking", end="", flush=True)
    for b in range(256):
        for _ in range(3):
            send(lib, h, [b, 0x01])
            f = read(lib, h, 40)
            if f and len(f) > 1 and f[1] == 0x65:
                print(" awake at command %02X 01" % b, flush=True)
                return b
            time.sleep(0.004)
        if b % 24 == 0:
            print(".", end="", flush=True)
    print(" FAILED - no sensor frames", flush=True)
    return None


def main():
    argv = sys.argv[1:]
    digits = [a for a in argv if a.isdigit()]
    if not digits:
        sys.exit("No descriptor. Launch through termux-usb -r -e.")
    fd = int(digits[-1])

    def opt(name, default):
        return argv[argv.index(name) + 1] if name in argv else default

    secs = int(opt("--secs", "6"))
    count = int(opt("--n", "10"))
    quiet = "--quiet" in argv

    lib = load()
    ctx, h = open_handle(lib, fd)
    lib.libusb_set_auto_detach_kernel_driver(h, 1)
    rc = lib.libusb_claim_interface(h, 0)
    print("RayNeo axes - claim %s" % ("ok" if rc == 0 else "failed"), flush=True)

    cmd_byte = fast_wake(lib, h)
    if cmd_byte is None:
        return
    cmd = [cmd_byte, 0x01]

    print("\nSampling %ds. HANDS OFF NOW.\n" % secs, flush=True)
    print("      " + "".join("%8s" % ("ch%d" % i) for i in range(count)) + "     |v|")

    deadline = time.time() + secs
    totals = [0.0] * count
    hits = [0] * count
    n = 0
    last = 0.0
    mags = []

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
            m = mag(vals)
            if m == m:
                mags.append(m)
            if not quiet and time.time() - last > 0.5:
                print("      %s  %6.2f" % (row(vals), m), flush=True)
                last = time.time()
        time.sleep(0.04)

    avg = [(totals[i] / hits[i]) if hits[i] else None for i in range(count)]
    print("\n---- result ----")
    print("samples ... %d" % n)
    print("average ... %s" % row(avg))
    if mags:
        mags.sort()
        print("|ch0-2| ... mean %.2f, min %.2f, max %.2f"
              % (sum(mags) / len(mags), mags[0], mags[-1]))
        print("            gravity is 9.81")
        steady = (mags[-1] - mags[0]) < 1.5
        print("            magnitude %s during this sample"
              % ("held steady" if steady else "varied - you moved them"))
    print("\nenabling command was %02X 01" % cmd_byte)

    lib.libusb_release_interface(h, 0)
    lib.libusb_close(h)
    lib.libusb_exit(ctx)


if __name__ == "__main__":
    main()
