#!/usr/bin/env python3
"""
rayneo_raw.py - dump the whole 64-byte sensor frame, not just the float view.

The float decoder shows exact 0.00 in several channels, which is suspicious.
The missing third accelerometer axis is probably encoded at a different
width or offset. This prints the full frame as hex, as float32, as int16
and as int32 all at once, so a value near +-9.8 (or a scaled integer form
of it) becomes visible whatever shape it is in.

    termux-usb -r -e "python -u rayneo_raw.py" /dev/bus/usb/001/002

Options:
    --secs 6      sampling seconds            (default 6)
    --hunt 8.83   flag any field near this    (default off)
    --tol 0.6     match tolerance for --hunt  (default 0.6)
    --frames 3    raw frames printed          (default 3)
"""

import sys
import time
import struct
import ctypes
import ctypes.util

NO_DISCOVERY = 2
ENABLE = [0x00, 0x01]


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


def hexdump(f):
    out = []
    for i in range(0, len(f), 16):
        chunk = f[i:i + 16]
        out.append("  %02X  %s" % (i, " ".join("%02X" % b for b in chunk)))
    return "\n".join(out)


def all_fields(f):
    """Every plausible numeric field in the frame, as (label, offset, value)."""
    out = []
    for o in range(0, len(f) - 3):
        (v,) = struct.unpack("<f", f[o:o + 4])
        if v == v and abs(v) < 1e6:
            out.append(("f32le", o, v))
    for o in range(0, len(f) - 1):
        (v,) = struct.unpack("<h", f[o:o + 2])
        out.append(("i16le", o, v))
        (v,) = struct.unpack(">h", f[o:o + 2])
        out.append(("i16be", o, v))
    for o in range(0, len(f) - 3):
        (v,) = struct.unpack("<i", f[o:o + 4])
        out.append(("i32le", o, v))
    return out


def main():
    argv = sys.argv[1:]
    digits = [a for a in argv if a.isdigit()]
    if not digits:
        sys.exit("No descriptor. Launch through termux-usb -r -e.")
    fd = int(digits[-1])

    def opt(name, d):
        return argv[argv.index(name) + 1] if name in argv else d

    secs = int(opt("--secs", "6"))
    frames_to_show = int(opt("--frames", "3"))
    hunt = float(opt("--hunt", "0")) if "--hunt" in argv else None
    tol = float(opt("--tol", "0.6"))

    lib = load()
    ctx, h = open_handle(lib, fd)
    lib.libusb_set_auto_detach_kernel_driver(h, 1)
    rc = lib.libusb_claim_interface(h, 0)
    print("RayNeo raw dump - claim %s" % ("ok" if rc == 0 else "failed"), flush=True)

    send(lib, h, ENABLE)
    time.sleep(0.05)
    probe = read(lib, h, 300)
    if not (probe and len(probe) > 1 and probe[1] == 0x65):
        print("Enable 00 01 did not give a sensor frame. Unplug, replug, retry.")
        return
    print("Awake via 00 01.\n", flush=True)

    print("Sampling %ds. HANDS OFF NOW.\n" % secs, flush=True)
    frames = []
    deadline = time.time() + secs
    while time.time() < deadline:
        send(lib, h, ENABLE)
        f = read(lib, h)
        if f and len(f) >= 64 and f[1] == 0x65:
            frames.append(f)
        time.sleep(0.04)

    if not frames:
        print("No frames captured.")
        return
    print("captured %d frames\n" % len(frames), flush=True)

    print("---- raw frames ----")
    for f in frames[:frames_to_show]:
        print(hexdump(f))
        print()

    # which byte positions actually move
    moving = set()
    for a, b in zip(frames, frames[1:]):
        for i in range(64):
            if a[i] != b[i]:
                moving.add(i)
    print("bytes that changed across the sample:")
    print("  %s\n" % (sorted(moving) if moving else "none"))

    # stable numeric fields, averaged
    print("---- stable fields (mean over sample) ----")
    n = len(frames)
    sums = {}
    for f in frames:
        for label, off, v in all_fields(f):
            sums.setdefault((label, off), []).append(v)

    interesting = []
    for (label, off), vals in sums.items():
        mean = sum(vals) / len(vals)
        spread = max(vals) - min(vals)
        if abs(mean) < 0.001:
            continue
        interesting.append((label, off, mean, spread))

    if hunt is not None:
        print("hunting for values near %+.2f (tolerance %.2f)\n" % (hunt, tol))
        hits = [x for x in interesting
                if abs(abs(x[2]) - abs(hunt)) < tol and x[3] < abs(hunt) * 0.5]
        if hits:
            for label, off, mean, spread in sorted(hits, key=lambda x: x[1]):
                print("  %s @ %2d   mean %+9.3f   spread %.3f" % (label, off, mean, spread))
        else:
            print("  nothing matched")
        print()

    print("float32 fields at 4-byte offsets:")
    for (label, off, mean, spread) in sorted(interesting, key=lambda x: x[1]):
        if label == "f32le" and off % 4 == 0 and abs(mean) > 0.01:
            print("  off %2d (ch%d)  mean %+10.3f  spread %8.3f"
                  % (off, (off - 8) // 4 if off >= 8 else -1, mean, spread))

    lib.libusb_release_interface(h, 0)
    lib.libusb_close(h)
    lib.libusb_exit(ctx)


if __name__ == "__main__":
    main()
