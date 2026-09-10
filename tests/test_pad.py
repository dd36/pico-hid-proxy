"""Exercise the pad parser and the Switch gamepad report on CPython."""
import sys, types, time as _t
_t.sleep_ms = lambda ms: None
for name, attrs in (("micropython", {"const": lambda x: x}), ("usb", {}),
                    ("usb.device", {}), ("usb.device.hid", {}), ("uasyncio", {})):
    m = types.ModuleType(name)
    for k, v in attrs.items(): setattr(m, k, v)
    sys.modules[name] = m
class _H:
    def __init__(self,*a,**k): pass
    def send_report(self, r): SENT.append(bytes(r))
SENT = []
sys.modules["usb.device.hid"].HIDInterface = _H
sys.modules["usb.device"].hid = sys.modules["usb.device.hid"]
import os as _os
sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "device"))
from protocol import parse
import hid_device
import keycodes

fails = []
def check(label, cond, extra=""):
    print(("  pass  " if cond else "  FAIL  ") + label + ("" if cond else "  " + str(extra)))
    if not cond: fails.append(label)

print("\n-- pad command parsing --")
for line, kind in [("pad tap a","pad_tap"), ("pad down zr","pad_down"), ("pad up minus","pad_up"),
                   ("pad dpad up","pad_dpad"), ("pad dpad neutral","pad_dpad"),
                   ("pad stick left 50 -25","pad_stick"), ("pad stick r 0 0","pad_stick"),
                   ("pad release","pad_release"),
                   ("usb mode pad","usb_mode_set"), ("usb status","usb_status")]:
    r = parse(line)
    check("%-26r -> %s" % (line, kind), not isinstance(r,str) and r.kind==kind, r)

print("\n-- rejected --")
for line, frag in [("pad","missing subcommand"), ("pad tap","missing button"),
                   ("pad tap nope","unknown button"), ("pad dpad sideways","unknown direction"),
                   ("pad stick left 5","need <left|right>"), ("pad stick left a b","must be integers"),
                   ("pad stick left 200 0","within -100..100"), ("pad bogus","unknown subcommand"),
                   ("usb mode xbox","unknown mode"), ("usb","missing subcommand")]:
    r = parse(line)
    check("%-26r rejected" % line, isinstance(r,str) and frag in r, r)

print("\n-- report bytes --")
pad = hid_device.SwitchGamepadHID()
SENT.clear(); pad.release_all()
check("neutral report", SENT[-1] == bytes([0,0,8,128,128,128,128,0]), list(SENT[-1]))
SENT.clear(); pad.button_down(keycodes.PAD_BUTTONS["a"])
check("A sets bit 0x0004", SENT[-1][0] == 0x04, list(SENT[-1]))
pad.button_down(keycodes.PAD_BUTTONS["zr"])
check("A+ZR chord", SENT[-1][0] == 0x84, hex(SENT[-1][0]))
pad.button_up(keycodes.PAD_BUTTONS["a"])
check("releasing A leaves ZR", SENT[-1][0] == 0x80, hex(SENT[-1][0]))
pad.release_all()
SENT.clear(); pad.button_down(keycodes.PAD_BUTTONS["home"])
check("home is in the high byte", SENT[-1][1] == 0x10, list(SENT[-1]))
pad.release_all()
SENT.clear(); pad.dpad(keycodes.PAD_HAT["right"])
check("dpad right = hat 2", SENT[-1][2] == 2, list(SENT[-1]))
SENT.clear(); pad.stick(True, 100, 0)
check("stick full right = 255", SENT[-1][3] == 255, list(SENT[-1]))
SENT.clear(); pad.stick(True, 0, 100)
check("stick full up = 1 (Y inverted)", SENT[-1][4] == 1, list(SENT[-1]))
SENT.clear(); pad.stick(True, 0, -100)
check("stick full down = 255", SENT[-1][4] == 255, list(SENT[-1]))
SENT.clear(); pad.stick(False, 0, 0)
check("right stick centers to 128", SENT[-1][5]==128 and SENT[-1][6]==128, list(SENT[-1]))
SENT.clear(); pad.stick(True, 37, 0)
check("37%% maps to 175", SENT[-1][3] == 175, SENT[-1][3])
check("every report is 8 bytes", all(len(r)==8 for r in SENT), [len(r) for r in SENT])

print("\n" + ("ALL PASS" if not fails else "%d FAILURE(S)" % len(fails)))
sys.exit(1 if fails else 0)
