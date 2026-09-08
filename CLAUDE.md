# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Raspberry Pi Pico 2 W (RP2350) that presents itself to a host machine as a real
USB HID keyboard and mouse, driven remotely over serial or WiFi. `device/` is
MicroPython that runs on the Pico; `host/` runs on your computer.

## Build and flash

```bash
./build_firmware.sh                  # Docker build -> firmware/pico_hid_firmware.uf2
BOARD=RPI_PICO_W ./build_firmware.sh # override board (default RPI_PICO2_W)
```

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
- **`boot.py`** runs before `main.py` and initializes the USB composite device
  (CDC + keyboard + mouse + absolute mouse). It exports `keyboard`, `mouse`, and
  `abs_mouse` singletons that `main.py` imports. Nothing else may touch USB.
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

Invariant: **held keys and buttons must always be released** when a macro stops,
finishes, or raises. `_Player._run()` does this in a `finally`. Preserve it.

`_button_task()` polls `rp2.bootsel_button()` at 20 Hz as a physical start/stop.
Each read blocks interrupts and flash access for `MICROPY_HW_BOOTSEL_DELAY_US`
(8 us in the pinned MicroPython), so the poll interval is a real cost, not a free
one — do not raise the rate without rechecking that against USB HID timing. The
task exits quietly if `rp2.bootsel_button` is missing, so the feature degrades
rather than breaking boot.

Autorun starts a macro after boot independently of WiFi. Safety constraints, all
deliberate — do not relax them without understanding why they exist:

- `micropython.kbd_intr(-1)` in `main()` **disables Ctrl-C on the device.** There is
  no REPL escape. The autorun startup delay is the only software intervention window.
- Autorun delay has a 3000 ms floor (`MIN_AUTORUN_DELAY_MS` in `protocol.py`), and
  `macro stop` during that window cancels the pending run.
- `reboot` and nested `macro_*` commands are rejected inside macro bodies. Autorun
  plus `reboot` is an unbreakable boot loop that requires a BOOTSEL reflash to clear.

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
