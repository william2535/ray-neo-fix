#!/usr/bin/env python3
"""
rayneo_live.py - watch RayNeo replies scroll past in real time.

Prints a line for every reply as it arrives, throttled so it stays
readable on a phone. Bytes 4-7 are the running clock and are dimmed
out of change detection by default, so brackets only appear on bytes
that are genuinely doing something.

    termux-usb -r -e "python -u rayneo_live.py" /dev/bus/usb/001/002

Options:
    --cmd 0166     payload to send each poll   (default 0166)
    --listen       send nothing, just watch    (passive mode)
    --rate 20      polls per second            (default 20)
    --lines 8      printed lines per second    (default 8)
    --bytes 16     bytes shown per line        (default 16)
    --ignore 4-7   byte range excluded from change marks (default 4-7)
    --seconds 30   run time                    (default 30)

Press Ctrl+C at any point to stop early and see the summary.
"""

import sys
import time
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


def send(lib, h, payload, iface=0, wvalue=0x0301):
    buf = (ctypes.c_ubyte * len(payload))(*payload)
    return lib.libusb_control_transfer(
        h, ctypes.c_ubyte(0x21), ctypes.c_ubyte(0x09),
        ctypes.c_uint16(wvalue), ctypes.c_uint16(iface),
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


def parse_hex(s):
    s = s.replace(" ", "").replace(",", "")
    return [int(s[i:i + 2], 16) for i in range(0, len(s), 2)]


def parse_range(s):
    if "-" in s:
        a, b = s.split("-")
        return set(range(int(a), int(b) + 1))
    return {int(s)}


def main():
    argv = sys.argv[1:]
    digits = [a for a in argv if a.isdigit()]
    if not digits:
        sys.exit("No descriptor. Launch through termux-usb -r -e.")
    fd = int(digits[-1])

    def opt(name, default):
        return argv[argv.index(name) + 1] if name in argv else default

    cmd = parse_hex(opt("--cmd", "0166"))
    passive = "--listen" in argv
    rate = int(opt("--rate", "20"))
    lines_per_sec = int(opt("--lines", "8"))
    width = int(opt("--bytes", "16"))
    ignore = parse_range(opt("--ignore", "4-7"))
    seconds = int(opt("--seconds", "30"))

    lib = load()
    ctx, h = open_handle(lib, fd)
    lib.libusb_set_auto_detach_kernel_driver(h, 1)
    rc = lib.libusb_claim_interface(h, 0)

    mode = "passive listen" if passive else "polling " + " ".join("%02X" % b for b in cmd)
    print("RayNeo live view - %s" % mode)
    print("claim %s, %ds, clock bytes %s dimmed"
          % ("ok" if rc == 0 else "failed", seconds, sorted(ignore)))
    print("\n     " + "".join("%3d " % i for i in range(min(width, 16))))
    print("     " + "-" * (4 * min(width, 16)))

    interval = 1.0 / max(1, rate)
    print_gap = 1.0 / max(1, lines_per_sec)
    deadline = time.time() + seconds
    last_print = 0.0
    prev = None
    replies = 0
    moving = set()

    try:
        while time.time() < deadline:
            t0 = time.time()
            if not passive:
                send(lib, h, cmd)
            frame = read(lib, h)
            if frame:
                replies += 1
                if prev is not None:
                    for i in range(min(len(frame), len(prev))):
                        if frame[i] != prev[i] and i not in ignore:
                            moving.add(i)
                if time.time() - last_print >= print_gap:
                    cells = []
                    for i, b in enumerate(frame[:width]):
                        if i in ignore:
                            cells.append(" %02X " % b)
                        elif prev is not None and i < len(prev) and prev[i] != b:
                            cells.append("[%02X]" % b)
                        else:
                            cells.append(" %02X " % b)
                    print("%4d " % replies + "".join(cells))
                    last_print = time.time()
                prev = frame
            dt = time.time() - t0
            if dt < interval:
                time.sleep(interval - dt)
    except KeyboardInterrupt:
        print("\nstopped early")

    print("\n---- summary ----")
    print("replies ......... %d" % replies)
    print("rate ............ %.1f/s" % (replies / max(1.0, seconds)))
    print("moving bytes .... %s"
          % (sorted(moving) if moving else "none outside the clock"))
    if moving:
        print("\nThose positions carry live data. Send this list back.")

    lib.libusb_release_interface(h, 0)
    lib.libusb_close(h)
    lib.libusb_exit(ctx)


if __name__ == "__main__":
    main()
