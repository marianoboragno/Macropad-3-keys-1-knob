// ===================================================================================
// Project:             MacroPad Mini (3 Keys + 1 Rotary Encoder) for CH552G
// Original Framework:  Stefan Wagner (https://github.com/wagiminator)
// Hardware RE & Knob:  biemster (https://github.com/biemster/3keys_1knob)
// Extended Features:   MrGeorgeK55 (https://github.com/MrGeorgeK55/Macropad-3-keys-1-knob)
// Modifications (2026): Mariano Boragno (refer to Git history for details)
// License:             GNU General Public License v3.0 (GPLv3)
// ===================================================================================
// Features:
// - CH552G 8051 USB microcontroller with internal oscillator.
// - 3 mechanical key switches with 15ms anti-bounce lockout.
// - 1 rotary encoder with integrated push switch, decoded via full-step FSM.
// - 3 WS2812B RGB LEDs with autonomous animations (Solid, Breathe, Blink, Reactive).
// - USB HID Composite Device: Keyboard, Consumer Control, and Vendor LED Report.
// - Software bootloader entry via holding Key 1 on USB connection.
// ===================================================================================

#include <config.h>     // User configurations & pinout definitions
#include <system.h>     // System clock & reset functions
#include <delay.h>      // Delay functions
#include <neo.h>        // NeoPixel bit-bang driver
#include <usb_conkbd.h> // USB HID keyboard & consumer functions
#include <usb_hid.h>    // USB HID core & host OUT buffer

// USB Interrupt Service Routine
void USB_interrupt(void);
void USB_ISR(void) __interrupt(INT_NO_USB)
{
  USB_interrupt();
}

// -----------------------------------------------------------------------------------
// LED Channel Definitions & NeoPixel Hardware Driver
// -----------------------------------------------------------------------------------
enum LedMode {
  LED_MODE_OFF      = 0,
  LED_MODE_SOLID    = 1,
  LED_MODE_BREATHE  = 2,
  LED_MODE_BLINK    = 3,
  LED_MODE_REACTIVE = 4
};

__xdata struct led_channel {
  uint8_t  mode;        // Active animation mode (enum LedMode)
  uint8_t  r, g, b;     // Target color configured by host
  uint16_t period_ms;   // Animation period in milliseconds
  uint16_t timer;       // Current phase timer (ms)
  uint8_t  cur_r;       // Current rendered physical red brightness (0-255)
  uint8_t  cur_g;       // Current rendered physical green brightness (0-255)
  uint8_t  cur_b;       // Current rendered physical blue brightness (0-255)
};

__xdata struct led_channel leds[3];

// Transmit 24-bit RGB values to all 3 WS2812B LEDs in daisy-chain
void NEO_update_all(uint8_t r0, uint8_t g0, uint8_t b0,
                    uint8_t r1, uint8_t g1, uint8_t b1,
                    uint8_t r2, uint8_t g2, uint8_t b2)
{
  EA = 0;                       // Disable interrupts for precise NeoPixel timing
  NEO_writeColor(r0, g0, b0);   // LED 1 (Key 1)
  NEO_writeColor(r1, g1, b1);   // LED 2 (Key 2)
  NEO_writeColor(r2, g2, b2);   // LED 3 (Key 3)
  EA = 1;                       // Re-enable interrupts
}

// -----------------------------------------------------------------------------------
// Key Definition & EEPROM (Data Flash) Structures
// -----------------------------------------------------------------------------------
enum KeyType
{
  KEYBOARD = 0,
  CONSUMER = 1,
  MACRO    = 2
};

__xdata struct key
{
  enum KeyType type;        // Key type: 0 = Keyboard, 1 = Consumer, 2 = Macro
  uint8_t mod[2];           // Modifiers for states 0 and 1 (Keyboard type)
  uint8_t ammount;          // Number of keystrokes in macro sequence
  uint8_t code[10];         // HID keycodes for keyboard and macro sequences
  uint16_t codeConsumer[2]; // Consumer codes for states 0 and 1
  uint8_t last;             // Last sampled physical switch state
  uint8_t toggle;           // Current toggle state (0 or 1)
  uint8_t debounce;         // Non-blocking lockout counter for switch bounce
};

// Read a single byte from CH552 Data Flash (EEPROM emulation)
// Address space starts at DATA_FLASH_ADDR (0xC000)
uint8_t eeprom_read_byte(uint8_t addr)
{
  ROM_ADDR_H = DATA_FLASH_ADDR >> 8;
  ROM_ADDR_L = addr << 1;       // 16-bit word alignment
  ROM_CTRL = ROM_CMD_READ;
  return ROM_DATA_L;
}

// Write a single byte to CH552 Data Flash (EEPROM emulation)
// Address space starts at DATA_FLASH_ADDR (0xC000)
uint8_t eeprom_write_byte(uint8_t addr, uint8_t dat)
{
  if (addr > 0x7F) return 0xFF; // Data Flash limit: 128 bytes (0x00 to 0x7F)

  EA = 0;                       // Inhibit interrupts for safe mode & flash programming
  SAFE_MOD = 0x55;
  SAFE_MOD = 0xAA;              // Enter safe mode
  GLOBAL_CFG |= bDATA_WE;       // Enable Data Flash writing
  SAFE_MOD = 0x00;              // Exit safe mode

  ROM_ADDR_H = DATA_FLASH_ADDR >> 8;
  ROM_ADDR_L = addr << 1;       // 16-bit word alignment
  ROM_DATA_L = dat;
  ROM_CTRL = ROM_CMD_WRITE;     // Execute write (CPU pauses until complete)

  SAFE_MOD = 0x55;
  SAFE_MOD = 0xAA;              // Enter safe mode
  GLOBAL_CFG &= ~bDATA_WE;      // Disable Data Flash writing (write protect)
  SAFE_MOD = 0x00;              // Exit safe mode
  EA = 1;                       // Re-enable interrupts

  return (ROM_STATUS & bROM_CMD_ERR) ? 0xFE : 0;
}

// handle key press
void handle_key(uint8_t current, struct key *key, struct led_channel *led)
{
  if (key->debounce)
  {
    key->debounce--;
  }
  else if (current != key->last)
  {                      // state changed?
    key->last = current; // update last state flag
    key->debounce = 15;  // 15ms lockout for mechanical bounce
    if (current)
    { // key was pressed?
      if (key->type == KEYBOARD)
      {
        if (key->toggle == 0)
        {
          KBD_code_press(key->mod[0], key->code[0]); // press keyboard/keypad key
        }
        else
        {
          KBD_code_press(key->mod[1], key->code[1]); // release
        }
      }

      else if (key->type == CONSUMER)
      {
        if (key->toggle == 0)
        {
          CON_press(key->codeConsumer[0]); // press consumer key
        }
        else
        {
          CON_press(key->codeConsumer[1]); // release
        }
      }

      else if (key->type == MACRO)
      {
        for (int i = 0; i < key->ammount; i++)
        {
          KBD_code_press(0, key->code[i]);
          DLY_ms(5);
          KBD_code_release(0, key->code[i]);
          DLY_ms(5);
        }
      }

      if (led && led->mode == LED_MODE_REACTIVE)
      {
        led->cur_r = led->r;
        led->cur_g = led->g;
        led->cur_b = led->b;
      }
    }
    else
    { // key was released?
      if (key->type == KEYBOARD)
      {
        if (key->toggle == 0)
        {
          KBD_code_release(key->mod[0], key->code[0]); // release
          key->toggle = 1;
        }
        else
        {
          KBD_code_release(key->mod[1], key->code[1]); // press keyboard/keypad key
          key->toggle = 0;
        }
      }
      else if (key->type == CONSUMER)
      {
        if (key->toggle == 0)
        {
          CON_release(key->codeConsumer[0]); // release
          key->toggle = 1;
        }
        else
        {
          CON_release(key->codeConsumer[1]); // release
          key->toggle = 0;
        }
      }
      // no need to release macro keys but enter cooldown in case it is a macro key
      if (key->type == MACRO)
      {
        DLY_ms(50);
      }
    }
  }
  else if (key->last)
  { // key still being pressed?
    if (led && led->mode == LED_MODE_REACTIVE)
    {
      led->cur_r = led->r;
      led->cur_g = led->g;
      led->cur_b = led->b;
    }
  }
}

// ===================================================================================
// Rotary Encoder Full-Step State Machine (Ben Buxton / buxtronix)
// ===================================================================================
#define DIR_NONE      0x0
#define DIR_CW        0x10
#define DIR_CCW       0x20

#define R_START       0x0
#define R_CW_FINAL    0x1
#define R_CW_BEGIN    0x2
#define R_CW_NEXT     0x3
#define R_CCW_BEGIN   0x4
#define R_CCW_FINAL   0x5
#define R_CCW_NEXT    0x6

__code const uint8_t ttable[7][4] = {
  // R_START (0x0)
  {R_START,    R_CW_BEGIN,  R_CCW_BEGIN,  R_START},
  // R_CW_FINAL (0x1)
  {R_CW_NEXT,  R_START,     R_CW_FINAL,   R_START | DIR_CW},
  // R_CW_BEGIN (0x2)
  {R_CW_NEXT,  R_CW_BEGIN,  R_START,      R_START},
  // R_CW_NEXT (0x3)
  {R_CW_NEXT,  R_CW_BEGIN,  R_CW_FINAL,   R_START},
  // R_CCW_BEGIN (0x4)
  {R_CCW_NEXT, R_START,     R_CCW_BEGIN,  R_START},
  // R_CCW_FINAL (0x5)
  {R_CCW_NEXT, R_CCW_FINAL, R_START,      R_START | DIR_CCW},
  // R_CCW_NEXT (0x6)
  {R_CCW_NEXT, R_CCW_FINAL, R_CCW_BEGIN,  R_START},
};

// handle knob
void handle_knob(struct key *key)
{
  if (key->type == KEYBOARD)
  {
    if (key->toggle == 0)
    {
      KBD_code_type(key->mod[0], key->code[0]); // press keyboard/keypad key
      key->toggle = 1;
    }
    else
    {
      KBD_code_type(key->mod[1], key->code[1]); // press keyboard/keypad key
      key->toggle = 0;
    }
  }

  else if (key->type == CONSUMER)
  {
    if (key->toggle == 0)
    {
      CON_type(key->codeConsumer[0]); // press consumer key
      key->toggle = 1;
    }
    else
    {
      CON_type(key->codeConsumer[1]); // press consumer key
      key->toggle = 0;
    }
  }

  else if (key->type == MACRO)
  {
    for (int i = 0; i < key->ammount; i++)
    {
      KBD_code_press(0, key->code[i]);
      DLY_ms(5);
      KBD_code_release(0, key->code[i]);
      DLY_ms(5);
    }
  }
}

// ===================================================================================
// LED Autonomous Animation Engine & Command Processing
// ===================================================================================

// Cache of physically transmitted NeoPixel RGB values to avoid redundant 90us bus stalls
static __xdata uint8_t rendered_r[3] = {0, 0, 0};
static __xdata uint8_t rendered_g[3] = {0, 0, 0};
static __xdata uint8_t rendered_b[3] = {0, 0, 0};

// Process incoming host command for LEDs
void process_led_command(__xdata uint8_t *buf)
{
  uint8_t led_idx = buf[1];
  uint8_t mode = buf[2];
  uint8_t r = buf[3];
  uint8_t g = buf[4];
  uint8_t b = buf[5];
  uint16_t period = ((uint16_t)buf[6] << 8) | buf[7];
  uint8_t i, start_i, end_i;

  if (period == 0) period = 2000;

  if (led_idx == 0xFF || led_idx >= 3)
  {
    start_i = 0;
    end_i = 3;
  }
  else
  {
    start_i = led_idx;
    end_i = led_idx + 1;
  }

  // 1. Immediately turn off selected LEDs to prevent glitches or flashes
  for (i = start_i; i < end_i; i++)
  {
    leds[i].cur_r = 0;
    leds[i].cur_g = 0;
    leds[i].cur_b = 0;
  }
  for (i = 0; i < 3; i++)
  {
    rendered_r[i] = leds[i].cur_r;
    rendered_g[i] = leds[i].cur_g;
    rendered_b[i] = leds[i].cur_b;
  }
  NEO_update_all(rendered_r[0], rendered_g[0], rendered_b[0],
                 rendered_r[1], rendered_g[1], rendered_b[1],
                 rendered_r[2], rendered_g[2], rendered_b[2]);

  // 2. Configure mode, color, and period while LEDs are off
  for (i = start_i; i < end_i; i++)
  {
    leds[i].mode = mode;
    leds[i].r = r;
    leds[i].g = g;
    leds[i].b = b;
    leds[i].period_ms = period;
    // 3. Reset phase timer to zero
    leds[i].timer = 0;
  }
}

// Update LED animations
void update_led_animations(uint8_t elapsed_ms)
{
  uint8_t i;
  uint16_t half_p;
  uint16_t factor;
  uint16_t scale;
  uint8_t changed = 0;

  for (i = 0; i < 3; i++)
  {
    if (leds[i].mode == LED_MODE_OFF)
    {
      leds[i].cur_r = 0;
      leds[i].cur_g = 0;
      leds[i].cur_b = 0;
    }
    else if (leds[i].mode == LED_MODE_SOLID)
    {
      leds[i].cur_r = leds[i].r;
      leds[i].cur_g = leds[i].g;
      leds[i].cur_b = leds[i].b;
    }
    else if (leds[i].mode == LED_MODE_BREATHE)
    {
      leds[i].timer += elapsed_ms;
      if (leds[i].timer >= leds[i].period_ms)
        leds[i].timer = 0;

      half_p = leds[i].period_ms >> 1;
      if (half_p == 0) half_p = 1;

      if (leds[i].timer < half_p)
      {
        factor = ((uint32_t)leds[i].timer * 255) / half_p;
      }
      else
      {
        factor = ((uint32_t)(leds[i].period_ms - leds[i].timer) * 255) / half_p;
      }

      scale = (factor * factor) >> 8;
      leds[i].cur_r = ((uint16_t)leds[i].r * scale) >> 8;
      leds[i].cur_g = ((uint16_t)leds[i].g * scale) >> 8;
      leds[i].cur_b = ((uint16_t)leds[i].b * scale) >> 8;
    }
    else if (leds[i].mode == LED_MODE_BLINK)
    {
      leds[i].timer += elapsed_ms;
      if (leds[i].timer >= leds[i].period_ms)
        leds[i].timer = 0;

      half_p = leds[i].period_ms >> 1;
      if (leds[i].timer < half_p)
      {
        leds[i].cur_r = 0;
        leds[i].cur_g = 0;
        leds[i].cur_b = 0;
      }
      else
      {
        leds[i].cur_r = leds[i].r;
        leds[i].cur_g = leds[i].g;
        leds[i].cur_b = leds[i].b;
      }
    }
    else if (leds[i].mode == LED_MODE_REACTIVE)
    {
      if (leds[i].cur_r > 1) leds[i].cur_r -= 2; else leds[i].cur_r = 0;
      if (leds[i].cur_g > 1) leds[i].cur_g -= 2; else leds[i].cur_g = 0;
      if (leds[i].cur_b > 1) leds[i].cur_b -= 2; else leds[i].cur_b = 0;
    }

    if (leds[i].cur_r != rendered_r[i] ||
        leds[i].cur_g != rendered_g[i] ||
        leds[i].cur_b != rendered_b[i])
    {
      changed = 1;
      rendered_r[i] = leds[i].cur_r;
      rendered_g[i] = leds[i].cur_g;
      rendered_b[i] = leds[i].cur_b;
    }
  }

  // Only disable interrupts and write to WS2812B if at least one pixel changed
  if (changed)
  {
    NEO_update_all(rendered_r[0], rendered_g[0], rendered_b[0],
                   rendered_r[1], rendered_g[1], rendered_b[1],
                   rendered_r[2], rendered_g[2], rendered_b[2]);
  }
}

// ===================================================================================
// Default Key Configurations (Fallback when EEPROM is unprogrammed / 0xFF)
// ===================================================================================
void load_default_key(struct key *k, uint8_t idx)
{
  k->last = 0;
  k->toggle = 0;
  k->debounce = 0;
  if (idx == 0) // Key 1: Ctrl + C (Copy)
  {
    k->type = KEYBOARD;
    k->mod[0] = 0x01; k->code[0] = 0x06;
    k->mod[1] = 0x01; k->code[1] = 0x06;
  }
  else if (idx == 1) // Key 2: Ctrl + V (Paste)
  {
    k->type = KEYBOARD;
    k->mod[0] = 0x01; k->code[0] = 0x19;
    k->mod[1] = 0x01; k->code[1] = 0x19;
  }
  else if (idx == 2) // Key 3: Ctrl + Z (Undo)
  {
    k->type = KEYBOARD;
    k->mod[0] = 0x01; k->code[0] = 0x1D;
    k->mod[1] = 0x01; k->code[1] = 0x1D;
  }
  else if (idx == 3) // Knob Switch: Consumer Mute
  {
    k->type = CONSUMER;
    k->codeConsumer[0] = 0x00E2;
    k->codeConsumer[1] = 0x00E2;
  }
  else if (idx == 4) // Knob CW: Consumer Volume Up
  {
    k->type = CONSUMER;
    k->codeConsumer[0] = 0x00E9;
    k->codeConsumer[1] = 0x00E9;
  }
  else if (idx == 5) // Knob CCW: Consumer Volume Down
  {
    k->type = CONSUMER;
    k->codeConsumer[0] = 0x00EA;
    k->codeConsumer[1] = 0x00EA;
  }
}

// Load key mapping from a 12-byte buffer into a key struct
void load_key_from_buffer(struct key *k, uint8_t idx, __xdata uint8_t *buf)
{
  uint8_t j;
  uint8_t ktype = buf[0];
  if (ktype == KEYBOARD)
  {
    k->type = KEYBOARD;
    k->mod[0] = buf[1];
    k->code[0] = buf[2];
    k->mod[1] = buf[3];
    k->code[1] = buf[4];
    // Fallback: if second state code is 0, duplicate first state (Bug 5 fix)
    if (k->code[1] == 0)
    {
      k->code[1] = k->code[0];
      k->mod[1] = k->mod[0];
    }
  }
  else if (ktype == CONSUMER)
  {
    k->type = CONSUMER;
    // Read 16-bit consumer codes (LSB | MSB << 8)
    k->codeConsumer[0] = (uint16_t)buf[1] | ((uint16_t)buf[2] << 8);
    k->codeConsumer[1] = (uint16_t)buf[3] | ((uint16_t)buf[4] << 8);
    // Fallback: if second state code is 0, duplicate first state (Bug 5 fix)
    if (k->codeConsumer[1] == 0)
    {
      k->codeConsumer[1] = k->codeConsumer[0];
    }
  }
  else if (ktype == MACRO)
  {
    k->type = MACRO;
    k->ammount = buf[1];
    // Prevent XRAM buffer overflow if ammount > 10 (Bug 1 fix)
    if (k->ammount > 10)
      k->ammount = 10;
    for (j = 0; j < k->ammount; j++)
    {
      k->code[j] = buf[2 + j];
    }
  }
  else
  {
    // Fallback to built-in factory defaults if unprogrammed (0xFF) or invalid
    load_default_key(k, idx);
  }
}

// Read 12 bytes from Data Flash (EEPROM) and populate key struct
void load_key_from_eeprom(struct key *k, uint8_t idx)
{
  __xdata uint8_t raw[12];
  uint8_t addr = idx * 12;
  uint8_t j;
  for (j = 0; j < 12; j++)
  {
    raw[j] = eeprom_read_byte(addr + j);
  }
  k->debounce = 0;
  k->last = 0;
  k->toggle = 0;
  load_key_from_buffer(k, idx, raw);
}

// Process incoming host command for Key configuration (Report ID 0x04)
void process_key_command(__xdata struct key *keys, __xdata uint8_t *buf)
{
  uint8_t slot = buf[1];
  uint8_t flags = buf[15];
  uint8_t j;
  uint8_t addr;

  if (slot >= 6) return; // Invalid slot index

  // Bit 0: COMMIT_EEPROM (1 = Write 12 bytes to Data Flash)
  if (flags & 0x01)
  {
    addr = slot * 12;
    for (j = 0; j < 12; j++)
    {
      eeprom_write_byte(addr + j, buf[2 + j]);
    }
  }

  // Update RAM mapping immediately
  load_key_from_buffer(&keys[slot], slot, &buf[2]);

  // Bit 1: RESET_STATE (Reset debounce, toggle, and last state)
  // Also reset on standard EEPROM commit for clean state transition
  if ((flags & 0x02) || (flags & 0x01))
  {
    keys[slot].debounce = 0;
    keys[slot].last = 0;
    keys[slot].toggle = 0;
  }
}

// ===================================================================================
// Main Function
// ===================================================================================
void main(void)
{
  // Variables
  __xdata struct key keys[6]; // array of struct for keys
  __idata uint8_t i;
  uint8_t enc_state = R_START;
  uint8_t pin_state;
  uint8_t anim_div = 0;

  // Enter bootloader if key 1 is pressed
  NEO_init(); // init NeoPixels
  if (!PIN_read(PIN_KEY1))
  {              // key 1 pressed?
    NEO_latch(); // make sure pixels are ready
    for (i = 9; i; i--)
      NEO_sendByte(NEO_MAX); // light up all pixels
    BOOT_now();              // enter bootloader
  }

  // Setup
  CLK_config(); // configure system clock
  DLY_ms(5);    // wait for clock to settle
  KBD_init();   // init USB HID keyboard
  WDT_start();  // start watchdog timer

  // Read EEPROM configurations for all 6 keys (12 bytes per key)
  for (i = 0; i < 6; i++)
  {
    load_key_from_eeprom(&keys[i], i);
  }

  // Initialize LED defaults: OFF
  for (i = 0; i < 3; i++)
  {
    leds[i].mode = LED_MODE_OFF;
    leds[i].r = 0;
    leds[i].g = 0;
    leds[i].b = 0;
    leds[i].period_ms = 2000;
    leds[i].timer = 0;
    leds[i].cur_r = 0;
    leds[i].cur_g = 0;
    leds[i].cur_b = 0;
  }

  NEO_update_all(0, 0, 0, 0, 0, 0, 0, 0, 0); // ensure LEDs are turned off initially

  // Loop
  while (1)
  {
    handle_key(!PIN_read(PIN_KEY1), &keys[0], &leds[0]);
    handle_key(!PIN_read(PIN_KEY2), &keys[1], &leds[1]);
    handle_key(!PIN_read(PIN_KEY3), &keys[2], &leds[2]);
    handle_key(!PIN_read(PIN_ENC_SW), &keys[3], (void *)0);

    // Rotary encoder state machine
    pin_state = (PIN_read(PIN_ENC_A) << 1) | PIN_read(PIN_ENC_B);
    enc_state = ttable[enc_state & 0x0F][pin_state];
    if ((enc_state & 0x30) == DIR_CW)
    {
      handle_knob(&keys[4]); // clockwise
    }
    else if ((enc_state & 0x30) == DIR_CCW)
    {
      handle_knob(&keys[5]); // counter-clockwise
    }

    // Process pending host USB command (Report 3: LEDs, Report 4: Keys)
    if (host_cmd_pending)
    {
      if (host_cmd_buf[0] == 3)
      {
        process_led_command(host_cmd_buf);
      }
      else if (host_cmd_buf[0] == 4)
      {
        process_key_command(keys, host_cmd_buf);
      }
      host_cmd_pending = 0;
      // Re-enable EP2 OUT reception (ACK)
      UEP2_CTRL = (UEP2_CTRL & ~MASK_UEP_R_RES) | UEP_R_RES_ACK;
    }

    // Update LED animations every 10ms
    if (++anim_div >= 10)
    {
      anim_div = 0;
      update_led_animations(10);
    }

    DLY_ms(1);   // 1kHz sampling rate
    WDT_reset(); // reset watchdog
  }
}
