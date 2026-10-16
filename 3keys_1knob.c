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
  NEO_update_all(leds[0].cur_r, leds[0].cur_g, leds[0].cur_b,
                 leds[1].cur_r, leds[1].cur_g, leds[1].cur_b,
                 leds[2].cur_r, leds[2].cur_g, leds[2].cur_b);

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
  }

  NEO_update_all(leds[0].cur_r, leds[0].cur_g, leds[0].cur_b,
                 leds[1].cur_r, leds[1].cur_g, leds[1].cur_b,
                 leds[2].cur_r, leds[2].cur_g, leds[2].cur_b);
}

// ===================================================================================
// Main Function
// ===================================================================================
void main(void)
{
  // Variables
  __xdata struct key keys[6]; // array of struct for keys
  __idata uint8_t i;
  __idata uint8_t j; // temp variable
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
  uint8_t eeprom_addr = 0;
  for (i = 0; i < 6; i++)
  {
    keys[i].debounce = 0;
    if (eeprom_read_byte(eeprom_addr) == 0)
    {
      keys[i].type = KEYBOARD;
      keys[i].mod[0] = eeprom_read_byte(eeprom_addr + 1);
      keys[i].code[0] = eeprom_read_byte(eeprom_addr + 2);
      keys[i].mod[1] = eeprom_read_byte(eeprom_addr + 3);
      keys[i].code[1] = eeprom_read_byte(eeprom_addr + 4);
      keys[i].last = 0;
      keys[i].toggle = 0;
    }
    else if (eeprom_read_byte(eeprom_addr) == 1)
    {
      keys[i].type = CONSUMER;
      keys[i].codeConsumer[0] = eeprom_read_byte(eeprom_addr + 1);
      keys[i].codeConsumer[1] = eeprom_read_byte(eeprom_addr + 2);
      keys[i].last = 0;
      keys[i].toggle = 0;
    }
    else if (eeprom_read_byte(eeprom_addr) == 2)
    {
      keys[i].type = MACRO;
      keys[i].ammount = eeprom_read_byte(eeprom_addr + 1);
      for (j = 0; j < keys[i].ammount; j++)
      {
        keys[i].code[j] = eeprom_read_byte(eeprom_addr + 2 + j);
      }
      keys[i].last = 0;
    }
    eeprom_addr += 12;
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

    // Process pending host USB command
    if (led_cmd_pending)
    {
      led_cmd_pending = 0;
      process_led_command(led_cmd_buf);
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
