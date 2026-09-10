# boot.py — Runs at power-on before main.py
# Initializes the USB composite device. Two personalities, chosen by config:
#
#   "hid" (default) — CDC serial + HID keyboard + mouse + absolute mouse
#   "pad"           — CDC serial + a Nintendo Switch gamepad, with the USB
#                     vendor/product ids of a HORI Pokken Tournament Pro Pad
#
# This runs before main.py and before anything else can recover, so every step
# is guarded: a bad config value or a failed pad init falls back to "hid"
# rather than leaving the device with no USB at all.

import usb.device
from hid_device import KeyboardHID, MouseHID, AbsMouseHID, SwitchGamepadHID, PAD_VID, PAD_PID

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

if usb_mode == "pad":
    try:
        # The Switch identifies controllers by VID/PID, so these apply to the
        # whole device -- in pad mode the Pico no longer enumerates as a
        # Raspberry Pi, and host.py has to look for the Pokken ids too.
        usb.device.get().init(
            gamepad,
            builtin_driver=True,
            id_vendor=PAD_VID,
            id_product=PAD_PID,
            manufacturer_str="HORI CO.,LTD.",
            product_str="POKKEN CONTROLLER",
        )
    except Exception:
        usb_mode = "hid"  # fall back rather than leave the device dark

if usb_mode != "pad":
    usb.device.get().init(keyboard, mouse, abs_mouse, builtin_driver=True)
