// ===================================================================================
// User Configurations for CH552G USB MacroPad Mini
// ===================================================================================

#pragma once

// Pin definitions (CH552G in SOP-16 package)
#define PIN_NEO             P34         // pin connected to NeoPixel (Pin 11)
#define PIN_KEY1            P11         // pin connected to key 1 (Pin 9)
#define PIN_KEY2            P17         // pin connected to key 2 (Pin 5)
#define PIN_KEY3            P16         // pin connected to key 3 (Pin 4)
#define PIN_ENC_SW          P33         // pin connected to knob switch (Pin 10)
#define PIN_ENC_A           P31         // pin connected to knob outA (Pin 7)
#define PIN_ENC_B           P30         // pin connected to knob outB (Pin 8)

// NeoPixel configuration
#define NEO_GRB                         // type of pixel: NEO_GRB or NEO_RGB
#define NEO_MAX             127

// USB device descriptor
#define USB_VENDOR_ID       0x1189      // VID
#define USB_PRODUCT_ID      0x8890      // PID
#define USB_DEVICE_VERSION  0x0100      // v1.0 (BCD-format)

// USB configuration descriptor
#define USB_MAX_POWER_mA    50          // max power in mA

// USB descriptor strings
#define MANUFACTURER_STR    'w','a','g','i','m','i','n','a','t','o','r'
#define PRODUCT_STR         'M','a','c','r','o','P','a','d'
#define SERIAL_STR          'C','H','5','5','2','x','H','I','D'
#define INTERFACE_STR       'H','I','D','-','K','e','y','b','o','a','r','d'
