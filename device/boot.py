# boot.py — Runs at power-on before main.py
# Initializes the USB composite device. Two personalities, chosen by config:
#
#   "hid" (default) — CDC serial + HID keyboard + mouse + absolute mouse
#   "pad"           — CDC serial + a Nintendo Switch gamepad, with the USB
#                     vendor/product ids of a HORI HORIPAD for Nintendo Switch
#
# This runs before main.py and before anything else can recover, so every step
# is guarded: a bad config value or a failed pad init falls back to "hid"
# rather than leaving the device with no USB at all.

import usb.device
from hid_device import (KeyboardHID, MouseHID, AbsMouseHID, SwitchGamepadHID,
                        PAD_VID, PAD_PID, PAD_BCD_DEVICE)

# Always created so main.py can import them unconditionally. Creating an
# interface does not register it with USB; only init() below does that.
keyboard = KeyboardHID()
mouse = MouseHID()
abs_mouse = AbsMouseHID()
gamepad = SwitchGamepadHID()

usb_mode = "hid"
try:
    import config

    usb_mode = config.get_usb_mode()
except Exception:
    pass  # unreadable config must not stop USB coming up

if usb_mode in ("pad", "all"):
    try:
        # "all" registers the gamepad plus keyboard and mouse, so a single
        # firmware could serve both consoles: the Switch uses the gamepad and
        # a PlayStation ignores it (an unauthenticated controller) while using
        # the keyboard and mouse. Experimental -- the Switch is fussy, and this
        # deviates from a real HORIPAD far more than adding CDC did.
        itfs = (gamepad,) if usb_mode == "pad" else (gamepad, keyboard, mouse, abs_mouse)
        # The Switch identifies controllers by VID/PID, so these apply to the
        # whole device -- in pad mode the Pico no longer enumerates as a
        # Raspberry Pi, and host.py has to look for the HORI ids too.
        # Composite: gamepad plus CDC serial. The Switch accepts this once the
        # descriptor is right, so there is no reason to give up the console.
        usb.device.get().init(
            *itfs,
            builtin_driver=True,
            id_vendor=PAD_VID,
            id_product=PAD_PID,
            bcd_device=PAD_BCD_DEVICE,
            remote_wakeup=True,   # NSLite sets usbAttributes 0xA0
            manufacturer_str="Espressif",
            product_str="NSLite",
        )
    except Exception:
        usb_mode = "hid"  # fall back rather than leave the device dark

if usb_mode not in ("pad", "all"):
    usb.device.get().init(keyboard, mouse, abs_mouse, builtin_driver=True)
