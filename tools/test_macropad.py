#!/usr/bin/env python3
"""
Diagnostic tool to monitor live input events from MacroPad (VID 0x1189, PID 0x8890).
Usage: sudo $(which python) tools/test_macropad.py

Author (2026): Mariano Boragno (refer to Git history for details)
License: GNU General Public License v3.0 (GPLv3)
"""
import selectors
import signal
import sys
import time
import evdev
from evdev import ecodes

# Track Ctrl+C presses to avoid quitting prematurely when testing Key 1 (Ctrl+C)
ctrl_c_count = 0
last_ctrl_c_time = 0.0


def sigint_handler(signum, frame):
    global ctrl_c_count, last_ctrl_c_time
    now = time.time()
    if now - last_ctrl_c_time < 1.5:
        ctrl_c_count += 1
    else:
        ctrl_c_count = 1
    last_ctrl_c_time = now

    if ctrl_c_count >= 3:
        print("\n\n[!] Exit requested (Ctrl+C pressed 3 times). Monitoring stopped.\n")
        sys.exit(0)
    else:
        remaining = 3 - ctrl_c_count
        print(f"\n[!] Notice: Ctrl+C received ({ctrl_c_count}/3). Press {remaining} more time{'s' if remaining > 1 else ''} quickly to exit.")


def main():
    signal.signal(signal.SIGINT, sigint_handler)

    print("=" * 60)
    print(" Searching for MacroPad interfaces (VID: 0x1189, PID: 0x8890)...")
    print("=" * 60)

    devices = []
    try:
        all_paths = evdev.list_devices()
    except PermissionError:
        print("\n[ERROR] Permission required to read /dev/input/event*.")
        print("Please run this diagnostic tool with sudo:")
        print("    sudo $(which python) tools/test_macropad.py\n")
        sys.exit(1)

    for path in all_paths:
        try:
            dev = evdev.InputDevice(path)
            if dev.info.vendor == 0x1189 and dev.info.product == 0x8890:
                devices.append(dev)
                print(f" [+] Found: {dev.path} -> {dev.name} (Phys: {dev.phys})")
        except Exception:
            continue

    if not devices:
        print("\n[!] No accessible MacroPad devices found with VID: 0x1189, PID: 0x8890.")
        print("Possible causes:")
        print(" 1. The MacroPad is not plugged in (or is currently in bootloader mode).")
        print(" 2. Root privileges are required to inspect raw input devices:")
        print("      sudo $(which python) tools/test_macropad.py\n")
        sys.exit(1)

    print("\n" + "-" * 60)
    print(" Monitoring live events...")
    print(" - Press switches, click the knob, and rotate the encoder.")
    print(" - To exit, press Ctrl+C 3 times rapidly (prevents accidental exit on Key 1).")
    print("-" * 60 + "\n")

    sel = selectors.DefaultSelector()
    for dev in devices:
        sel.register(dev, selectors.EVENT_READ)

    while True:
        for key, mask in sel.select():
            device = key.fileobj
            for event in device.read():
                if event.type == ecodes.EV_KEY:
                    key_name = ecodes.KEY.get(event.code, f"CODE_{event.code}")
                    if isinstance(key_name, (list, tuple)):
                        key_name = key_name[0]
                    status = "PRESSED (DOWN)" if event.value == 1 else ("RELEASED (UP)" if event.value == 0 else "REPEAT")
                    print(f"[{device.name}] KEY: {key_name:<15} ({status})")
                elif event.type == ecodes.EV_REL:
                    axis = ecodes.REL.get(event.code, f"REL_{event.code}")
                    if isinstance(axis, (list, tuple)):
                        axis = axis[0]
                    direction = "Clockwise / Positive" if event.value > 0 else "Counter-Clockwise / Negative"
                    print(f"[{device.name}] KNOB/REL: {axis:<12} val={event.value} ({direction})")
                elif event.type == ecodes.EV_SYN:
                    pass
                else:
                    print(f"[{device.name}] OTHER EVENT: type={event.type}, code={event.code}, val={event.value}")


if __name__ == "__main__":
    main()
