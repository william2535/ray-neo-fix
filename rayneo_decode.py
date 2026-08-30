#!/usr/bin/env python3
"""
rayneo_decode.py - read the RayNeo 0x65 sensor frame as floating point.

The frame looks like:  99 65 40 00 <clock> <floats...>

Whether the clock is 3 or 4 bytes decides where the floats start, so this
prints both readings side by side. Tilt the glasses through a known
movement and whichever column behaves sensibly is the right one.

    termux-usb -r -e "python -u rayneo_decode.py" /dev/bus/usb/001/002

Options:
    --cmd FF01     command to poll             (default FF01)
    --n 6          floats shown per layout     (default 6)
    --rate 20      polls per second            (default 20)
    --lines 5      printed lines per second    (default 5)
    --seconds 30   run time                    (default 30)
    --raw          also print the raw hex line
    --le-only      show only the little-endian offset-8 reading
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


def read(lib, h, timeout=200):
    buf = (ctypes.c_ubyte * 64)()
    n = ctypes.c_int(0)
    rc = lib.libusb_interrupt_transfer(
        h, ctypes.c_ubyte(0x81), buf, ctypes.c_int(64),
        ctypes.byref(n), ctypes.c_uint(timeout)
    )
    return bytes(buf[:n.value]) if rc == 0 and n.value else None


def floats(frame, offset, count, endian):
    """Pull `count` IEEE-754 singles from `offset`. Returns None for junk."""
    out = []
    fmt = "<f" if endian == "le" else ">f"
    for i in range(count):
        a = offset + i * 4
        if a + 4 > len(frame):
            break
        (v,) = struct.unpack(fmt, frame[a:a + 4])
        if v != v or abs(v) > 1e6:      # NaN or absurd magnitude
            out.append(None)
        else:
            out.append(v)
    return out


def fmt_row(vals):
    cells = []
    for v in vals:
        cells.append("   ----" if v is None else "%8.2f" % v)
    return "".join(cells)


def parse_hex(s):
    s = s.replace(" ", "").replace(",", "")
    return [int(s[i:i + 2], 16) for i in range(0, len(s), 2)]


def main():
    argv = sys.argv[1:]
    digits = [a for a in argv if a.isdigit()]
    if not digits:
        sys.exit("No descriptor. Launch through termux-usb -r -e.")
    fd = int(digits[-1])

    def opt(name, default):
        return argv[argv.index(name) + 1] if name in argv else default

    cmd = parse_hex(opt("--cmd", "FF01"))
    count = int(opt("--n", "6"))
    rate = int(opt("--rate", "20"))
    lines_per_sec = int(opt("--lines", "5"))
    seconds = int(opt("--seconds", "30"))
    raw = "--raw" in argv
    le_only = "--le-only" in argv

    lib = load()
    ctx, h = open_handle(lib, fd)
    lib.libusb_set_auto_detach_kernel_driver(h, 1)
    rc = lib.libusb_claim_interface(h, 0)

    print("RayNeo float decode - cmd %s" % " ".join("%02X" % b for b in cmd))
    print("claim %s\n" % ("ok" if rc == 0 else "failed"))
    if le_only:
        print("       little-endian from offset 8")
    else:
        print("       %-*s | %s" % (8 * count, "LITTLE-ENDIAN from offset 8",
                                    "BIG-ENDIAN from offset 7"))
    print("       " + "-" * (8 * count * (1 if le_only else 2) + 3))

    interval = 1.0 / max(1, rate)
    gap = 1.0 / max(1, lines_per_sec)
    deadline = time.time() + seconds
    last = 0.0
    n_sensor = 0
    n_other = 0
    lo = [None] * count
    hi = [None] * count

    try:
        while time.time() < deadline:
            t0 = time.time()
            send(lib, h, cmd)
            frame = read(lib, h)
            if frame and len(frame) >= 24:
                if frame[1] == 0x65:
                    n_sensor += 1
                    le = floats(frame, 8, count, "le")
                    be = floats(frame, 7, count, "be")
                    for i, v in enumerate(le):
                        if v is None:
                            continue
                        if lo[i] is None or v < lo[i]:
                            lo[i] = v
                        if hi[i] is None or v > hi[i]:
                            hi[i] = v
                    if time.time() - last >= gap:
                        line = fmt_row(le) if le_only else fmt_row(le) + " |" + fmt_row(be)
                        print("%6d %s" % (n_sensor, line))
                        if raw:
                            print("       " + " ".join("%02X" % b for b in frame[:24]))
                        last = time.time()
                else:
                    n_other += 1
            dt = time.time() - t0
            if dt < interval:
                time.sleep(interval - dt)
    except KeyboardInterrupt:
        print("\nstopped early")

    print("\n---- summary ----")
    print("sensor frames (type 65) .. %d" % n_sensor)
    print("other frames ............. %d" % n_other)
    if n_sensor:
        print("\nlittle-endian channel ranges:")
        for i in range(count):
            if lo[i] is None:
                continue
            span = hi[i] - lo[i]
            flag = "  <-- moving" if span > 1.0 else ""
            print("  ch%d  %8.2f .. %8.2f   span %7.2f%s" % (i, lo[i], hi[i], span, flag))
        print("\nChannels with a big span are responding to movement.")

    lib.libusb_release_interface(h, 0)
    lib.libusb_close(h)
    lib.libusb_exit(ctx)


if __name__ == "__main__":
    main()
