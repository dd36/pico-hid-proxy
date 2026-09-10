# boot.py — Runs at power-on before main.py
#
# Initializes the USB composite device: CDC serial plus HID keyboard, mouse,
# absolute mouse and a Nintendo Switch gamepad, all at once.
#
# One device serves both consoles. The Switch uses the gamepad and accepts the
# extra interfaces; a PlayStation uses the keyboard and mouse and ignores the
# gamepad, which it cannot authenticate. Verified on both.
#
# The device reports the USB ids of a HORI HORIPAD for Nintendo Switch, which
# the Switch requires and a PlayStation does not care about. That means the
# board never enumerates as a Raspberry Pi, so host.py matches both vendor ids.
#
# This runs before main.py and before anything can recover the device, so a
# failure here would leave it with no USB at all. Keep it simple.

import usb.device
from hid_device import (KeyboardHID, MouseHID, AbsMouseHID, SwitchGamepadHID,
                        PAD_VID, PAD_PID, PAD_BCD_DEVICE)

keyboard = KeyboardHID()
mouse = MouseHID()
abs_mouse = AbsMouseHID()
gamepad = SwitchGamepadHID()

usb.device.get().init(
    gamepad,
    keyboard,
    mouse,
    abs_mouse,
    builtin_driver=True,
    id_vendor=PAD_VID,
    id_product=PAD_PID,
    bcd_device=PAD_BCD_DEVICE,
    remote_wakeup=True,
    manufacturer_str="Espressif",
    product_str="NSLite",
)
