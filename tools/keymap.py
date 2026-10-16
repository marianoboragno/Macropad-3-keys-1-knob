#!/usr/bin/env python3
"""
Keymap compiler for MacroPad (CH552).
Compiles a JSON keymap definition file into a 128-byte EEPROM / Data Flash binary.

Author (2026): Mariano Boragno (refer to Git history for details)
License: GNU General Public License v3.0 (GPLv3)
"""
import json
import os
import sys

MODIFIERS = {
    "none": 0x00,
    "ctrl": 0x01, "lctrl": 0x01, "control": 0x01,
    "shift": 0x02, "lshift": 0x02,
    "alt": 0x04, "lalt": 0x04,
    "gui": 0x08, "lgui": 0x08, "win": 0x08, "cmd": 0x08, "super": 0x08,
    "rctrl": 0x10,
    "rshift": 0x20,
    "ralt": 0x40, "altgr": 0x40,
    "rgui": 0x80, "rwin": 0x80, "rcmd": 0x80,
}

KEYCODES = {
    # Letters
    "a": 0x04, "b": 0x05, "c": 0x06, "d": 0x07, "e": 0x08, "f": 0x09,
    "g": 0x0A, "h": 0x0B, "i": 0x0C, "j": 0x0D, "k": 0x0E, "l": 0x0F,
    "m": 0x10, "n": 0x11, "o": 0x12, "p": 0x13, "q": 0x14, "r": 0x15,
    "s": 0x16, "t": 0x17, "u": 0x18, "v": 0x19, "w": 0x1A, "x": 0x1B,
    "y": 0x1C, "z": 0x1D,
    # Numbers
    "1": 0x1E, "2": 0x1F, "3": 0x20, "4": 0x21, "5": 0x22,
    "6": 0x23, "7": 0x24, "8": 0x25, "9": 0x26, "0": 0x27,
    # Controls & Whitespace
    "enter": 0x28, "return": 0x28,
    "esc": 0x29, "escape": 0x29,
    "backspace": 0x2A,
    "tab": 0x2B,
    "space": 0x2C, "spacebar": 0x2C,
    "minus": 0x2D, "-": 0x2D,
    "equal": 0x2E, "=": 0x2E,
    "bracket_left": 0x2F, "[": 0x2F,
    "bracket_right": 0x30, "]": 0x30,
    "backslash": 0x31, "\\": 0x31,
    "semicolon": 0x33, ";": 0x33,
    "quote": 0x34, "'": 0x34,
    "grave": 0x35, "`": 0x35, "~": 0x35,
    "comma": 0x36, ",": 0x36,
    "dot": 0x37, ".": 0x37,
    "slash": 0x38, "/": 0x38,
    "capslock": 0x39, "caps": 0x39,
    # Function keys
    "f1": 0x3A, "f2": 0x3B, "f3": 0x3C, "f4": 0x3D, "f5": 0x3E, "f6": 0x3F,
    "f7": 0x40, "f8": 0x41, "f9": 0x42, "f10": 0x43, "f11": 0x44, "f12": 0x45,
    # Navigation & Edit
    "printscreen": 0x46, "prtsc": 0x46,
    "scrolllock": 0x47,
    "pause": 0x48,
    "insert": 0x49,
    "home": 0x4A,
    "pageup": 0x4B, "pgup": 0x4B,
    "delete": 0x4C, "del": 0x4C,
    "end": 0x4D,
    "pagedown": 0x4E, "pgdn": 0x4E,
    "right": 0x4F, "arrow_right": 0x4F,
    "left": 0x50, "arrow_left": 0x50,
    "down": 0x51, "arrow_down": 0x51,
    "up": 0x52, "arrow_up": 0x52,
}

CONSUMER_CODES = {
    "mute": 0x00E2,
    "volume_up": 0x00E9, "volup": 0x00E9, "vol_up": 0x00E9,
    "volume_down": 0x00EA, "voldown": 0x00EA, "vol_down": 0x00EA,
    "play_pause": 0x00CD, "play": 0x00CD, "pause": 0x00CD,
    "next_track": 0x00B5, "next": 0x00B5,
    "prev_track": 0x00B6, "prev": 0x00B6, "previous": 0x00B6,
    "stop": 0x00B7,
    "eject": 0x00B8,
    "brightness_up": 0x006F,
    "brightness_down": 0x0070,
    "media_player": 0x0183, "media": 0x0183,
    "calculator": 0x0192, "calc": 0x0192,
    "browser": 0x0223, "browser_home": 0x0223, "home_page": 0x0223,
    "browser_back": 0x0224,
    "browser_forward": 0x0225,
    "browser_refresh": 0x0227,
    "browser_bookmarks": 0x022A,
}

SLOT_ALIASES = [
    ("key1", ["key1", "k1", "1", "left"]),
    ("key2", ["key2", "k2", "2", "middle", "center"]),
    ("key3", ["key3", "k3", "3", "right"]),
    ("knob_switch", ["knob_switch", "knob_sw", "knob_click", "knob_button", "knob_btn", "enc_sw"]),
    ("knob_cw", ["knob_cw", "knob_right", "enc_cw", "cw"]),
    ("knob_ccw", ["knob_ccw", "knob_left", "enc_ccw", "ccw"]),
]

DEFAULT_KEYMAP = {
    "key1": {"type": "keyboard", "mod": ["ctrl"], "key": "c"},
    "key2": {"type": "keyboard", "mod": ["ctrl"], "key": "v"},
    "key3": {"type": "keyboard", "mod": ["ctrl"], "key": "z"},
    "knob_switch": {"type": "consumer", "action": "mute"},
    "knob_cw": {"type": "consumer", "action": "volume_up"},
    "knob_ccw": {"type": "consumer", "action": "volume_down"},
}


def parse_keycode(val):
    if isinstance(val, int):
        return val & 0xFF
    if isinstance(val, str):
        v = val.strip().lower()
        if v.startswith("0x"):
            return int(v, 16) & 0xFF
        if v.isdigit():
            return int(v) & 0xFF
        if v in KEYCODES:
            return KEYCODES[v]
    raise ValueError(f"Unknown keycode: {val}")


def parse_modifiers(val):
    if isinstance(val, int):
        return val & 0xFF
    if isinstance(val, str):
        val = [val]
    if isinstance(val, list):
        mask = 0
        for item in val:
            if isinstance(item, int):
                mask |= (item & 0xFF)
            elif isinstance(item, str):
                v = item.strip().lower()
                if v.startswith("0x"):
                    mask |= int(v, 16)
                elif v in MODIFIERS:
                    mask |= MODIFIERS[v]
                else:
                    raise ValueError(f"Unknown modifier: {item}")
        return mask & 0xFF
    return 0


def parse_consumer(val):
    if isinstance(val, int):
        return val & 0xFFFF
    if isinstance(val, str):
        v = val.strip().lower()
        if v.startswith("0x"):
            return int(v, 16) & 0xFFFF
        if v.isdigit():
            return int(v) & 0xFFFF
        if v in CONSUMER_CODES:
            return CONSUMER_CODES[v]
    raise ValueError(f"Unknown consumer usage: {val}")


def compile_keymap(data):
    """
    Takes a dictionary or path to a JSON keymap and returns 128 bytes EEPROM data.
    """
    if isinstance(data, (str, os.PathLike)):
        with open(data, "r", encoding="utf-8") as f:
            data = json.load(f)

    eeprom = bytearray(128)

    for slot_idx, (canonical_name, aliases) in enumerate(SLOT_ALIASES):
        conf = None
        for alias in aliases:
            if alias in data:
                conf = data[alias]
                break

        if conf is None:
            conf = DEFAULT_KEYMAP[canonical_name]

        offset = slot_idx * 12
        ktype_str = str(conf.get("type", "keyboard")).strip().lower()

        if ktype_str == "keyboard":
            eeprom[offset] = 0  # KEYBOARD
            if "toggle" in conf:
                t = conf["toggle"]
                if len(t) < 2:
                    t = [t[0], t[0]]
                eeprom[offset + 1] = parse_modifiers(t[0].get("mod", []))
                eeprom[offset + 2] = parse_keycode(t[0].get("key", 0))
                eeprom[offset + 3] = parse_modifiers(t[1].get("mod", []))
                eeprom[offset + 4] = parse_keycode(t[1].get("key", 0))
            else:
                mod = parse_modifiers(conf.get("mod", []))
                key = parse_keycode(conf.get("key", 0))
                eeprom[offset + 1] = mod
                eeprom[offset + 2] = key
                eeprom[offset + 3] = mod
                eeprom[offset + 4] = key

        elif ktype_str in ("consumer", "media"):
            eeprom[offset] = 1  # CONSUMER
            if "toggle" in conf:
                t = conf["toggle"]
                c0 = parse_consumer(t[0])
                c1 = parse_consumer(t[1] if len(t) > 1 else t[0])
            else:
                action = conf.get("action", conf.get("key", 0))
                c0 = parse_consumer(action)
                c1 = c0
            eeprom[offset + 1] = c0 & 0xFF
            eeprom[offset + 2] = (c0 >> 8) & 0xFF
            eeprom[offset + 3] = c1 & 0xFF
            eeprom[offset + 4] = (c1 >> 8) & 0xFF

        elif ktype_str == "macro":
            eeprom[offset] = 2  # MACRO
            keys = conf.get("keys", [])
            if len(keys) > 10:
                keys = keys[:10]
            eeprom[offset + 1] = len(keys)
            for j, k in enumerate(keys):
                eeprom[offset + 2 + j] = parse_keycode(k)

        else:
            raise ValueError(f"Unknown key type '{ktype_str}' for slot '{canonical_name}'")

    return bytes(eeprom)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 tools/keymap.py <keymap.json> [output.bin]")
        sys.exit(1)

    json_file = sys.argv[1]
    out_file = sys.argv[2] if len(sys.argv) > 2 else "eeprom.bin"
    bin_data = compile_keymap(json_file)
    with open(out_file, "wb") as f:
        f.write(bin_data)
    print(f"[+] Compiled {json_file} -> {out_file} ({len(bin_data)} bytes)")
