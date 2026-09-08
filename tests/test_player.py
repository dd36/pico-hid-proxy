"""Integration test: macro storage + player, with CPython asyncio standing in for uasyncio."""
import sys, types, asyncio, os as _os, os, shutil, tempfile

stub = types.ModuleType("uasyncio")
stub.create_task = asyncio.create_task
stub.sleep_ms = lambda ms: asyncio.sleep(ms / 1000.0)
stub.CancelledError = asyncio.CancelledError
sys.modules["uasyncio"] = stub

sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "device"))
import macros

TMP = tempfile.mkdtemp()
macros._DIR = TMP

fails = []
def check(label, cond, extra=""):
    print(("  pass  " if cond else "  FAIL  ") + label + ("" if cond else "  " + str(extra)))
    if not cond: fails.append(label)

BODY = "key down w\nsleep 20\nkey up w\nkey tap space\n"

print("\n-- storage --")
check("empty listing", macros.list_names() == [])
check("exists() false", not macros.exists("gold1"))
macros.save("gold1", BODY)
check("saved", macros.exists("gold1"))
check("round-trips", macros.load("gold1") == BODY, repr(macros.load("gold1")))
macros.save("alpha", "key tap a\n")
check("sorted listing", macros.list_names() == ["alpha", "gold1"], macros.list_names())
check("file on disk", os.path.exists(os.path.join(TMP, "gold1.txt")))
macros.delete("alpha")
check("deleted", macros.list_names() == ["gold1"], macros.list_names())

print("\n-- player --")
executed, released, logs = [], [], []
macros.player.bind(lambda c: executed.append(c.kind),
                   lambda m: logs.append(m),
                   lambda: released.append(1))

async def scenario():
    r = macros.player.start("gold1")
    check("start ok", r.startswith("OK"), r)
    check("is_running", macros.player.is_running())
    check("status shows name", "gold1" in macros.player.status(), macros.player.status())
    await asyncio.sleep(0.3)
    check("ran all 3 hid steps", executed == ["key_down", "key_up", "key_tap"], executed)
    check("released after finish", len(released) == 1, released)
    check("not running after finish", not macros.player.is_running())
    check("status back to idle", macros.player.status() == "macro: not running")

    # missing / invalid
    check("missing macro", macros.player.start("nope").startswith("ERR macro 'nope' not found"))
    check("invalid name", macros.player.start("../x").startswith("ERR macro: invalid name"))

    # loop + stop
    executed.clear(); released.clear()
    r = macros.player.start("gold1", loop=True)
    check("loop start ok", r.endswith("(loop)"), r)
    check("double start refused", macros.player.start("gold1").startswith("ERR macro 'gold1' already running"))
    await asyncio.sleep(0.25)
    n_before = len(executed)
    check("looped past one pass", n_before > 3, n_before)
    check("iteration counter advanced", macros.player.iteration > 1, macros.player.iteration)
    r = macros.player.stop()
    check("stop ok", r.startswith("OK macro 'gold1' stopped"), r)
    check("released on stop", len(released) >= 1, released)
    check("not running after stop", not macros.player.is_running())
    await asyncio.sleep(0.15)
    check("no execution after stop", len(executed) == n_before or len(executed) - n_before <= 1,
          (n_before, len(executed)))
    check("stop when idle", macros.player.stop() == "macro not running")

    # a macro whose command raises must still release
    macros.save("boom", "key tap a\n")
    executed.clear(); released.clear()
    def boom(c): raise RuntimeError("hid failure")
    macros.player.bind(boom, lambda m: logs.append(m), lambda: released.append(1))
    macros.player.start("boom")
    await asyncio.sleep(0.15)
    check("error logged", any("hid failure" in m for m in logs), logs)
    check("released after error", len(released) == 1, released)
    check("not running after error", not macros.player.is_running())

asyncio.run(scenario())
shutil.rmtree(TMP)
print("\n" + ("ALL PASS" if not fails else "{} FAILURE(S): {}".format(len(fails), fails)))
sys.exit(1 if fails else 0)
