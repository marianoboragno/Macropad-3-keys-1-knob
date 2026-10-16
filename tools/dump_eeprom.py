#!/usr/bin/env python3
"""
Dump (read) CH552 Data Flash / EEPROM to a binary file.
Usage: sudo python3 tools/dump_eeprom.py [output_file.bin]

Author (2026): Mariano Boragno (refer to Git history for details)
License: GNU General Public License v3.0 (GPLv3)
"""
import sys
import time
import os
import subprocess
import usb.core

CH_VID = 0x4348
CH_PID = 0x55e0

def main():
    dump_file = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "eeprom_dump.bin")

    print("=" * 60)
    print(" CH552 EEPROM (Data Flash) Reader")
    print(f" Target file: {dump_file}")
    print("=" * 60)
    print("\n>>> WAITING for MacroPad in Bootloader mode (4348:55e0)...")
    print("    (Hold KEY 1 while plugging into USB, then release)")
    print("    Press Ctrl+C to cancel.\n")

    while True:
        try:
            dev = usb.core.find(idVendor=CH_VID, idProduct=CH_PID)
            if dev is not None:
                break
        except Exception:
            pass
        time.sleep(0.05)

    print("[+] MacroPad detected in Bootloader mode!")
    print(f"[*] Reading EEPROM to {dump_file}...")

    python_bin = sys.executable
    cmd = [python_bin, "-m", "ch55xtool", "-g", dump_file, "-v"]

    res = subprocess.run(cmd)
    if res.returncode == 0:
        print("\n" + "=" * 60)
        print(" EEPROM DUMP COMPLETED SUCCESSFULLY!")
        print(f" Saved to: {dump_file}")
        print("=" * 60 + "\n")
    else:
        print(f"\n[ERROR] Failed to read EEPROM (exit code {res.returncode})")

if __name__ == "__main__":
    main()
