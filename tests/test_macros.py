"""Desktop test harness: stubs uasyncio so device modules import on CPython."""
import sys, types, os as _os

stub = types.ModuleType("uasyncio")
class _T:
    def cancel(self): pass
stub.create_task = lambda c: _T()
async def _s(ms): pass
stub.sleep_ms = _s
stub.CancelledError = type("CancelledError", (Exception,), {})
sys.modules["uasyncio"] = stub

sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "device"))
from protocol import parse, Command, valid_macro_name, MIN_AUTORUN_DELAY_MS
import macros

fails = []
def check(label, cond, extra=""):
    if cond:
        print("  pass  {}".format(label))
    else:
        print("  FAIL  {}  {}".format(label, extra))
        fails.append(label)

def kind_of(line):
    r = parse(line)
    return r if isinstance(r, str) else r.kind

print("\n-- name validation --")
for n in ("gold1", "a", "my-macro_2", "A"*24):
    check("accept %r" % n, valid_macro_name(n))
for n in ("", "a"*25, "../etc", "has space", "sl/ash", "dot.name", "unié"):
    check("reject %r" % n, not valid_macro_name(n))

print("\n-- macro command parsing --")
cases = [
    ("macro list", "macro_list"),
    ("macro status", "macro_status"),
    ("macro stop", "macro_stop"),
    ("macro run gold1", "macro_run"),
    ("macro run gold1 loop", "macro_run"),
    ("macro show gold1", "macro_show"),
    ("macro delete gold1", "macro_delete"),
    ("macro save gold1", "macro_capture_begin"),
    ("macro save gold1\nkey tap space", "macro_save"),
    ("macro end", "macro_capture_end"),
    ("macro abort", "macro_capture_abort"),
    ("macro autorun", "macro_autorun_status"),
    ("macro autorun status", "macro_autorun_status"),
    ("macro autorun off", "macro_autorun_off"),
    ("macro autorun gold1 5000", "macro_autorun_set"),
    ("macro autorun gold1 5000 loop", "macro_autorun_set"),
]
for line, want in cases:
    got = kind_of(line)
    check("%-34r -> %s" % (line, want), got == want, "got %r" % got)

print("\n-- macro run/save flags --")
r = parse("macro run gold1 loop");  check("run loop=True", r.params["loop"] is True)
r = parse("macro run gold1");       check("run loop=False", r.params["loop"] is False)
r = parse("macro autorun gold1 7000 loop")
check("autorun name", r.params["name"] == "gold1")
check("autorun delay", r.params["delay"] == 7000, r.params)
check("autorun loop", r.params["loop"] is True)
r = parse("macro save g1\nkey down w\nsleep 500")
check("save body captured", r.params["body"] == "key down w\nsleep 500", repr(r.params["body"]))

print("\n-- error paths --")
errs = [
    ("sleep 500", "only valid inside a macro"),
    ("macro", "missing subcommand"),
    ("macro bogus", "unknown subcommand"),
    ("macro run", "missing name"),
    ("macro run g1 twice", "unknown option"),
    ("macro show", "missing name"),
    ("macro delete", "missing name"),
    ("macro save", "missing name"),
    ("macro save bad name", "unexpected extra argument"),
    ("macro show a b", "unexpected extra argument"),
    ("macro delete a b", "unexpected extra argument"),
    ("macro run ../evil", "invalid name"),
    ("macro show ../evil", "invalid name"),
    ("macro delete ../evil", "invalid name"),
    ("macro save ../evil", "invalid name"),
    ("macro autorun g1", "need <name> <delay_ms>"),
    ("macro autorun g1 abc", "must be an integer"),
    ("macro autorun g1 100", ">= 3000"),
    ("macro autorun g1 2999", ">= 3000"),
    ("macro autorun g1 5000 nope", "unknown option"),
]
for line, frag in errs:
    got = kind_of(line)
    check("%-28r rejected" % line, isinstance(got, str) and frag in got, "got %r" % got)

check("autorun floor is 3000", MIN_AUTORUN_DELAY_MS == 3000)
r = parse("macro autorun g1 3000")
check("exactly 3000 accepted", not isinstance(r, str), r)

print("\n-- on-device paths must not shadow frozen modules --")
# sys.path on the device is ['', '.frozen', '/lib'], so anything at / whose name
# matches a frozen module beats the module. /macros shadowed macros.py and left
# the device at a bare REPL on the first boot after any macro was saved.
_devdir = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "device")
_frozen = sorted(f[:-3] for f in _os.listdir(_devdir) if f.endswith(".py"))
_base = macros._DIR.lstrip("/")
check("macro dir is not a bare identifier", not _base.isidentifier(), macros._DIR)
check("macro dir shadows no frozen module", _base not in _frozen,
      "%s collides with device/%s.py" % (macros._DIR, _base))
print("   frozen modules: %s" % ", ".join(_frozen))

print("\n-- macro body compilation --")
good = """# gold farm loop
key down w
sleep 800
key up w

mouse move 120 0
sleep 300
key tap space
sleep 5000
"""
steps = macros.compile_body(good)
check("good body compiles", not isinstance(steps, str), steps)
check("comments+blanks skipped -> 7 steps", len(steps) == 7, len(steps) if not isinstance(steps,str) else steps)
check("sleep steps are kind 0", steps[1][0] == 0 and steps[1][1] == 800, steps[1])
check("cmd steps are kind 1", steps[0][0] == 1 and steps[0][1].kind == "key_down", steps[0])

bad = [
    ("key down\nsleep 100", "line 1"),
    ("key down w\nsleep", "line 2"),
    ("key down w\nsleep abc", "must be an integer"),
    ("key down w\nsleep -5", "must be >= 0"),
    ("key tap notakey", "unknown key"),
    ("reboot", "not allowed inside a macro"),
    ("key tap a\nreboot bootloader", "not allowed inside a macro"),
    ("macro run other", "not allowed inside a macro"),
    ("macro stop", "not allowed inside a macro"),
    ("bogusverb 1", "unknown command"),
]
for body, frag in bad:
    res = macros.compile_body(body)
    check("reject %-30r" % body.replace("\n", "|"),
          isinstance(res, str) and frag in res, "got %r" % res)

check("empty body -> no steps", macros.compile_body("\n# just a comment\n\n") == [])

print("\n-- repeat blocks --")
good = """key tap a
repeat 3
key down w
sleep 100
key up w
end
key tap b
"""
st = macros.compile_body(good)
check("repeat compiles", not isinstance(st, str), st)
check("expands 1 + 3*3 + 1 = 11 steps", len(st) == 11, len(st) if not isinstance(st,str) else st)
check("body before repeat kept", st[0][1].kind == "key_tap", st[0])
check("body after repeat kept", st[-1][1].kind == "key_tap", st[-1])
check("repeat 1 is identity",
      len(macros.compile_body("repeat 1\nkey tap a\nend")) == 1)
check("comments/blanks inside repeat skipped",
      len(macros.compile_body("repeat 2\n# hi\n\nkey tap a\nend")) == 2)

for body, frag in [
    ("repeat\nkey tap a\nend",            "repeat needs <count>"),
    ("repeat x\nkey tap a\nend",          "must be an integer"),
    ("repeat 0\nkey tap a\nend",          "must be 1-"),
    ("repeat 99999\nkey tap a\nend",      "must be 1-"),
    ("repeat 2\nkey tap a",                "without a matching 'end'"),
    ("end",                                 "without a matching 'repeat'"),
    ("repeat 2\nend",                      "repeat block is empty"),
    ("repeat 2\nrepeat 2\nkey tap a\nend\nend", "cannot be nested"),
    ("repeat 2\nkey tap NOPE\nend",       "unknown key"),
    ("repeat 2\nreboot\nend",             "not allowed inside a macro"),
    ("repeat 1000\nkey tap a\nkey tap b\nkey tap c\nkey tap d\nkey tap e\nend", "over the"),
]:
    r = macros.compile_body(body)
    check("reject %-42r" % body.replace("\n","|"),
          isinstance(r, str) and frag in r, "got %r" % r)

print("\n-- line numbers point at the real line --")
res = macros.compile_body("key tap a\nkey tap b\nkey tap NOPE")
check("error reports line 3", isinstance(res, str) and res.startswith("line 3:"), res)

print("\n" + ("ALL PASS" if not fails else "{} FAILURE(S): {}".format(len(fails), fails)))
sys.exit(1 if fails else 0)
