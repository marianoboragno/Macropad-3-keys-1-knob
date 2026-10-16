# Project Backlog & Pending Tasks (TODO)

This document tracks planned architectural improvements, feature research, and pending firmware hardening items for the MacroPad (3 Keys + 1 Knob) project.

---

## 1. Pending Firmware Hardening

### 1.1. Bug 3: Clock Stabilization, Bootloader Entry & NeoPixel Timing
- **Status:** **POSTPONED / PENDING** (Deferred to avoid clock configuration side effects during active testing).
- **Location:** [`3keys_1knob.c:490-505`](3keys_1knob.c#L490-L505) (startup of `main()`).
- **Issue Description:**
  1. **Clock Mismatch at Power-On:** At cold reset, the CH552G starts running from the internal RC oscillator with factory default dividers (typically ~6 MHz to 12 MHz, uncalibrated). However, `CLK_config()` (which sets system clock to 16 MHz via `CLOCK_CFG`) is only executed *after* the bootloader entry check:
     ```c
     NEO_init();
     if (!PIN_read(PIN_KEY1)) {
       NEO_latch();
       for (i = 9; i; i--) NEO_sendByte(NEO_MAX); // NeoPixel bitbang
       BOOT_now();                                 // Jump to bootloader
     }
     CLK_config(); // Configures 16 MHz
     ```
  2. **NeoPixel Timing Distortion:** `NEO_sendByte()` relies on inline assembly / delay loops explicitly tuned for `FREQ_SYS = 16000000` (800 kHz bit-bang protocol with ±150 ns tolerances). Executing it before `CLK_config()` runs the timing loops on an unconfigured clock, violating the WS2812 protocol and causing garbled or failed LED lighting.
  3. **GPIO Pull-Up Inconsistency:** `PIN_read(PIN_KEY1)` is checked before setting explicit input pull-up modes (`PIN_input_PU(PIN_KEY1)`).
  4. **Bootloader Handoff:** Calling `BOOT_now()` directly without a clean software reset or proper peripheral deinitialization can leave USB hardware registers in an intermediate state when entering the factory ISP ROM.
- **Planned Remediation:**
  - Move `CLK_config()` and a brief 5 ms stabilization delay (`DLY_ms(5)`) to the very top of `main()`, before any pin reads or NeoPixel operations.
  - Explicitly configure `PIN_input_PU(PIN_KEY1)`.
  - Ensure the bootloader transition executes with verified 16 MHz timing and clean latching.
  - Test thoroughly against both warm reboots and cold plug-in states to verify that ISP entry (`4348:55e0`) remains 100% reliable under all host conditions.

---

## 2. Research & Feature Exploration

### 2.1. Standalone Modifier Keystrokes (Modifiers Without Associated Keycodes)
- **Status:** **UNDER RESEARCH / DISCUSSION**
- **Description:** Investigate and discuss whether physical keys/knob inputs can be configured to fire standalone modifier key events (e.g. `Right GUI` / `Super` alone, or `Left Alt` alone) without an accompanying primary HID keycode.
- **Technical Context & Questions to Explore:**
  - Standard USB HID keyboard input reports (`Report ID 0x01`) transmit modifiers as a dedicated 8-bit bitmask (`Byte 1`) independently from the 6 regular keycode slots (`Bytes 3..8`).
  - Setting a modifier bit while leaving the keycode array as zero (`0x00`) transmits a modifier press to the host OS.
  - Investigate OS-level behavior across Linux, Windows, and macOS (e.g., single GUI tap opening the start/app menu, compositor shortcut behaviors, modifier hold vs tap).
  - Investigate configuration syntax and firmware handling: how `keymap.json`, `tools/keymap.py`, `tools/macropad_config.py`, and firmware `handle_key()` should represent a key mapping that only contains modifiers (e.g. `{"type": "keyboard", "mod": ["rgui"], "key": "none"}`).
