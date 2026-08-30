#!/usr/bin/env python3
"""
rayneo_tracker.py - turn RayNeo IMU frames into usable head tracking.

Frame layout (little-endian float32 from offset 4):
    4  accel X    8  accel Y   12  accel Z
   16  gyro X    20  gyro Y    24  gyro Z    28  temperature

Head axes, measured:
    pitch = gyroX
    yaw   = gyroY + gyroZ
    roll  = gyroY - gyroZ

Modes:
    screen   absolute angles in degrees - for a pinned virtual screen
    mouse    per-tick deltas - for driving a cursor
    raw      the three head rates, no integration

    termux-usb -r -e "python -u rayneo_tracker.py" /dev/bus/usb/001/002

Options:
    --mode screen     screen | mouse | raw          (default screen)
    --sens 8          mouse pixels per degree       (default 8)
    --deadzone 2.0    deg/s treated as zero         (default 2.0)
    --smooth 0.35     0 = none, 0.9 = heavy         (default 0.35)
    --calib 2         startup still-calibration secs(default 2)
    --udp 127.0.0.1:9000   also send as UDP text    (default off)
    --hz 15           lines printed per second      (default 15)
    --secs 0          run time, 0 = until Ctrl+C    (default 0)
"""

import sys
import time
import math
import struct
import socket
import ctypes
import ctypes.util

NO_DISCOVERY = 2
ENABLE = [0x66, 0x01]


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
    b = (ctypes.c_ubyte * len(payload))(*payload)
    return lib.libusb_control_transfer(
        h, ctypes.c_ubyte(0x21), ctypes.c_ubyte(0x09),
        ctypes.c_uint16(0x0301), ctypes.c_uint16(0),
        b, ctypes.c_uint16(len(payload)), ctypes.c_uint(600)
    )


def read(lib, h, timeout=100):
    b = (ctypes.c_ubyte * 64)()
    n = ctypes.c_int(0)
    rc = lib.libusb_interrupt_transfer(
        h, ctypes.c_ubyte(0x81), b, ctypes.c_int(64),
        ctypes.byref(n), ctypes.c_uint(timeout)
    )
    return bytes(b[:n.value]) if rc == 0 and n.value else None


def unpack(frame):
    """Return (accel xyz, head rates pitch/yaw/roll, temperature)."""
    v = struct.unpack_from("<7f", frame, 4)
    ax, ay, az, gx, gy, gz, temp = v
    return (ax, ay, az), (gx, gy + gz, gy - gz), temp


class Tracker:
    """Bias-corrected integration with a still-detector that re-learns bias."""

    def __init__(self, deadzone, smooth):
        self.deadzone = deadzone
        self.smooth = smooth
        self.bias = [0.0, 0.0, 0.0]
        self.angle = [0.0, 0.0, 0.0]
        self.rate = [0.0, 0.0, 0.0]
        self.still_since = None
        self.recentres = 0

    def calibrate(self, samples):
        n = len(samples)
        for i in range(3):
            self.bias[i] = sum(s[i] for s in samples) / n
        spread = max(
            max(s[i] for s in samples) - min(s[i] for s in samples)
            for i in range(3)
        )
        return spread

    def update(self, raw, dt):
        corrected = [raw[i] - self.bias[i] for i in range(3)]
        moving = False
        for i in range(3):
            r = corrected[i]
            if abs(r) < self.deadzone:
                r = 0.0
            else:
                moving = True
            # exponential smoothing on the rate, not the angle
            self.rate[i] = self.rate[i] * self.smooth + r * (1.0 - self.smooth)
            self.angle[i] += self.rate[i] * dt

        now = time.time()
        if moving:
            self.still_since = None
        else:
            if self.still_since is None:
                self.still_since = now
            elif now - self.still_since > 1.0:
                # held still for a second: nudge the bias toward the raw
                # reading so slow drift is continuously cancelled
                for i in range(3):
                    self.bias[i] += (raw[i] - self.bias[i]) * 0.02
                    self.rate[i] = 0.0
        return self.angle, self.rate

    def recentre(self):
        self.angle = [0.0, 0.0, 0.0]
        self.recentres += 1


def main():
    argv = sys.argv[1:]
    digits = [a for a in argv if a.isdigit()]
    if not digits:
        sys.exit("No descriptor. Launch through termux-usb -r -e.")
    fd = int(digits[-1])

    def opt(name, d):
        return argv[argv.index(name) + 1] if name in argv else d

    mode = opt("--mode", "screen")
    sens = float(opt("--sens", "8"))
    deadzone = float(opt("--deadzone", "2.0"))
    smooth = float(opt("--smooth", "0.35"))
    calib_s = float(opt("--calib", "2"))
    hz = float(opt("--hz", "15"))
    run_s = float(opt("--secs", "0"))
    udp = opt("--udp", None)

    sock = None
    if udp:
        host, port = udp.split(":")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        target = (host, int(port))

    lib = load()
    ctx, h = open_handle(lib, fd)
    lib.libusb_set_auto_detach_kernel_driver(h, 1)
    rc = lib.libusb_claim_interface(h, 0)
    if rc != 0:
        sys.exit("claim failed: %d" % rc)

    live = False
    for _ in range(20):
        send(lib, h, ENABLE)
        f = read(lib, h, 60)
        if f and len(f) >= 32 and f[1] == 0x65:
            live = True
            break
        time.sleep(0.02)
    if not live:
        sys.exit("no sensor frames - unplug, replug, retry")

    trk = Tracker(deadzone, smooth)

    print("Calibrating %.0fs - PUT THEM DOWN AND DO NOT TOUCH" % calib_s, flush=True)
    samples = []
    end = time.time() + calib_s
    while time.time() < end:
        send(lib, h, ENABLE)
        f = read(lib, h)
        if f and len(f) >= 32 and f[1] == 0x65:
            _, rates, _ = unpack(f)
            samples.append(rates)
    if len(samples) < 20:
        sys.exit("too few calibration samples (%d)" % len(samples))
    spread = trk.calibrate(samples)
    print("  %d samples, bias %+.2f %+.2f %+.2f, spread %.2f"
          % (len(samples), trk.bias[0], trk.bias[1], trk.bias[2], spread), flush=True)
    if spread > 8:
        print("  WARNING: they moved during calibration. Restart for a clean bias.",
              flush=True)

    print("\nmode: %s   deadzone %.1f deg/s   smoothing %.2f" % (mode, deadzone, smooth))
    if mode == "screen":
        print("Turn your head - angles should hold when you stop.")
        print("      pitch     yaw    roll    temp", flush=True)
    elif mode == "mouse":
        print("Cursor deltas at %.0f px per degree." % sens)
        print("         dx      dy   |  yaw rate  pitch rate", flush=True)
    else:
        print("Raw head rates, deg/s.")
        print("      pitch     yaw    roll", flush=True)

    gap = 1.0 / hz
    last_print = 0.0
    last_t = time.time()
    stop = time.time() + run_s if run_s > 0 else None
    frames = 0

    try:
        while True:
            if stop and time.time() > stop:
                break
            send(lib, h, ENABLE)
            f = read(lib, h)
            if not (f and len(f) >= 32 and f[1] == 0x65):
                continue
            now = time.time()
            dt = now - last_t
            last_t = now
            if dt <= 0 or dt > 0.5:
                continue
            frames += 1

            accel, rates, temp = unpack(f)
            angle, rate = trk.update(rates, dt)

            if now - last_print < gap:
                continue
            last_print = now

            if mode == "screen":
                line = "  %8.2f %7.2f %7.2f  %5.1f" % (angle[0], angle[1], angle[2], temp)
            elif mode == "mouse":
                dx = -rate[1] * dt * sens
                dy = -rate[0] * dt * sens
                line = "  %9.2f %7.2f   | %8.2f %9.2f" % (dx, dy, rate[1], rate[0])
            else:
                line = "  %8.2f %7.2f %7.2f" % (rate[0], rate[1], rate[2])

            print(line, flush=True)
            if sock:
                if mode == "mouse":
                    msg = "M %.3f %.3f" % (-rate[1] * dt * sens, -rate[0] * dt * sens)
                else:
                    msg = "A %.3f %.3f %.3f" % (angle[0], angle[1], angle[2])
                try:
                    sock.sendto(msg.encode(), target)
                except OSError:
                    pass
    except KeyboardInterrupt:
        print("\nstopped", flush=True)

    print("\nframes %d   final angles  pitch %.1f  yaw %.1f  roll %.1f"
          % (frames, trk.angle[0], trk.angle[1], trk.angle[2]))
    print("bias drift corrections applied continuously while still")

    lib.libusb_release_interface(h, 0)
    lib.libusb_close(h)
    lib.libusb_exit(ctx)


if __name__ == "__main__":
    main()
