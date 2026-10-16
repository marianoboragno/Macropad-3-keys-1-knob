#!/usr/bin/env python3
"""
MacroPad RGB LED Controller
Sends autonomous animation/color commands via USB HID (hidraw) to the MacroPad Mini.

Author (2026): Mariano Boragno (refer to Git history for details)
License: GNU General Public License v3.0 (GPLv3)
"""

import sys
import os
import glob
import re
import argparse

VENDOR_ID = 0x1189
PRODUCT_ID = 0x8890
REPORT_ID = 0x03

MODE_OFF = 0
MODE_SOLID = 1
MODE_BREATHE = 2
MODE_BLINK = 3
MODE_REACTIVE = 4

NAMED_COLORS = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "cyan": (0, 255, 255),
    "magenta": (255, 0, 255),
    "purple": (180, 0, 255),
    "orange": (255, 120, 0),
    "pink": (255, 50, 150),
    "white": (255, 255, 255),
    "warmwhite": (255, 200, 100),
    "off": (0, 0, 0),
}


def find_macropad_hidraw():
    """Find the /dev/hidraw device path for the MacroPad."""
    for syspath in glob.glob("/sys/class/hidraw/hidraw*"):
        uevent_file = os.path.join(syspath, "device", "uevent")
        if os.path.exists(uevent_file):
            try:
                with open(uevent_file, "r") as f:
                    content = f.read()
                    # Example: HID_ID=0003:00001189:00008890
                    match = re.search(r"HID_ID=[0-9A-Fa-f]+:([0-9A-Fa-f]{8}):([0-9A-Fa-f]{8})", content)
                    if match:
                        vid = int(match.group(1), 16)
                        pid = int(match.group(2), 16)
                        if vid == VENDOR_ID and pid == PRODUCT_ID:
                            hidraw_name = os.path.basename(syspath)
                            dev_path = os.path.join("/dev", hidraw_name)
                            if os.path.exists(dev_path):
                                return dev_path
            except Exception:
                continue
    return None


def parse_color(color_str):
    """Parse color from name, hex (#RRGGBB or RRGGBB), or comma-separated R,G,B."""
    if not color_str:
        return (0, 0, 0)
    c = color_str.strip().lower()
    if c in NAMED_COLORS:
        return NAMED_COLORS[c]

    if c.startswith("#"):
        c = c[1:]
    elif c.startswith("0x"):
        c = c[2:]

    if len(c) == 6:
        try:
            r = int(c[0:2], 16)
            g = int(c[2:4], 16)
            b = int(c[4:6], 16)
            return (r, g, b)
        except ValueError:
            pass

    if "," in c:
        parts = [int(p.strip()) for p in c.split(",")]
        if len(parts) == 3:
            return (
                max(0, min(255, parts[0])),
                max(0, min(255, parts[1])),
                max(0, min(255, parts[2]))
            )

    raise ValueError(f"Unrecognized color: '{color_str}'. Use a color name ('red', 'blue'), hex ('#00FF00', 'AAFF00'), or 'R,G,B'.")


def parse_period(period_str):
    """Parse period duration to milliseconds (e.g. '4s', '500ms', '2.5s', '3000')."""
    if not period_str:
        return 2000
    p = str(period_str).strip().lower()
    if p.endswith("ms"):
        return max(50, min(65535, int(float(p[:-2]))))
    elif p.endswith("s"):
        return max(50, min(65535, int(float(p[:-1]) * 1000)))
    else:
        # Default assume seconds if small or ms if large
        val = float(p)
        if val <= 30.0:
            return max(50, min(65535, int(val * 1000)))
        else:
            return max(50, min(65535, int(val)))


def send_led_command(dev_path, led_idx, mode, r, g, b, period_ms):
    """Write 16-byte Report ID 3 to /dev/hidraw device."""
    packet = bytearray(16)
    packet[0] = REPORT_ID
    packet[1] = led_idx & 0xFF
    packet[2] = mode & 0xFF
    packet[3] = r & 0xFF
    packet[4] = g & 0xFF
    packet[5] = b & 0xFF
    packet[6] = (period_ms >> 8) & 0xFF
    packet[7] = period_ms & 0xFF
    # bytes 8..15 remain 0

    with open(dev_path, "wb") as f:
        f.write(packet)


def main():
    parser = argparse.ArgumentParser(
        description="Autonomous RGB LED controller for MacroPad Mini (CH552G)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Usage examples:
  %(prog)s 1 --solid green
  %(prog)s 2 --breathe 4s "#0022FA"
  %(prog)s 3 --blink 1s red
  %(prog)s all --breathe 3s purple     # Synchronizes all 3 LEDs in phase
  %(prog)s all --reactive              # Key-press reactive mode
  %(prog)s all --off                   # Turn off all LEDs
        """
    )

    parser.add_argument("target", choices=["1", "2", "3", "all"],
                        help="Target LED (1, 2, 3 or 'all')")

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--solid", nargs="?", const="white", metavar="COLOR",
                            help="Static solid color mode. Optional color (default: white)")
    mode_group.add_argument("--breathe", nargs="*", metavar=("TIME", "COLOR"),
                            help="Smooth breathing mode. Optional parameters: [time] [color] (e.g. 4s '#0022FA')")
    mode_group.add_argument("--blink", nargs="*", metavar=("TIME", "COLOR"),
                            help="Blinking mode. Optional parameters: [time] [color] (e.g. 1s red)")
    mode_group.add_argument("--reactive", nargs="?", const="default", metavar="COLOR",
                            help="Reactive mode on key press (default: base R/G/B colors)")
    mode_group.add_argument("--off", action="store_true",
                            help="Turn off LED(s)")

    parser.add_argument("--period", "-p", metavar="TIME",
                        help="Period duration (e.g. '4s', '500ms', '2.5s'). Default: 2s")
    parser.add_argument("--color", "-c", metavar="COLOR",
                        help="Explicit color (e.g. '#FF00AA', 'cyan', '255,100,0')")

    args = parser.parse_args()

    # Determine target index (0-indexed or 0xFF)
    if args.target == "all":
        target_idx = 0xFF
        target_name = "ALL LEDs (1, 2, and 3)"
    else:
        target_idx = int(args.target) - 1
        target_name = f"LED {args.target}"

    dev_path = find_macropad_hidraw()
    if not dev_path:
        print(f"[!] Error: MacroPad device not found (VID: {VENDOR_ID:#06x}, PID: {PRODUCT_ID:#06x}).")
        print("    Please check that the device is connected via USB.")
        sys.exit(1)

    if not os.access(dev_path, os.W_OK):
        print(f"[!] Permission denied when writing to {dev_path}.")
        print("    Install the udev rule to allow non-root access:")
        print("      sudo cp tools/udev/99-macropad.rules /etc/udev/rules.d/")
        print("      sudo udevadm control --reload-rules && sudo udevadm trigger")
        print("    Or run this script temporarily with sudo.")
        sys.exit(1)

    # Determine mode, color and period
    mode = MODE_OFF
    color = (0, 0, 0)
    period_ms = 2000

    if args.period:
        period_ms = parse_period(args.period)

    if args.off:
        mode = MODE_OFF
        color = (0, 0, 0)
        mode_desc = "OFF"

    elif args.solid is not None:
        mode = MODE_SOLID
        c_str = args.color or args.solid
        color = parse_color(c_str)
        mode_desc = f"SOLID ({color[0]}, {color[1]}, {color[2]})"

    elif args.breathe is not None:
        mode = MODE_BREATHE
        # breathe can receive: [] (defaults), [time], [color], [time, color], [color, time]
        items = args.breathe
        c_str = args.color
        if len(items) == 1:
            try:
                period_ms = parse_period(items[0])
            except Exception:
                c_str = items[0]
        elif len(items) >= 2:
            try:
                period_ms = parse_period(items[0])
                c_str = items[1]
            except Exception:
                period_ms = parse_period(items[1])
                c_str = items[0]
        color = parse_color(c_str or "white")
        mode_desc = f"BREATHE ({period_ms/1000:.1f}s, color: {color[0]}, {color[1]}, {color[2]})"

    elif args.blink is not None:
        mode = MODE_BLINK
        items = args.blink
        c_str = args.color
        if len(items) == 1:
            try:
                period_ms = parse_period(items[0])
            except Exception:
                c_str = items[0]
        elif len(items) >= 2:
            try:
                period_ms = parse_period(items[0])
                c_str = items[1]
            except Exception:
                period_ms = parse_period(items[1])
                c_str = items[0]
        color = parse_color(c_str or "white")
        mode_desc = f"BLINK ({period_ms/1000:.1f}s, color: {color[0]}, {color[1]}, {color[2]})"

    elif args.reactive is not None:
        mode = MODE_REACTIVE
        c_str = args.color or (args.reactive if args.reactive != "default" else None)
        if c_str:
            color = parse_color(c_str)
        else:
            color = (255, 255, 255)
        mode_desc = f"REACTIVE ({color[0]}, {color[1]}, {color[2]})"

    try:
        send_led_command(dev_path, target_idx, mode, color[0], color[1], color[2], period_ms)
        print(f"[+] Sent to {dev_path}: {target_name} -> {mode_desc}")
    except Exception as e:
        print(f"[!] Error sending command: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
