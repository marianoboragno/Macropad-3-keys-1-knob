#!/usr/bin/env python3
"""
Automated flasher for MacroPad (CH552).
Flashes firmware and/or EEPROM keymap definitions with active wait for bootloader mode (4348:55e0).

Usage:
  python3 tools/flash.py                     # Flashes firmware (3keys_1knob.bin) AND keymap.json
  python3 tools/flash.py --skip-eeprom       # Flashes ONLY firmware binary
  python3 tools/flash.py --eeprom-only       # Flashes ONLY EEPROM keymap (skips firmware)
  python3 tools/flash.py -k my_keys.json     # Custom keymap file

Author (2026): Mariano Boragno (refer to Git history for details)
License: GNU General Public License v3.0 (GPLv3)
"""
import argparse
import os
import subprocess
import sys
import tempfile
import time
import usb.core
import usb.util

# Ensure current script directory is in sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
sys.path.insert(0, SCRIPT_DIR)

import chprog
from keymap import compile_keymap

CH_VID = 0x4348
CH_PID = 0x55e0


def check_ch55xtool_available():
    try:
        import ch55xtool  # noqa: F401
        return True
    except ImportError:
        # Also test executing as module with current interpreter
        res = subprocess.run([sys.executable, "-m", "ch55xtool", "--help"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return res.returncode == 0


def wait_for_bootloader():
    print("\n>>> WAITING for MacroPad in Bootloader mode (4348:55e0)...")
    print("    (Hold KEY 1 while plugging into USB, or bridge 1k resistor)")
    print("    Press Ctrl+C to cancel.\n")

    dev = None
    while True:
        try:
            dev = usb.core.find(idVendor=CH_VID, idProduct=CH_PID)
            if dev is not None:
                # Release USB resources so subprocess or chprog can re-open
                try:
                    usb.util.dispose_resources(dev)
                except Exception:
                    pass
                break
        except Exception:
            pass
        time.sleep(0.05)

    print("[+] Device detected in Bootloader mode!")
    print("[*] Flashing in:")
    for remaining in (3, 2, 1):
        print(f"    {remaining}...")
        time.sleep(1)


def flash_ch55xtool(bin_file=None, eeprom_bin=None):
    cmd_args = []
    if eeprom_bin:
        cmd_args.extend(["-d", eeprom_bin, "--verify_data"])
    if bin_file:
        cmd_args.extend(["-f", bin_file, "--verify_flash"])
    cmd_args.extend(["-r", "-v"])

    print(f"[*] Executing ISP command: python -m ch55xtool {' '.join(cmd_args)}")

    try:
        import ch55xtool.ch55xtool as ch55x

        # Patch __end_flash_ch5xx so it handles the immediate USB disconnection on reset cleanly
        orig_end = ch55x.__end_flash_ch5xx

        def safe_end(dev, restart_after=False):
            try:
                return orig_end(dev, restart_after=restart_after)
            except Exception:
                # The CH552 microcontroller resets immediately upon receiving the End command,
                # causing an expected USB read disconnect error in libusb as the device reboots.
                return True, None

        ch55x.__end_flash_ch5xx = safe_end
        old_argv = sys.argv
        try:
            sys.argv = ["ch55xtool"] + cmd_args
            ch55x.main()
        except SystemExit as se:
            if se.code not in (0, None):
                raise RuntimeError(f"ch55xtool exited with status {se.code}")
        finally:
            sys.argv = old_argv
            ch55x.__end_flash_ch5xx = orig_end

    except ImportError:
        res = subprocess.run([sys.executable, "-m", "ch55xtool"] + cmd_args)
        if res.returncode != 0:
            raise RuntimeError(f"ch55xtool exited with status {res.returncode}")


def flash_chprog(bin_file):
    print("[*] Starting flashing via chprog...")
    isp = chprog.Programmer()
    isp.detect()
    print(f"[+] Detected: {isp.chipname} (Bootloader v{isp.bootloader})")
    print("[*] Erasing program flash...")
    isp.erase()
    print(f"[*] Writing {bin_file}...")
    with open(bin_file, "rb") as f:
        data = f.read()
    isp.flash_data(data)
    print(f"[+] Written {len(data)} bytes successfully.")
    print("[*] Verifying flash data...")
    isp.verify_data(data)
    print(f"[+] Verification completed successfully ({len(data)} bytes)!")
    isp.exit()


def main():
    parser = argparse.ArgumentParser(
        description="Flash MacroPad CH552 firmware and/or EEPROM keymap.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("firmware_pos", nargs="?", default=None,
                        help="Optional firmware binary path (default: 3keys_1knob.bin)")
    parser.add_argument("-b", "--bin", default=None,
                        help="Firmware binary to flash (default: 3keys_1knob.bin)")
    parser.add_argument("-k", "--keymap", default=None,
                        help="Path to JSON keymap definition (default: keymap.json)")
    parser.add_argument("-s", "--skip-eeprom", action="store_true",
                        help="Skip EEPROM flashing (only flash firmware binary)")
    parser.add_argument("-e", "--eeprom-only", "--flash-eeprom-only", action="store_true",
                        help="Only flash EEPROM keymap (skip firmware binary)")

    args = parser.parse_args()

    # Determine firmware binary
    bin_file = args.bin or args.firmware_pos
    if not bin_file:
        # Search for 3keys_1knob.bin in current dir or project root
        candidates = [
            "3keys_1knob.bin",
            os.path.join(PROJECT_DIR, "3keys_1knob.bin"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                bin_file = c
                break

    # Determine keymap JSON file
    keymap_file = args.keymap
    if not keymap_file:
        candidates = [
            "keymap.json",
            os.path.join(PROJECT_DIR, "keymap.json"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                keymap_file = c
                break

    flash_fw = not args.eeprom_only
    flash_ee = not args.skip_eeprom

    if not flash_fw and not flash_ee:
        print("[ERROR] Both firmware and EEPROM flashing were disabled.")
        sys.exit(1)

    if flash_fw:
        if not bin_file or not os.path.isfile(bin_file):
            print(f"[ERROR] Firmware binary not found: {bin_file or '3keys_1knob.bin'}")
            print("Run 'make bin' first to build the firmware.")
            sys.exit(1)

    temp_ee_path = None
    if flash_ee:
        if not keymap_file or not os.path.isfile(keymap_file):
            print(f"[ERROR] Keymap JSON file not found: {keymap_file or 'keymap.json'}")
            sys.exit(1)

        print(f"[*] Compiling keymap from: {keymap_file}")
        try:
            ee_data = compile_keymap(keymap_file)
        except Exception as ex:
            print(f"[ERROR] Failed to parse {keymap_file}: {ex}")
            sys.exit(1)

        fd, temp_ee_path = tempfile.mkstemp(prefix="macropad_ee_", suffix=".bin")
        os.close(fd)
        with open(temp_ee_path, "wb") as f:
            f.write(ee_data)

    print("=" * 60)
    print(" MacroPad Unified Flasher")
    if flash_fw:
        print(f" -> Firmware: {bin_file}")
    if flash_ee:
        print(f" -> Keymap:   {keymap_file} (compiled 128-byte Data Flash)")
    print("=" * 60)

    try:
        has_tool = check_ch55xtool_available()

        if flash_ee and not has_tool:
            print("\n[ERROR] 'ch55xtool' is required for EEPROM flashing.")
            print("Please activate your virtualenv or install requirements:")
            print("    pip install -r tools/requirements.txt")
            print("Alternatively, pass --skip-eeprom to flash only the firmware.")
            sys.exit(1)

        wait_for_bootloader()

        if has_tool:
            target_fw = bin_file if flash_fw else None
            target_ee = temp_ee_path if flash_ee else None
            flash_ch55xtool(bin_file=target_fw, eeprom_bin=target_ee)
        else:
            # Fallback to chprog for firmware-only
            flash_chprog(bin_file)

        print("\n" + "=" * 60)
        print(" FLASH SUCCESSFUL!")
        print(" The MacroPad is now running with the updated configuration.")
        print("=" * 60 + "\n")

    except Exception as ex:
        print(f"\n[ERROR] Flashing failed: {ex}")
        sys.exit(1)
    finally:
        if temp_ee_path and os.path.isfile(temp_ee_path):
            try:
                os.remove(temp_ee_path)
            except OSError:
                pass


if __name__ == "__main__":
    main()
