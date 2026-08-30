#!/usr/bin/env python3
"""
rayneo_map.py - map the RayNeo command space properly.

We know the device answers every SET_REPORT on the control pipe, and that
01 66 returns a status block with a running clock in bytes 4-6. This walks
the command space and reports any command whose reply differs from that
baseline once the clock is masked out.

    termux-usb -r -e "python -u rayneo_map.py" /dev/bus/usb/001/002

Modes:
    (default)      sweep 01 XX for XX in 00-FF
    --first        sweep XX 01 for XX in 00-FF
    --both         run both sweeps
    --cmd 0166     single command, repeated, full 64-byte dump

Options:
    --tries 3      sends per command        (default 3)
    --mask 4-6     clock bytes to ignore    (default 4-6)
    --settle 30    ms to wait for the reply (default 30)
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


def send(lib, h, payload):
    buf = (ctypes.c_ubyte * len(payload))(*payload)
    return lib.libusb_control_transfer(
        h, ctypes.c_ubyte(0x21), ctypes.c_ubyte(0x09),
        ctypes.c_uint16(0x0301), ctypes.c_uint16(0),
        buf, ctypes.c_uint16(len(payload)), ctypes.c_uint(600)
    )


def read(lib, h, timeout):
    buf = (ctypes.c_ubyte * 64)()
    n = ctypes.c_int(0)
    rc = lib.libusb_interrupt_transfer(
        h, ctypes.c_ubyte(0x81), buf, ctypes.c_int(64),
        ctypes.byref(n), ctypes.c_uint(timeout)
    )
    return bytes(buf[:n.value]) if rc == 0 and n.value else None


def mask_clock(frame, mask):
    return bytes(0 if i in mask else b for i, b in enumerate(frame))


def parse_range(s):
    if "-" in s:
        a, b = s.split("-")
        return set(range(int(a), int(b) + 1))
    return {int(s)}


def parse_hex(s):
    s = s.replace(" ", "").replace(",", "")
    return [int(s[i:i + 2], 16) for i in range(0, len(s), 2)]


def brief(sig, n=20):
    return " ".join("%02X" % b for b in sig[:n])


def probe(lib, h, cmd, tries, settle, mask):
    """Send a command a few times, return the masked reply signature."""
    sigs = []
    for _ in range(tries):
        if send(lib, h, cmd) < 0:
            continue
        f = read(lib, h, settle)
        if f:
            sigs.append(mask_clock(f, mask))
        time.sleep(0.005)
    if not sigs:
        return None, 0
    # most common signature wins
    best = max(set(sigs), key=sigs.count)
    return best, len(sigs)


def sweep(lib, h, vary_first, baseline, tries, settle, mask):
    label = "XX 01" if vary_first else "01 XX"
    print("\n=== sweeping %s ===" % label)
    novel = []
    silent = []
    for b in range(256):
        cmd = [b, 0x01] if vary_first else [0x01, b]
        sig, n = probe(lib, h, cmd, tries, settle, mask)
        if sig is None:
            silent.append(b)
            continue
        if baseline is not None and sig == baseline:
            continue
        novel.append((b, sig))
        print("  %02X -> %s" % (b, brief(sig)))
    print("  novel replies: %d, silent: %d" % (len(novel), len(silent)))
    return novel


def main():
    argv = sys.argv[1:]
    digits = [a for a in argv if a.isdigit()]
    if not digits:
        sys.exit("No descriptor. Launch through termux-usb -r -e.")
    fd = int(digits[-1])

    def opt(name, default):
        return argv[argv.index(name) + 1] if name in argv else default

    tries = int(opt("--tries", "3"))
    settle = int(opt("--settle", "30"))
    mask = parse_range(opt("--mask", "4-6"))
    do_first = "--first" in argv or "--both" in argv
    do_second = "--first" not in argv or "--both" in argv
    single = parse_hex(opt("--cmd", "")) if "--cmd" in argv else None

    lib = load()
    ctx, h = open_handle(lib, fd)
    lib.libusb_set_auto_detach_kernel_driver(h, 1)
    rc = lib.libusb_claim_interface(h, 0)
    print("RayNeo command map")
    print("claim %s, mask %s, %d tries each\n"
          % ("ok" if rc == 0 else "failed", sorted(mask), tries))

    for _ in range(3):
        read(lib, h, 60)

    if single:
        print("Single command %s, 10 reads, full frame:\n" % brief(single, 8))
        for i in range(10):
            send(lib, h, single)
            f = read(lib, h, settle)
            if f:
                for row in range(0, len(f), 16):
                    print("   %04X  %s" % (row, " ".join("%02X" % x for x in f[row:row + 16])))
                print()
            time.sleep(0.05)
        lib.libusb_release_interface(h, 0)
        lib.libusb_close(h)
        lib.libusb_exit(ctx)
        return

    baseline, n = probe(lib, h, [0x01, 0x66], 5, settle, mask)
    if baseline is None:
        print("Baseline 01 66 gave no reply. Unplug, replug and retry.")
        return
    print("baseline (01 66), clock masked:")
    print("   %s\n" % brief(baseline, 24))

    found = []
    if do_second:
        found += sweep(lib, h, False, baseline, tries, settle, mask)
    if do_first:
        found += sweep(lib, h, True, baseline, tries, settle, mask)

    print("\n---- map summary ----")
    if found:
        print("%d command(s) replied differently from baseline." % len(found))
        print("Those are worth polling while moving your head.")
    else:
        print("Every command returned the same status block.")
        print("The command set is not reachable by guessing two bytes.")
        print("Next step would be capturing the Windows SDK traffic.")

    lib.libusb_release_interface(h, 0)
    lib.libusb_close(h)
    lib.libusb_exit(ctx)


if __name__ == "__main__":
    main()
