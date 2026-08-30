#!/usr/bin/env python3
"""
rayneo_dump.py - read raw HID reports from RayNeo Air glasses on Android.

Run under Termux via termux-usb, which hands us an already-permitted
file descriptor. We cannot enumerate USB on Android, so libusb is put
into no-discovery mode and wrapped around that descriptor directly.

    termux-usb -l
    termux-usb -r -e "python rayneo_dump.py" /dev/bus/usb/001/002

Options (append after the script name inside the quotes):
    --ep 0x81       input endpoint to read      (default 0x81)
    --out 0x01      output endpoint for --send  (default 0x01)
    --iface 0       interface to claim          (default 0)
    --len 64        report length in bytes      (default 64)
    --seconds 15    how long to listen          (default 15)
    --all           print every frame, not just changed ones
    --send AABBCC   send these hex bytes before listening
    --probe         try a short list of common wake-up patterns
"""

import sys
import time
import ctypes
import ctypes.util

# ---------------------------------------------------------------- constants

LIBUSB_OPTION_NO_DEVICE_DISCOVERY = 2
LIBUSB_ERROR_TIMEOUT = -7

ERRORS = {
    0: "success", -1: "io error", -2: "invalid parameter", -3: "access denied",
    -4: "no such device", -5: "not found", -6: "busy", -7: "timeout",
    -8: "overflow", -9: "pipe error", -10: "interrupted",
    -11: "insufficient memory", -12: "not supported", -99: "other",
}


def strerror(code):
    return ERRORS.get(code, "code %d" % code)


# ---------------------------------------------------------------- arguments

def parse_args(argv):
    opts = {
        "ep": 0x81, "out": 0x01, "iface": 0, "len": 64,
        "seconds": 15, "all": False, "send": None, "probe": False,
    }
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--all":
            opts["all"] = True
        elif a == "--probe":
            opts["probe"] = True
        elif a in ("--ep", "--out", "--iface", "--len", "--seconds", "--send"):
            if i + 1 >= len(argv):
                sys.exit("Missing value after %s" % a)
            v = argv[i + 1]
            i += 1
            if a == "--send":
                opts["send"] = v
            elif a in ("--ep", "--out"):
                opts[a[2:]] = int(v, 16) if v.lower().startswith("0x") else int(v)
            else:
                opts[a[2:]] = int(v)
        elif a.startswith("-"):
            sys.exit("Unknown option %s" % a)
        i += 1
    return opts


# ---------------------------------------------------------------- libusb

def load_libusb():
    for name in ("libusb-1.0.so", "libusb-1.0.so.0", ctypes.util.find_library("usb-1.0")):
        if not name:
            continue
        try:
            return ctypes.CDLL(name)
        except OSError:
            continue
    sys.exit("libusb not found. Run: pkg install libusb")


def setup(lib, fd):
    lib.libusb_set_option.restype = ctypes.c_int
    rc = lib.libusb_set_option(None, ctypes.c_int(LIBUSB_OPTION_NO_DEVICE_DISCOVERY))
    if rc != 0:
        print("! set_option returned %s (continuing)" % strerror(rc))

    ctx = ctypes.c_void_p()
    rc = lib.libusb_init(ctypes.byref(ctx))
    if rc != 0:
        sys.exit("libusb_init failed: %s" % strerror(rc))

    lib.libusb_wrap_sys_device.argtypes = [
        ctypes.c_void_p, ctypes.c_ssize_t, ctypes.POINTER(ctypes.c_void_p)
    ]
    handle = ctypes.c_void_p()
    rc = lib.libusb_wrap_sys_device(ctx, ctypes.c_ssize_t(fd), ctypes.byref(handle))
    if rc != 0:
        sys.exit("Could not wrap the descriptor: %s\n"
                 "Check you passed the right /dev/bus/usb path to termux-usb."
                 % strerror(rc))
    return ctx, handle


def claim(lib, handle, iface):
    lib.libusb_set_auto_detach_kernel_driver(handle, 1)
    rc = lib.libusb_claim_interface(handle, iface)
    if rc == 0:
        print("Interface %d claimed." % iface)
        return True
    print("! claim_interface(%d) failed: %s" % (iface, strerror(rc)))
    if rc == -6:
        print("  The kernel HID driver is holding it. Unplug, replug, retry.")
    print("  Continuing anyway - some kernels allow reads regardless.\n")
    return False


# ---------------------------------------------------------------- transfers

def send(lib, handle, ep, payload):
    buf = (ctypes.c_ubyte * len(payload))(*payload)
    n = ctypes.c_int(0)
    rc = lib.libusb_interrupt_transfer(
        handle, ctypes.c_ubyte(ep), buf, ctypes.c_int(len(payload)),
        ctypes.byref(n), ctypes.c_uint(1000)
    )
    tag = " ".join("%02X" % b for b in payload[:12])
    if rc == 0:
        print("  -> sent %d bytes: %s" % (n.value, tag))
    else:
        print("  -> send failed (%s): %s" % (strerror(rc), tag))
    return rc == 0


def read_once(lib, handle, ep, length, timeout_ms):
    buf = (ctypes.c_ubyte * length)()
    n = ctypes.c_int(0)
    rc = lib.libusb_interrupt_transfer(
        handle, ctypes.c_ubyte(ep), buf, ctypes.c_int(length),
        ctypes.byref(n), ctypes.c_uint(timeout_ms)
    )
    if rc == 0:
        return bytes(buf[:n.value]), None
    return None, rc


def fmt(frame, previous, width=16):
    """Hex dump, wrapping bytes that changed since the last frame in brackets."""
    out = []
    for i, b in enumerate(frame):
        cell = "%02X" % b
        if previous is not None and i < len(previous) and previous[i] != b:
            out.append("[%s]" % cell)
        else:
            out.append(" %s " % cell)
    lines = []
    for i in range(0, len(out), width):
        lines.append("".join(out[i:i + width]))
    return "\n        ".join(lines)


# ---------------------------------------------------------------- wake-ups

# Generic patterns seen across vendor HID glasses. Guesses, nothing more.
PROBE_PATTERNS = [
    [0x00, 0x01],
    [0x01, 0x01],
    [0x02, 0x01],
    [0xAA, 0x01],
    [0xFD, 0x1E, 0xB9, 0xF0],
]


# ---------------------------------------------------------------- main

def main():
    argv = sys.argv[1:]
    if not argv:
        sys.exit("No file descriptor. Launch through termux-usb -r -e.")

    try:
        fd = int(argv[0])
    except ValueError:
        sys.exit("First argument should be the descriptor from termux-usb, got %r" % argv[0])

    opts = parse_args(argv[1:])

    print("RayNeo HID dump")
    print("  descriptor %d, interface %d, in 0x%02X, out 0x%02X, %d bytes\n"
          % (fd, opts["iface"], opts["ep"], opts["out"], opts["len"]))

    lib = load_libusb()
    ctx, handle = setup(lib, fd)
    claim(lib, handle, opts["iface"])

    if opts["send"]:
        raw = opts["send"].replace(" ", "").replace(",", "")
        try:
            payload = [int(raw[i:i + 2], 16) for i in range(0, len(raw), 2)]
        except ValueError:
            sys.exit("--send needs plain hex, e.g. --send 0201")
        print("Sending wake-up:")
        send(lib, handle, opts["out"], payload)
        print()

    if opts["probe"]:
        print("Probing wake-up patterns:")
        for p in PROBE_PATTERNS:
            send(lib, handle, opts["out"], p)
            time.sleep(0.15)
        print()

    print("Listening %ds. Move your head around now.\n" % opts["seconds"])

    deadline = time.time() + opts["seconds"]
    previous = None
    frames = 0
    shown = 0
    timeouts = 0
    other_errors = 0

    try:
        while time.time() < deadline:
            frame, rc = read_once(lib, handle, opts["ep"], opts["len"], 500)
            if frame is None:
                if rc == LIBUSB_ERROR_TIMEOUT:
                    timeouts += 1
                else:
                    other_errors += 1
                    if other_errors > 8:
                        print("Too many transfer errors (%s). Stopping." % strerror(rc))
                        break
                continue

            frames += 1
            changed = previous is not None and frame != previous
            if opts["all"] or previous is None or changed:
                if shown < 40:
                    print("  %5d  %s" % (frames, fmt(frame, previous)))
                    shown += 1
            previous = frame
    except KeyboardInterrupt:
        print("\nStopped.")

    print("\n---- summary ----")
    print("frames read .... %d" % frames)
    print("timeouts ....... %d" % timeouts)
    print("other errors ... %d" % other_errors)

    if frames == 0:
        print("\nNothing arrived. The IMU is idle until told to start.")
        print("Try:  --probe        (fires a few guessed wake-up patterns)")
        print("Then: capture the Windows SDK traffic to find the real command.")
    else:
        print("\nData confirmed. Copy the frames above into the chat and")
        print("we will work out which bytes are the gyro axes.")

    lib.libusb_release_interface(handle, opts["iface"])
    lib.libusb_close(handle)
    lib.libusb_exit(ctx)


if __name__ == "__main__":
    main()
