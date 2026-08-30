#!/usr/bin/env python3
"""
rayneo_head.py - RayNeo Air 4 Pro head tracking for Android. No root.

Reads the glasses' IMU over USB, turns it into head orientation, and
drives either a virtual mouse (for mouse-look in a streamed PC game)
or absolute angles (for a pinned virtual screen).

Switch modes while it runs by typing a letter and pressing enter:

    m   mouse mode   - head motion moves the cursor
    s   screen mode  - absolute pitch/yaw/roll, no cursor
    r   recentre     - zero the angles / reset drift
    c   recalibrate  - hold still, re-learn the gyro bias
    q   quit

    termux-usb -r -e "python -u rayneo_head.py" /dev/bus/usb/001/002

Options:
    --mode mouse|screen   starting mode            (default screen)
    --sens 12             mouse pixels per degree  (default 12)
    --deadzone 2.0        deg/s treated as zero    (default 2.0)
    --smooth 0.35         0 none .. 0.9 heavy      (default 0.35)
    --calib 2             startup calibration secs (default 2)
    --invert-x            reverse horizontal
    --invert-y            reverse vertical
    --udp host:port       also emit as UDP text    (default off)
    --quiet               no per-frame printing in mouse mode

Requires uinput_mouse.py in the same folder for mouse mode.
"""

import os
import sys
import time
import select
import struct
import socket
import ctypes
import ctypes.util

NO_DISCOVERY = 2
ENABLE = [0x66, 0x01]

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from uinput_mouse import VirtualMouse
    HAVE_MOUSE = True
except Exception as e:
    HAVE_MOUSE = False
    MOUSE_ERR = str(e)


# ----------------------------------------------------------------- USB layer

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
    ax, ay, az, gx, gy, gz, temp = struct.unpack_from("<7f", frame, 4)
    # measured head axes: pitch = X, yaw = Y+Z, roll = Y-Z
    return (ax, ay, az), (gx, gy + gz, gy - gz), temp


# ------------------------------------------------------------------ tracking

class Tracker:
    def __init__(self, deadzone, smooth):
        self.deadzone = deadzone
        self.smooth = smooth
        self.bias = [0.0, 0.0, 0.0]
        self.angle = [0.0, 0.0, 0.0]
        self.rate = [0.0, 0.0, 0.0]
        self.still_since = None

    def calibrate(self, samples):
        n = len(samples)
        for i in range(3):
            self.bias[i] = sum(s[i] for s in samples) / n
        return max(max(s[i] for s in samples) - min(s[i] for s in samples)
                   for i in range(3))

    def update(self, raw, dt):
        moving = False
        for i in range(3):
            r = raw[i] - self.bias[i]
            if abs(r) < self.deadzone:
                r = 0.0
            else:
                moving = True
            self.rate[i] = self.rate[i] * self.smooth + r * (1.0 - self.smooth)
            self.angle[i] += self.rate[i] * dt

        now = time.time()
        if moving:
            self.still_since = None
        else:
            if self.still_since is None:
                self.still_since = now
            elif now - self.still_since > 1.0:
                for i in range(3):
                    self.bias[i] += (raw[i] - self.bias[i]) * 0.02
                    self.rate[i] = 0.0
        return self.angle, self.rate

    def recentre(self):
        self.angle = [0.0, 0.0, 0.0]


def collect(lib, h, seconds):
    out = []
    end = time.time() + seconds
    while time.time() < end:
        send(lib, h, ENABLE)
        f = read(lib, h)
        if f and len(f) >= 32 and f[1] == 0x65:
            _, rates, _ = unpack(f)
            out.append(rates)
    return out


def key_waiting():
    """Non-blocking single-line read from stdin, returns '' if nothing typed."""
    try:
        r, _, _ = select.select([sys.stdin], [], [], 0)
    except (ValueError, OSError):
        return ""
    if not r:
        return ""
    line = sys.stdin.readline()
    return line.strip().lower()


# ---------------------------------------------------------------------- main

def main():
    argv = sys.argv[1:]
    digits = [a for a in argv if a.isdigit()]
    if not digits:
        sys.exit("No descriptor. Launch through termux-usb -r -e.")
    fd = int(digits[-1])

    def opt(name, d):
        return argv[argv.index(name) + 1] if name in argv else d

    mode = opt("--mode", "screen")
    sens = float(opt("--sens", "12"))
    deadzone = float(opt("--deadzone", "2.0"))
    smooth = float(opt("--smooth", "0.35"))
    calib_s = float(opt("--calib", "2"))
    inv_x = -1.0 if "--invert-x" in argv else 1.0
    inv_y = -1.0 if "--invert-y" in argv else 1.0
    quiet = "--quiet" in argv
    udp = opt("--udp", None)

    sock = target = None
    if udp:
        host, port = udp.split(":")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        target = (host, int(port))

    lib = load()
    ctx, h = open_handle(lib, fd)
    lib.libusb_set_auto_detach_kernel_driver(h, 1)
    if lib.libusb_claim_interface(h, 0) != 0:
        sys.exit("could not claim interface 0")

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

    mouse = None
    if HAVE_MOUSE:
        try:
            mouse = VirtualMouse().open()
        except SystemExit as e:
            print("mouse unavailable: %s" % e, flush=True)
            mouse = None
    else:
        print("uinput_mouse.py not found - screen mode only", flush=True)

    trk = Tracker(deadzone, smooth)
    print("\nCalibrating %.0fs - PUT THEM DOWN, DO NOT TOUCH" % calib_s, flush=True)
    samples = collect(lib, h, calib_s)
    if len(samples) < 20:
        sys.exit("too few calibration samples")
    spread = trk.calibrate(samples)
    print("  %d samples, bias %+.2f %+.2f %+.2f, spread %.2f"
          % (len(samples), trk.bias[0], trk.bias[1], trk.bias[2], spread), flush=True)
    if spread > 8:
        print("  they moved during calibration - press c to redo", flush=True)

    print("\n  m mouse   s screen   r recentre   c recalibrate   q quit")
    print("  mode: %s   sens %.0f px/deg   deadzone %.1f\n" % (mode, sens, deadzone),
          flush=True)

    # fractional pixel carry: without this a slow turn rounds to zero every tick
    carry_x = carry_y = 0.0
    last_t = time.time()
    last_print = 0.0
    frames = 0
    moved_px = 0.0

    try:
        while True:
            cmd = key_waiting()
            if cmd:
                if cmd.startswith("q"):
                    break
                elif cmd.startswith("m"):
                    if mouse:
                        mode = "mouse"
                        carry_x = carry_y = 0.0
                        print(">>> mouse mode", flush=True)
                    else:
                        print(">>> mouse unavailable", flush=True)
                elif cmd.startswith("s"):
                    mode = "screen"
                    print(">>> screen mode", flush=True)
                elif cmd.startswith("r"):
                    trk.recentre()
                    print(">>> recentred", flush=True)
                elif cmd.startswith("c"):
                    print(">>> hold still...", flush=True)
                    sp = trk.calibrate(collect(lib, h, calib_s))
                    trk.recentre()
                    print(">>> bias %+.2f %+.2f %+.2f, spread %.2f"
                          % (trk.bias[0], trk.bias[1], trk.bias[2], sp), flush=True)
                    last_t = time.time()

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

            _, rates, temp = unpack(f)
            angle, rate = trk.update(rates, dt)

            if mode == "mouse" and mouse:
                carry_x += -inv_x * rate[1] * dt * sens
                carry_y += -inv_y * rate[0] * dt * sens
                dx = int(carry_x)
                dy = int(carry_y)
                carry_x -= dx
                carry_y -= dy
                if dx or dy:
                    mouse.move(dx, dy)
                    moved_px += abs(dx) + abs(dy)
                if not quiet and now - last_print > 0.1:
                    print("  mouse  dx %+5d  dy %+5d   yaw rate %+7.1f"
                          % (dx, dy, rate[1]), flush=True)
                    last_print = now
            else:
                if now - last_print > 0.07:
                    print("  pitch %+7.2f   yaw %+7.2f   roll %+7.2f   %.1fC"
                          % (angle[0], angle[1], angle[2], temp), flush=True)
                    last_print = now

            if sock:
                msg = ("A %.3f %.3f %.3f" % tuple(angle)) if mode != "mouse" \
                      else ("M %.3f %.3f" % (carry_x, carry_y))
                try:
                    sock.sendto(msg.encode(), target)
                except OSError:
                    pass
    except KeyboardInterrupt:
        pass

    print("\nframes %d   cursor moved %.0f px total" % (frames, moved_px))
    print("final  pitch %.1f  yaw %.1f  roll %.1f" % tuple(trk.angle))
    if mouse:
        mouse.close()
    lib.libusb_release_interface(h, 0)
    lib.libusb_close(h)
    lib.libusb_exit(ctx)


if __name__ == "__main__":
    main()
