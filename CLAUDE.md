# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Raspberry Pi Pico 2 W (RP2350) that presents itself to a host machine as a real
USB HID keyboard and mouse, driven remotely over serial or WiFi. `device/` is
MicroPython that runs on the Pico; `host/` runs on your computer.

## Build and flash

```bash
./build_firmware.sh                  # Docker build -> firmware/
./build_firmware.sh --clean          # bypass Docker layer cache
BOARD=RPI_PICO_W ./build_firmware.sh # override board (default RPI_PICO2_W)
```

Each build writes a versioned `pico-hid-proxy-<board>-<git describe>.uf2` plus a
copy at the stable path `firmware/pico_hid_firmware.uf2`, which `release.yml` and
the README both depend on — keep that name if you touch the build script. The
versioned copies are never overwritten, so a rollback image always survives; the
build extracts to a temp file and checks the UF2 magic before replacing anything,
because a failed build silently clobbering the previous image once cost the only
known-good firmware on hand.

The MicroPython version is pinned by `ARG MICROPYTHON_TAG` in the `Dockerfile`.

**`device/` is frozen into the firmware** (see `manifest.py`), not copied onto the
Pico's filesystem. Every device-code change — including one-line edits and web UI
tweaks — requires a full rebuild and reflash: hold BOOTSEL while plugging in, then
copy the `.uf2` to the drive that appears. Budget for that when planning changes;
it is the dominant cost of iterating on `device/`.

```bash
python3 host/host.py [PORT]   # interactive serial console; auto-detects the port
```

## Testing

```bash
python3 tests/test_macros.py    # protocol parsing + macro compilation
python3 tests/test_player.py    # macro storage + playback
```

Plain scripts, no framework, no dependencies; each exits non-zero on failure and
prints one line per assertion.

They work because device code that is pure logic can run on CPython once `uasyncio`
is stubbed into `sys.modules` before import (`test_player.py` stubs it with real
`asyncio`, so playback, looping and cancellation are genuinely exercised).
`macros._DIR` is repointed at a temp directory for storage tests. `main.py`,
`boot.py`, `web.py`, `wifi.py`, and `hid_device.py` cannot be imported at all —
`main.py` calls `main()` at import time and `boot.py` initializes real USB hardware,
so their behavior is only verifiable on device.

Know what this does not cover: anything about the real MicroPython runtime. The
`/macros` shadowing bug passed every desktop test and still bricked the device to a
REPL, because the tests repoint `_DIR` and CPython has no frozen-module shadowing.
Boot behavior needs a flash and a serial capture across the USB re-enumeration.

Syntax-check everything before a build, since a MicroPython syntax error only
surfaces after a full Docker build and reflash:

```bash
for f in device/*.py host/host.py; do python3 -m py_compile "$f"; done
```

## Architecture

Everything is one text command protocol. Serial and HTTP are two front doors onto
the same parser and the same dispatcher:

```
serial (CDC)  ─┐
HTTP POST /api ┼─> protocol.parse() ─> Command ─> main._dispatch() ─> hid_device
macro player  ─┘
```

- **`protocol.py`** is pure parsing — no side effects, no hardware. `parse()` returns
  a `Command(kind, params)` on success or a plain `str` error on failure. That
  str-vs-object return is the error convention throughout; callers check
  `isinstance(result, str)`.
- **`main.py`** owns all execution. `_dispatch()` is one long `if k == ...` chain
  keyed on `Command.kind`, and is the single place hardware gets touched. It also
  holds module-global state (`_capture`, `_autorun_handle`, `_web_server_started`).
  `main()` runs at import time.
- **`boot.py`** runs before `main.py` and initializes the USB composite device.
  It has two personalities, chosen by `config.get_usb_mode()`: `hid` (CDC +
  keyboard + mouse + absolute mouse) and `pad` (CDC + Switch gamepad). It exports
  `keyboard`, `mouse`, `abs_mouse`, `gamepad` and `usb_mode` for `main.py`.
  Nothing else may touch USB. Every step is guarded — this runs before anything
  can recover it, so a bad config or a failed pad init falls back to `hid` rather
  than leaving the device with no USB at all.
- **`web.py`** is a hand-rolled asyncio HTTP/1.0 server serving exactly three
  routes (`GET /`, `GET /health`, `POST /api`). The entire web UI is a single
  frozen `_HTML` string in this file. It calls back into `main._dispatch_from_web`;
  it never imports `main` (which would re-run `main()`).
- **`macros.py`** stores macros as one text file per macro under `/macros.d/` on
  the Pico filesystem and plays them back as an asyncio task. The `.d` suffix is
  load-bearing, see below.
- **`config.py`** is the only writer of `/config.json`. `save()` rewrites the whole
  file, so do not put frequently-changing data there — that is why macros live in
  their own files.

### Editing the web UI

`_HTML` is a Python triple-quoted string, so any literal backslash in the embedded
JavaScript must be doubled in the source: JS `split('\n')` must be written `\\n`
in `web.py`. Verify by extracting the constant with `ast` rather than importing:

```python
import ast; t = ast.parse(open("device/web.py").read())
```

### Never name an on-device path after a module

`sys.path` on the device is `['', '.frozen', '/lib']`, so **the filesystem root is
searched before frozen modules**. Any file or directory at `/` whose name matches a
frozen module shadows it. The macro store was originally `/macros`, which made
`import macros` resolve to the directory instead of the module — the device dropped
to a REPL on the first boot after a macro was saved, and only hardware testing found
it. Hence `/macros.d`. Anything new written to `/` needs an extension or a suffix
that is not a valid identifier. `main.py` migrates a legacy `/macros` before
importing the module; that call must stay above `import macros`.

### Macros

Command lines plus `sleep <ms>`. Bodies are compile-checked by
`macros.compile_body()` at save and at start, so failures surface with a line
number instead of mid-run with keys held down. The player yields
(`await asyncio.sleep_ms(0)`) between steps so the HTTP server stays responsive
and `macro stop` can always land.

`repeat <n>` / `end` is expanded inline by `compile_body()`, so the player never
sees it — it still walks a flat step list. That is deliberate: nesting or a runtime
loop would need a call stack and would complicate stop semantics for no gain. Since
expansion happens at compile time, a large count costs RAM rather than failing at
run time, hence `_MAX_STEPS` and `_MAX_REPEAT` in `macros.py`.

Invariant: **held keys and buttons must always be released** when a macro stops,
finishes, or raises. `_Player._run()` does this in a `finally`. Preserve it.

`_button_task()` polls `rp2.bootsel_button()` at 20 Hz as a physical start/stop.
Each read blocks interrupts and flash access for `MICROPY_HW_BOOTSEL_DELAY_US`
(8 us in the pinned MicroPython), so the poll interval is a real cost, not a free
one — do not raise the rate without rechecking that against USB HID timing. The
task exits quietly if `rp2.bootsel_button` is missing, so the feature degrades
rather than breaking boot.

`_wifi_watch_task()` rechecks the connection every 30 s and reconnects if it
dropped, then calls `_try_start_web()`. Before it existed `wifi.connect()` ran once
at boot with a 15 s window, and a single miss meant no network until someone
physically intervened — which on a device that lives inside a games console is
expensive. Do not "simplify" this back to a one-shot connect.

Autorun starts a macro after boot independently of WiFi. Safety constraints, all
deliberate — do not relax them without understanding why they exist:

- `micropython.kbd_intr(-1)` in `main()` **disables Ctrl-C on the device.** There is
  no REPL escape. The autorun startup delay is the only software intervention window.
- Autorun delay has a 3000 ms floor (`MIN_AUTORUN_DELAY_MS` in `protocol.py`), and
  `macro stop` during that window cancels the pending run.
- `reboot` and nested `macro_*` commands are rejected inside macro bodies. Autorun
  plus `reboot` is an unbreakable boot loop that requires a BOOTSEL reflash to clear.

### Switch pad mode

The Switch accepts only certain controllers, so `SwitchGamepadHID` reports the
descriptor and USB ids of a HORI Pokken Tournament Pro Pad (`0x0F0D` / `0x0092`).
**The descriptor and the 8-byte report layout are not free parameters** — they have
to match that controller or the console ignores the device. `tests/test_pad.py`
checks the descriptor's declared input size against `_PAD_REPORT_LEN`, which is the
cheap way to catch a mismatch that would otherwise fail silently on hardware.

`id_vendor` / `id_product` apply to the whole USB device, not one interface, so in
pad mode the board stops enumerating as a Raspberry Pi — `host/host.py` matches
both vendor ids for that reason.

Whether the Switch accepts a *composite* device (CDC serial alongside the gamepad)
is unverified. If it refuses, the fallback is `builtin_driver=False` for a
gamepad-only device, which costs the serial console entirely: WiFi and token would
have to be configured in `hid` mode first, and a WiFi failure in pad mode would
lock you out until you reflash.

Button and hat name tables live in `keycodes.py`, not `hid_device.py`, so that
`protocol.py` stays free of hardware imports — see the parse/dispatch split above.
That is load-bearing for the tests: `tests/test_macros.py` stubs only `uasyncio`,
and pulling `hid_device` into the parser would drag `micropython` and `usb.device`
in with it.

### hid_device state, and one inconsistency in it

`KeyboardHID` keeps a modifier byte plus a list of at most 6 held keycodes and
rebuilds the whole 8-byte report on every change. Two behaviors surprise people:

- `key_down` **silently drops the 7th key** (`if len(self._keys) < 6`). The command
  still returns `OK`, so an over-chorded macro fails invisibly.
- `type_chars` **does not preserve held keys** — it assigns `self._keys = [code]`
  per character and `[]` at the end, so `key type` releases anything being held.
  Every other keyboard method mutates the held set incrementally. If you change
  this, note that `key type` currently relies on that reset for correct repeated
  characters.

`MouseHID` keeps a button bitmask and chords correctly. `move()` chunks anything
past ±127 per axis into several reports; that loop is the least-exercised code in
the firmware, which is what `tests/` and the soak macro in the README target.

### Adding a command

Follow the existing `category_action` naming (`key tap`, `macro autorun`). Touch all
of: `protocol.py` (parse to a `Command`), `main.py` (`_dispatch` branch), the `_HTML`
command reference table in `web.py`, the `help` text in `host/host.py`, and the
command tables in `README.md`. Macro names become filenames — validate them through
`protocol.valid_macro_name()`.

## Releases

`.github/workflows/release.yml` runs on every push to `main` and derives the semver
tag from **conventional commit messages**, so commit subjects directly control
versioning: `feat:` minor, `fix:`/`deps:` patch, `feat!:` or a `BREAKING CHANGE:`
footer major. Commits with other prefixes (`chore:`, `ci:`, `docs:`) cut no release.
Tagging triggers a firmware build and attaches a zip of the `.uf2` plus setup
scripts. `update-micropython.yml` opens automated `deps:` bumps.

## Repo layout note

`origin` is the fork `dd36/pico-hid-proxy`; `upstream` is `rbnkr/pico-hid-proxy`.
