#!/usr/bin/env python3
"""
rayneo_ctrl.py - interrogate the RayNeo glasses over the HID control pipe.

The interrupt endpoint is silent, so this asks the device to describe
itself instead, then tries the control pipe as an alternative way in.

    termux-usb -r -e "python -u rayneo_ctrl.py" /dev/bus/usb/001/002

Stages:
    1. Read the HID report descriptor and parse it
    2. GET_REPORT on feature and input reports, IDs 0-8
    3. SET_REPORT enable attempts, listening after each
    4. Final listen on the interrupt endpoint

Options:
    --iface 0       interface number      (default 0)
    --ep 0x81       input endpoint        (default 0x81)
    --skip-set      stages 1 and 2 only, write nothing to the device
"""

import sys
import time
import ctypes
import ctypes.util

LIBUSB_OPTION_NO_DEVICE_DISCOVERY = 2
LIBUSB_ERROR_TIMEOUT = -7

ERRORS = {
    0: "success", -1: "io error", -2: "invalid parameter", -3: "access denied",
    -4: "no such device", -5: "not found", -6: "busy", -7: "timeout",
    -8: "overflow", -9: "pipe error (device refused)", -10: "interrupted",
    -11: "insufficient memory", -12: "not supported", -99: "other",
}


def strerror(c):
    return ERRORS.get(c, "code %d" % c)


def hexdump(data, indent="    "):
    out = []
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        out.append(indent + "%04X  " % i + " ".join("%02X" % b for b in chunk))
    return "\n".join(out)


# ------------------------------------------------------- HID descriptor parse

USAGE_PAGES = {
    0x01: "generic desktop", 0x02: "simulation", 0x03: "VR", 0x04: "sport",
    0x05: "game", 0x06: "generic device", 0x07: "keyboard", 0x08: "LED",
    0x09: "button", 0x0A: "ordinal", 0x0C: "consumer", 0x0D: "digitiser",
    0x20: "sensor", 0x84: "power", 0x8C: "bar code",
}

ITEM_NAMES = {
    0x04: "Usage Page", 0x08: "Usage", 0x14: "Logical Min", 0x24: "Logical Max",
    0x74: "Report Size", 0x94: "Report Count", 0x84: "Report ID",
    0xA0: "Collection", 0xC0: "End Collection", 0x80: "Input",
    0x90: "Output", 0xB0: "Feature", 0x18: "Usage Min", 0x28: "Usage Max",
}


def parse_report_descriptor(data):
    """Walk the short-item stream and report IDs, sizes and usage pages."""
    lines = []
    ids = set()
    i = 0
    depth = 0
    while i < len(data):
        prefix = data[i]
        size = prefix & 0x03
        if size == 3:
            size = 4
        tag = prefix & 0xFC
        val = 0
        for b in range(size):
            if i + 1 + b < len(data):
                val |= data[i + 1 + b] << (8 * b)
        name = ITEM_NAMES.get(tag, "tag 0x%02X" % tag)

        if tag == 0xC0:
            depth = max(0, depth - 1)
        pad = "  " * depth

        extra = ""
        if tag == 0x04:
            extra = "  (%s)" % USAGE_PAGES.get(val, "vendor/unknown")
        if tag == 0x84:
            ids.add(val)
        lines.append("    %s%-15s %d" % (pad, name, val) + extra)
        if tag == 0xA0:
            depth += 1

        i += 1 + size
    return lines, sorted(ids)


# ------------------------------------------------------------------- libusb

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
    lib.libusb_set_option(None, ctypes.c_int(LIBUSB_OPTION_NO_DEVICE_DISCOVERY))
    ctx = ctypes.c_void_p()
    rc = lib.libusb_init(ctypes.byref(ctx))
    if rc != 0:
        sys.exit("libusb_init failed: %s" % strerror(rc))
    lib.libusb_wrap_sys_device.argtypes = [
        ctypes.c_void_p, ctypes.c_ssize_t, ctypes.POINTER(ctypes.c_void_p)
    ]
    h = ctypes.c_void_p()
    rc = lib.libusb_wrap_sys_device(ctx, ctypes.c_ssize_t(fd), ctypes.byref(h))
    if rc != 0:
        sys.exit("Could not wrap descriptor: %s" % strerror(rc))
    return ctx, h


def control(lib, h, req_type, req, value, index, length, data=None, timeout=1500):
    if data is not None:
        buf = (ctypes.c_ubyte * len(data))(*data)
        n = len(data)
    else:
        buf = (ctypes.c_ubyte * length)()
        n = length
    rc = lib.libusb_control_transfer(
        h, ctypes.c_ubyte(req_type), ctypes.c_ubyte(req),
        ctypes.c_uint16(value), ctypes.c_uint16(index),
        buf, ctypes.c_uint16(n), ctypes.c_uint(timeout)
    )
    if rc < 0:
        return None, rc
    return bytes(buf[:rc]), rc


def listen(lib, h, ep, seconds, length=64, label=""):
    deadline = time.time() + seconds
    prev = None
    frames = 0
    shown = 0
    while time.time() < deadline:
        buf = (ctypes.c_ubyte * length)()
        n = ctypes.c_int(0)
        rc = lib.libusb_interrupt_transfer(
            h, ctypes.c_ubyte(ep), buf, ctypes.c_int(length),
            ctypes.byref(n), ctypes.c_uint(400)
        )
        if rc == 0 and n.value:
            frames += 1
            frame = bytes(buf[:n.value])
            if shown < 12 and frame != prev:
                marks = []
                for i, b in enumerate(frame):
                    if prev is not None and i < len(prev) and prev[i] != b:
                        marks.append("[%02X]" % b)
                    else:
                        marks.append(" %02X " % b)
                print("      " + "".join(marks[:16]))
                shown += 1
            prev = frame
    if label:
        print("      %s -> %d frames" % (label, frames))
    return frames


# ---------------------------------------------------------------------- main

def main():
    argv = sys.argv[1:]
    digits = [a for a in argv if a.isdigit()]
    if not digits:
        sys.exit("No descriptor found. Launch through termux-usb -r -e.")
    fd = int(digits[-1])

    iface = 0
    ep = 0x81
    skip_set = "--skip-set" in argv
    if "--iface" in argv:
        iface = int(argv[argv.index("--iface") + 1])
    if "--ep" in argv:
        v = argv[argv.index("--ep") + 1]
        ep = int(v, 16) if v.lower().startswith("0x") else int(v)

    print("RayNeo control-pipe probe")
    print("  descriptor %d, interface %d, in 0x%02X\n" % (fd, iface, ep))

    lib = load()
    ctx, h = open_handle(lib, fd)
    lib.libusb_set_auto_detach_kernel_driver(h, 1)
    rc = lib.libusb_claim_interface(h, iface)
    print("Claim interface %d: %s\n" % (iface, "ok" if rc == 0 else strerror(rc)))

    # ---- stage 1: report descriptor
    print("[1] HID report descriptor")
    data, rc = control(lib, h, 0x81, 0x06, 0x2200, iface, 512)
    report_ids = []
    if data and len(data):
        print("    %d bytes" % len(data))
        print(hexdump(data))
        print("\n    parsed:")
        lines, report_ids = parse_report_descriptor(data)
        for l in lines[:60]:
            print(l)
        if len(lines) > 60:
            print("    ... %d more items" % (len(lines) - 60))
        print("\n    report IDs found: %s" % (report_ids if report_ids else "none (single unnumbered report)"))
    else:
        print("    failed: %s" % strerror(rc))
    print()

    # ---- stage 2: GET_REPORT
    print("[2] GET_REPORT sweep")
    candidates = report_ids if report_ids else list(range(0, 9))
    got_any = False
    for rtype, tname in ((0x03, "feature"), (0x01, "input")):
        for rid in candidates:
            data, rc = control(lib, h, 0xA1, 0x01, (rtype << 8) | rid, iface, 64)
            if data and any(data):
                got_any = True
                print("    %s id %d: %s" % (tname, rid, " ".join("%02X" % b for b in data[:16])))
            elif data is not None:
                print("    %s id %d: all zero (%d bytes)" % (tname, rid, len(data)))
    if not got_any:
        print("    nothing readable")
    print()

    if skip_set:
        print("Skipping write stages as requested.")
        lib.libusb_release_interface(h, iface)
        lib.libusb_close(h)
        lib.libusb_exit(ctx)
        return

    # ---- stage 3: SET_REPORT enable attempts
    print("[3] SET_REPORT enable attempts")
    attempts = []
    for rid in (candidates or [0]):
        attempts.append((rid, [rid, 0x01]))
        attempts.append((rid, [rid, 0x01, 0x01]))
    attempts.append((0, [0x00, 0x02, 0x01]))

    for rid, payload in attempts:
        data, rc = control(lib, h, 0x21, 0x09, (0x03 << 8) | rid, iface,
                           len(payload), data=payload)
        tag = " ".join("%02X" % b for b in payload)
        if rc >= 0:
            print("    id %d <- %s  accepted" % (rid, tag))
            n = listen(lib, h, ep, 2, 64, "listen")
            if n:
                print("\n    *** DEVICE RESPONDED to id %d payload %s ***" % (rid, tag))
                print("    Note this line down and send it back.\n")
                listen(lib, h, ep, 10, 64, "extended listen")
                break
        else:
            print("    id %d <- %s  refused (%s)" % (rid, tag, strerror(rc)))
    print()

    # ---- stage 4: final listen
    print("[4] Final listen, 10s. Move your head.")
    frames = listen(lib, h, ep, 10, 64, "total")

    print("\n---- summary ----")
    print("report descriptor .. %s" % ("read" if report_ids or data else "failed"))
    print("frames at end ...... %d" % frames)
    if not frames:
        print("\nStill silent. The report descriptor above is the useful part -")
        print("send it back and we will read what the device says it does.")

    lib.libusb_release_interface(h, iface)
    lib.libusb_close(h)
    lib.libusb_exit(ctx)


if __name__ == "__main__":
    main()
