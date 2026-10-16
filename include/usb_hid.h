// ===================================================================================
// USB HID Functions for CH551, CH552 and CH554
// 2023 by Stefan Wagner (https://github.com/wagiminator)
// Modifications (2026): Mariano Boragno (refer to Git history for details)
// License: GNU General Public License v3.0 (GPLv3)
// ===================================================================================

#pragma once
#include <stdint.h>

void HID_init(void);                                      // setup USB-HID
void HID_sendReport(__xdata uint8_t* buf, uint8_t len);   // send HID report

extern volatile __bit host_cmd_pending;
extern __xdata uint8_t host_cmd_buf[16];

// Backwards-compatibility aliases
#define led_cmd_pending host_cmd_pending
#define led_cmd_buf     host_cmd_buf
