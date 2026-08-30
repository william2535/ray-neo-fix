#!/usr/bin/env python3
"""
uinput_mouse.py - create a virtual relative mouse via /dev/uinput.

On this handheld /dev/uinput is mode 666 and SELinux permits the open,
so no root is needed. Import this from the tracker, or run it directly
to self-test.

    python uinput_mouse.py            # draws a square with the cursor
    python uinput_mouse.py --probe    # create and destroy, report only

If UI_DEV_CREATE fails, SELinux is allowing the open but denying the
ioctl - the error is reported rather than swallowed.
"""

import os
import sys
import time
import fcntl
import struct
import ctypes

UINPUT = "/dev/uinput"

# linux/input-event-codes.h
EV_SYN, EV_KEY, EV_REL = 0x00, 0x01, 0x02
REL_X, REL_Y, REL_WHEEL = 0x00, 0x01, 0x08
BTN_LEFT, BTN_RIGHT, BTN_MIDDLE = 0x110, 0x111, 0x112
SYN_REPORT = 0

# ioctl numbers for uinput
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_RELBIT = 0x40045566
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502

BUS_USB = 0x03


class VirtualMouse:
    def __init__(self, name="RayNeo Head Mouse", vendor=0x1BBB, product=0xAF51):
        self.name = name
        self.vendor = vendor
        self.product = product
        self.fd = None

    def open(self):
        try:
            self.fd = os.open(UINPUT, os.O_WRONLY | os.O_NONBLOCK)
        except OSError as e:
            raise SystemExit("cannot open %s: %s" % (UINPUT, e))

        for code in (EV_KEY, EV_REL, EV_SYN):
            fcntl.ioctl(self.fd, UI_SET_EVBIT, code)
        for code in (REL_X, REL_Y, REL_WHEEL):
            fcntl.ioctl(self.fd, UI_SET_RELBIT, code)
        for code in (BTN_LEFT, BTN_RIGHT, BTN_MIDDLE):
            fcntl.ioctl(self.fd, UI_SET_KEYBIT, code)

        # struct uinput_user_dev: char name[80]; input_id id; ff_effects; abs arrays
        name = self.name.encode()[:79]
        dev = struct.pack(
            "80sHHHHi" + "i" * 64 * 4,
            name, BUS_USB, self.vendor, self.product, 1, 0,
            *([0] * (64 * 4))
        )
        os.write(self.fd, dev)

        try:
            fcntl.ioctl(self.fd, UI_DEV_CREATE)
        except OSError as e:
            os.close(self.fd)
            self.fd = None
            raise SystemExit(
                "UI_DEV_CREATE refused: %s\n"
                "The open succeeded but the kernel would not register the device.\n"
                "Mouse mode is not available; use --udp output instead." % e
            )
        time.sleep(0.3)   # give Android time to notice the new device
        return self

    def _emit(self, etype, code, value):
        # struct input_event: timeval (2x long), u16 type, u16 code, s32 value
        ev = struct.pack("llHHi", 0, 0, etype, code, value)
        os.write(self.fd, ev)

    def move(self, dx, dy):
        dx, dy = int(dx), int(dy)
        if dx:
            self._emit(EV_REL, REL_X, dx)
        if dy:
            self._emit(EV_REL, REL_Y, dy)
        if dx or dy:
            self._emit(EV_SYN, SYN_REPORT, 0)

    def click(self, button=BTN_LEFT):
        self._emit(EV_KEY, button, 1)
        self._emit(EV_SYN, SYN_REPORT, 0)
        self._emit(EV_KEY, button, 0)
        self._emit(EV_SYN, SYN_REPORT, 0)

    def scroll(self, amount):
        self._emit(EV_REL, REL_WHEEL, int(amount))
        self._emit(EV_SYN, SYN_REPORT, 0)

    def close(self):
        if self.fd is not None:
            try:
                fcntl.ioctl(self.fd, UI_DEV_DESTROY)
            except OSError:
                pass
            os.close(self.fd)
            self.fd = None


def main():
    probe = "--probe" in sys.argv
    print("opening %s ..." % UINPUT, flush=True)
    m = VirtualMouse().open()
    print("device created: '%s'" % m.name, flush=True)
    print("check with:  ls /dev/input/  (a new eventN should have appeared)", flush=True)

    if probe:
        m.close()
        print("destroyed. uinput works on this device.")
        return

    print("\nDrawing a square with the cursor - watch the screen.", flush=True)
    time.sleep(1.5)
    for label, dx, dy in (("right", 6, 0), ("down", 0, 6), ("left", -6, 0), ("up", 0, -6)):
        print("  %s" % label, flush=True)
        for _ in range(40):
            m.move(dx, dy)
            time.sleep(0.012)
        time.sleep(0.4)

    print("\nIf the cursor moved, head-to-mouse works with no root.")
    print("If nothing moved, the device registered but Android is ignoring it.")
    m.close()


if __name__ == "__main__":
    main()
