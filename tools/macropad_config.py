#!/usr/bin/env python3
"""
MacroPad Runtime Keymap Configuration Tool
Sends real-time key remapping commands via USB HID (hidraw) to the MacroPad Mini (Report ID 0x04).
Supports updating all 6 slots from a JSON file or remapping individual keys from the CLI,
with options for permanent Data Flash (EEPROM) persistence or temporary RAM-only testing.

Author (2026): Mariano Boragno (refer to Git history for details)
License: GNU General Public License v3.0 (GPLv3)
"""

import sys
import os
import glob
import re
import time
import json
import argparse

# Allow importing helper definitions from keymap.py in the same directory
sys.path.insert(0, os.path.dirname(__file__))
from keymap import (
    SLOT_ALIASES,
    DEFAULT_KEYMAP,
    parse_keycode,
    parse_modifiers,
    parse_consumer,
    KEYCODES,
    CONSUMER_CODES,
    MODIFIERS,
)

VENDOR_ID = 0x1189
PRODUCT_ID = 0x8890
REPORT_ID = 0x04

# FLAGS bit definitions
FLAG_COMMIT_EEPROM = 0x01
FLAG_RESET_STATE   = 0x02

SLOT_NAME_TO_INDEX = {}
for idx, (canonical, aliases) in enumerate(SLOT_ALIASES):
    SLOT_NAME_TO_INDEX[canonical] = idx
    for alias in aliases:
        SLOT_NAME_TO_INDEX[alias] = idx


def find_macropad_hidraw():
    """Find the /dev/hidraw device path for the MacroPad."""
    for syspath in glob.glob("/sys/class/hidraw/hidraw*"):
        uevent_file = os.path.join(syspath, "device", "uevent")
        if os.path.exists(uevent_file):
            try:
                with open(uevent_file, "r") as f:
                    content = f.read()
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


def resolve_slot_index(val):
    """Resolve a slot name or number to an integer 0..5."""
    if isinstance(val, int):
        if 0 <= val <= 5:
            return val
        raise ValueError(f"Slot index out of range (0..5): {val}")

    val_str = str(val).strip().lower()
    if val_str.isdigit():
        idx = int(val_str)
        if 0 <= idx <= 5:
            return idx
        raise ValueError(f"Slot index out of range (0..5): {idx}")

    if val_str in SLOT_NAME_TO_INDEX:
        return SLOT_NAME_TO_INDEX[val_str]

    valid = ", ".join(f"'{s[0]}'" for s in SLOT_ALIASES)
    raise ValueError(f"Unknown slot '{val}'. Valid slots: {valid} or 0..5")


def compile_slot_payload(conf):
    """
    Compile a slot configuration dictionary into a 12-byte payload.
    Matches the EEPROM storage layout in 3keys_1knob.c.
    """
    payload = bytearray(12)
    ktype_str = str(conf.get("type", "keyboard")).strip().lower()

    if ktype_str == "keyboard":
        payload[0] = 0  # KEYBOARD
        if "toggle" in conf:
            t = conf["toggle"]
            if len(t) < 2:
                t = [t[0], t[0]]
            payload[1] = parse_modifiers(t[0].get("mod", []))
            payload[2] = parse_keycode(t[0].get("key", 0))
            payload[3] = parse_modifiers(t[1].get("mod", []))
            payload[4] = parse_keycode(t[1].get("key", 0))
        else:
            mod = parse_modifiers(conf.get("mod", []))
            key = parse_keycode(conf.get("key", 0))
            payload[1] = mod
            payload[2] = key
            payload[3] = mod
            payload[4] = key

    elif ktype_str in ("consumer", "media"):
        payload[0] = 1  # CONSUMER
        if "toggle" in conf:
            t = conf["toggle"]
            c0 = parse_consumer(t[0])
            c1 = parse_consumer(t[1] if len(t) > 1 else t[0])
        else:
            action = conf.get("action", conf.get("key", 0))
            c0 = parse_consumer(action)
            c1 = c0
        payload[1] = c0 & 0xFF
        payload[2] = (c0 >> 8) & 0xFF
        payload[3] = c1 & 0xFF
        payload[4] = (c1 >> 8) & 0xFF

    elif ktype_str == "macro":
        payload[0] = 2  # MACRO
        keys = conf.get("keys", [])
        if len(keys) > 10:
            keys = keys[:10]
        payload[1] = len(keys)
        for j, k in enumerate(keys):
            payload[2 + j] = parse_keycode(k)

    else:
        raise ValueError(f"Unknown key type '{ktype_str}'")

    return bytes(payload)


def format_slot_desc(payload):
    """Return a human-readable description of a 12-byte slot payload."""
    ktype = payload[0]
    if ktype == 0:  # KEYBOARD
        mod0 = payload[1]
        code0 = payload[2]
        mod1 = payload[3]
        code1 = payload[4]
        # Find key name
        k0_name = f"0x{code0:02X}"
        for name, code in KEYCODES.items():
            if code == code0:
                k0_name = name
                break
        mods0_list = [name for name, val in [("ctrl", 0x01), ("shift", 0x02), ("alt", 0x04), ("gui", 0x08)] if mod0 & val]
        combo0 = " + ".join(mods0_list + [k0_name]) if (mods0_list or code0) else "None"
        if (mod0 == mod1 and code0 == code1) or (code1 == 0 and mod1 == 0):
            return f"KEYBOARD [{combo0}]"
        else:
            k1_name = f"0x{code1:02X}"
            for name, code in KEYCODES.items():
                if code == code1:
                    k1_name = name
                    break
            mods1_list = [name for name, val in [("ctrl", 0x01), ("shift", 0x02), ("alt", 0x04), ("gui", 0x08)] if mod1 & val]
            combo1 = " + ".join(mods1_list + [k1_name])
            return f"KEYBOARD TOGGLE [{combo0} <-> {combo1}]"

    elif ktype == 1:  # CONSUMER
        c0 = payload[1] | (payload[2] << 8)
        c1 = payload[3] | (payload[4] << 8)
        c0_name = f"0x{c0:04X}"
        for name, code in CONSUMER_CODES.items():
            if code == c0:
                c0_name = name
                break
        if c0 == c1 or c1 == 0:
            return f"CONSUMER [{c0_name}]"
        else:
            c1_name = f"0x{c1:04X}"
            for name, code in CONSUMER_CODES.items():
                if code == c1:
                    c1_name = name
                    break
            return f"CONSUMER TOGGLE [{c0_name} <-> {c1_name}]"

    elif ktype == 2:  # MACRO
        count = payload[1]
        codes = [payload[2 + j] for j in range(count)]
        names = []
        for c in codes:
            kname = f"0x{c:02X}"
            for name, code in KEYCODES.items():
                if code == c:
                    kname = name
                    break
            names.append(kname)
        return f"MACRO [{', '.join(names)}]"

    return f"UNKNOWN (type {ktype})"


def send_slot_config(fd, slot_idx, payload, commit_eeprom=True, reset_state=True):
    """
    Construct and send a 16-byte Report ID 0x04 packet via hidraw.
    """
    report = bytearray(16)
    report[0] = REPORT_ID
    report[1] = slot_idx & 0xFF
    report[2:14] = payload[:12]
    report[14] = 0x00  # Reserved

    flags = 0
    if commit_eeprom:
        flags |= FLAG_COMMIT_EEPROM
    if reset_state:
        flags |= FLAG_RESET_STATE
    report[15] = flags

    os.write(fd, report)


def apply_keymap_file(device_path, json_path, commit_eeprom=True):
    """Load keymap JSON file and send reconfigurations for all 6 slots."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    mode_str = "Permanent (EEPROM + RAM)" if commit_eeprom else "Temporary (RAM-only)"
    print(f"[*] MacroPad Device: {device_path}")
    print(f"[*] Applying keymap: '{json_path}' [{mode_str}]")

    fd = os.open(device_path, os.O_WRONLY)
    try:
        for slot_idx, (canonical_name, aliases) in enumerate(SLOT_ALIASES):
            conf = None
            for alias in aliases:
                if alias in data:
                    conf = data[alias]
                    break
            if conf is None:
                conf = DEFAULT_KEYMAP[canonical_name]

            payload = compile_slot_payload(conf)
            send_slot_config(fd, slot_idx, payload, commit_eeprom=commit_eeprom)
            desc = format_slot_desc(payload)
            print(f"  - Slot {slot_idx} ({canonical_name:<12}): {desc}")
            time.sleep(0.015)  # 15ms delay for flash write cycles
    finally:
        os.close(fd)

    print("\n[+] All slots reconfigured successfully!")


def apply_single_slot(device_path, slot_name_or_idx, conf, commit_eeprom=True):
    """Configure a single slot from CLI parameters."""
    slot_idx = resolve_slot_index(slot_name_or_idx)
    canonical_name = SLOT_ALIASES[slot_idx][0]
    payload = compile_slot_payload(conf)

    mode_str = "Permanent (EEPROM + RAM)" if commit_eeprom else "Temporary (RAM-only)"
    print(f"[*] MacroPad Device: {device_path}")
    print(f"[*] Remapping Slot {slot_idx} ({canonical_name}) [{mode_str}]")

    fd = os.open(device_path, os.O_WRONLY)
    try:
        send_slot_config(fd, slot_idx, payload, commit_eeprom=commit_eeprom)
        desc = format_slot_desc(payload)
        print(f"  - Configuration: {desc}")
    finally:
        os.close(fd)

    print("[+] Slot updated successfully!")


def main():
    parser = argparse.ArgumentParser(
        description="Configure MacroPad key mappings in real-time over USB HID (Report ID 0x04).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Apply a full keymap from a JSON file:
  python3 tools/macropad_config.py keymap.json

  # Remap Key 1 to Ctrl+C permanently:
  python3 tools/macropad_config.py --slot key1 --key c --mod ctrl

  # Remap Key 2 to Alt+Tab temporarily (RAM-only, tests without flash wear):
  python3 tools/macropad_config.py --slot key2 --key tab --mod alt --temp

  # Remap Knob Switch to Play/Pause:
  python3 tools/macropad_config.py --slot knob_sw --type consumer --action play_pause

  # Remap Key 3 to a keystroke sequence macro:
  python3 tools/macropad_config.py --slot key3 --macro h,e,l,l,o,enter
"""
    )

    parser.add_argument("file", nargs="?", default=None,
                        help="Path to JSON keymap file to apply to all 6 slots.")
    parser.add_argument("-d", "--device", default=None,
                        help="Explicit /dev/hidrawX device path (auto-detected if omitted).")
    parser.add_argument("-s", "--slot", default=None,
                        help="Target slot name or index (key1, key2, key3, knob_sw, knob_cw, knob_ccw, or 0..5).")
    parser.add_argument("-t", "--type", choices=["keyboard", "consumer", "media", "macro"], default=None,
                        help="Key action type for single-slot remapping.")
    parser.add_argument("-k", "--key", default=None,
                        help="HID key name or code for keyboard mapping (e.g. 'c', 'v', 'f5', 'enter', '0x04').")
    parser.add_argument("-m", "--mod", default=None,
                        help="Comma-separated modifiers (ctrl, shift, alt, gui).")
    parser.add_argument("-a", "--action", default=None,
                        help="Consumer usage action name (mute, volume_up, volume_down, play_pause, etc.).")
    parser.add_argument("--macro", default=None,
                        help="Comma-separated list of keys for macro sequence (up to 10 keys).")
    parser.add_argument("--temp", "--ram-only", action="store_true",
                        help="RAM-only update: do NOT commit to Data Flash (reverts on reboot / unplug).")

    args = parser.parse_args()

    # Determine hidraw device
    dev_path = args.device or find_macropad_hidraw()
    if not dev_path:
        print("[ERROR] MacroPad device not found!")
        print("Please ensure the MacroPad is plugged in, or specify --device /dev/hidrawX.")
        print("Also check that tools/udev/99-macropad.rules is installed for non-root access.")
        sys.exit(1)

    commit_eeprom = not args.temp

    # If JSON file is provided
    if args.file:
        if not os.path.isfile(args.file):
            print(f"[ERROR] File not found: '{args.file}'")
            sys.exit(1)
        try:
            apply_keymap_file(dev_path, args.file, commit_eeprom=commit_eeprom)
        except Exception as e:
            print(f"[ERROR] Failed to apply keymap: {e}")
            sys.exit(1)
        return

    # If single slot remapping is requested
    if args.slot:
        conf = {}
        # Auto-detect or infer type
        ktype = args.type
        if not ktype:
            if args.macro:
                ktype = "macro"
            elif args.action:
                ktype = "consumer"
            else:
                ktype = "keyboard"
        conf["type"] = ktype

        if ktype == "keyboard":
            if not args.key:
                print("[ERROR] --key must be specified for keyboard mapping.")
                sys.exit(1)
            conf["key"] = args.key
            if args.mod:
                conf["mod"] = [m.strip() for m in args.mod.split(",")]

        elif ktype in ("consumer", "media"):
            action = args.action or args.key
            if not action:
                print("[ERROR] --action (e.g. 'mute', 'volume_up') must be specified for consumer mapping.")
                sys.exit(1)
            conf["action"] = action

        elif ktype == "macro":
            macro_str = args.macro or args.key
            if not macro_str:
                print("[ERROR] --macro (comma-separated keys) must be specified for macro mapping.")
                sys.exit(1)
            conf["keys"] = [k.strip() for k in macro_str.split(",")]

        try:
            apply_single_slot(dev_path, args.slot, conf, commit_eeprom=commit_eeprom)
        except Exception as e:
            print(f"[ERROR] Failed to remap slot: {e}")
            sys.exit(1)
        return

    # If neither file nor slot was given, print help
    parser.print_help()
    sys.exit(0)


if __name__ == "__main__":
    main()
