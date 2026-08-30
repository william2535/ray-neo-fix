#!/usr/bin/env python3
"""
rayneo_setup.py - install RayNeo head tracking as home screen shortcuts.

Run once. Creates:

    ~/.rayneo.conf              settings you can edit
    ~/.shortcuts/RayNeo Mouse   head-to-cursor
    ~/.shortcuts/RayNeo Screen  absolute angles
    ~/.shortcuts/RayNeo Tune    interactive, all controls
    ~/rayneo_launch.sh          shared wrapper: finds the device, runs the app

    python rayneo_setup.py

Then add the widget from your launcher. Requires Termux:Widget, installed
from GitHub with the same signature as Termux itself.
"""

import os
import sys
import stat
import json

HOME = os.path.expanduser("~")
SHORTCUTS = os.path.join(HOME, ".shortcuts")
CONF = os.path.join(HOME, ".rayneo.conf")
LAUNCH = os.path.join(HOME, "rayneo_launch.sh")

DEFAULT_CONF = {
    "sens": 25,
    "deadzone": 2.0,
    "smooth": 0.35,
    "calib": 2,
    "invert_x": False,
    "invert_y": False,
}

LAUNCHER = r'''#!/data/data/com.termux/files/usr/bin/bash
# RayNeo head tracking launcher.
# Finds the glasses whatever bus address they land on, then runs the app.
# Usage: rayneo_launch.sh <mode> [extra args]

MODE="${1:-screen}"
shift 2>/dev/null

cd "$HOME" || exit 1

# keep Android from suspending us mid-session
termux-wake-lock 2>/dev/null

cleanup() { termux-wake-unlock 2>/dev/null; }
trap cleanup EXIT

echo "RayNeo head tracking - $MODE mode"
echo

# --- find the device, retrying: it takes a moment to enumerate after plug-in
DEV=""
for i in 1 2 3 4 5 6; do
    DEV=$(termux-usb -l 2>/dev/null | grep -o '/dev/bus/usb/[0-9]*/[0-9]*' | head -1)
    if [ -n "$DEV" ]; then break; fi
    if [ "$i" = "1" ]; then echo "Waiting for the glasses..."; fi
    sleep 1
done

if [ -z "$DEV" ]; then
    echo
    echo "No RayNeo device found."
    echo "  - are the glasses plugged in?"
    echo "  - are they showing a picture?"
    echo "  - unplug, wait 3 seconds, plug back in"
    echo
    read -r -p "Press enter to close "
    exit 1
fi

echo "Found $DEV"
echo

# --- settings from ~/.rayneo.conf
SENS=$(grep -E '^\s*"sens"' "$HOME/.rayneo.conf" 2>/dev/null | grep -o '[0-9.]*' | tail -1)
DEAD=$(grep -E '^\s*"deadzone"' "$HOME/.rayneo.conf" 2>/dev/null | grep -o '[0-9.]*' | tail -1)
SMOOTH=$(grep -E '^\s*"smooth"' "$HOME/.rayneo.conf" 2>/dev/null | grep -o '[0-9.]*' | tail -1)
[ -z "$SENS" ] && SENS=25
[ -z "$DEAD" ] && DEAD=2.0
[ -z "$SMOOTH" ] && SMOOTH=0.35

INV=""
grep -q '"invert_x": *true' "$HOME/.rayneo.conf" 2>/dev/null && INV="$INV --invert-x"
grep -q '"invert_y": *true' "$HOME/.rayneo.conf" 2>/dev/null && INV="$INV --invert-y"

ARGS="--mode $MODE --sens $SENS --deadzone $DEAD --smooth $SMOOTH $INV $*"
echo "sens $SENS   deadzone $DEAD   smoothing $SMOOTH"
echo

termux-usb -r -e "python -u $HOME/rayneo_head.py $ARGS" "$DEV"
RC=$?

echo
if [ $RC -ne 0 ]; then
    echo "Exited with code $RC"
    read -r -p "Press enter to close "
fi
'''

SHORTCUT_MOUSE = r'''#!/data/data/com.termux/files/usr/bin/bash
exec "$HOME/rayneo_launch.sh" mouse --quiet
'''

SHORTCUT_SCREEN = r'''#!/data/data/com.termux/files/usr/bin/bash
exec "$HOME/rayneo_launch.sh" screen
'''

SHORTCUT_TUNE = r'''#!/data/data/com.termux/files/usr/bin/bash
# Interactive session - all keyboard controls available.
echo "Controls:  m mouse   s screen   r recentre   c recalibrate   q quit"
echo
exec "$HOME/rayneo_launch.sh" screen
'''


def write(path, content, executable=False):
    with open(path, "w") as f:
        f.write(content)
    if executable:
        st = os.stat(path)
        os.chmod(path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def main():
    print("RayNeo head tracking - setup\n")

    missing = []
    for f in ("rayneo_head.py", "uinput_mouse.py"):
        if not os.path.exists(os.path.join(HOME, f)):
            missing.append(f)
    if missing:
        print("Missing from your home folder: %s" % ", ".join(missing))
        print("Copy them across first, then run this again.")
        return 1

    if not os.path.exists(CONF):
        write(CONF, json.dumps(DEFAULT_CONF, indent=2) + "\n")
        print("created  ~/.rayneo.conf")
    else:
        print("kept     ~/.rayneo.conf  (yours, not overwritten)")

    write(LAUNCH, LAUNCHER, executable=True)
    print("created  ~/rayneo_launch.sh")

    os.makedirs(SHORTCUTS, exist_ok=True)
    try:
        os.chmod(SHORTCUTS, 0o700)
    except OSError:
        pass

    for name, body in (("RayNeo Mouse", SHORTCUT_MOUSE),
                       ("RayNeo Screen", SHORTCUT_SCREEN),
                       ("RayNeo Tune", SHORTCUT_TUNE)):
        write(os.path.join(SHORTCUTS, name), body, executable=True)
        print("created  ~/.shortcuts/%s" % name)

    print("""
Done.

NEXT
  1. Install Termux:Widget from GitHub - github.com/termux/termux-widget
     It must be the github-debug build, same as Termux and Termux:API,
     or Android will refuse it as a signature conflict.
  2. Long-press your home screen, choose Widgets, find Termux.
  3. Drop the widget on. It lists the three shortcuts.
  4. Tap one. Plug the glasses in first.

TUNING
  Edit ~/.rayneo.conf - no need to touch any commands:

      nano ~/.rayneo.conf

  sens      pixels per degree. Higher is faster. 25 is a good start.
  deadzone  deg/s ignored as noise. Raise if the cursor creeps.
  smooth    0 to 0.9. Raise if it feels jittery at high sens.
  invert_x  set true if left/right is backwards
  invert_y  set true if up/down is backwards

NOTES
  The device path is detected automatically, so it survives replugging.
  A wake lock is held while running so Android does not suspend it.
  Android may ask for USB permission the first time each session.
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
