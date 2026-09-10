# Pico HID Proxy

A Raspberry Pi Pico 2 W acting as a USB HID keyboard and mouse, controlled over serial or WiFi from a host PC or any device on the network.

![](.github/media/interface.png)

## Setup

### Flash Firmware

1. Hold BOOTSEL on the Pico and plug it in (or send `reboot bootloader` if already connected)
2. Copy `pico_hid_firmware.uf2` to the USB drive that appears

### Configure

Plug the Pico in normally and run the setup script for your OS. No dependencies required.

| OS | Script |
|---|---|
| Windows | `setup-windows.bat` |
| Linux / macOS | `./setup-linux.sh` |

The setup wizard walks you through WiFi configuration, API token, and enabling the web UI.

![](.github/media/setup.png)

> [!TIP]
> On Linux, you may need serial port permissions. The script will prompt you to add yourself to the `dialout` group or run with `sudo`.

### Manual Setup

If you prefer to configure manually, connect via the serial host script and run commands directly:

```
api token mysecrettoken
wifi connect MyNetwork MyPassword
webui enable
```

Credentials, token, and enable states persist across reboots — the Pico will auto-connect on power up.

## WiFi Web Control

The Pico can connect to a WiFi network and serve a web interface for sending commands from any device on the same network, no serial connection needed.

The API and web UI are disabled by default. Use `webui enable` to enable the web interface (this also enables the API). To enable only the API without the web UI, use `api enable` instead.

On success, the Pico prints the URL (e.g. `WEB http://192.168.1.42`). Open it in any browser to access the control page.

### API

The web interface uses a JSON API that can also be called directly:

```
curl -X POST http://PICO_IP/api \
  -H "Content-Type: application/json" \
  -d '{"cmd":"key type Hello","delay":0,"token":"mysecrettoken"}'
```

Response: `{"ok":true,"result":"OK"}`

The `delay` field (in milliseconds) adds a wait before executing the command.

## Macros

Macros are named command sequences stored on the Pico itself, so a sequence keeps
running with no host connected. Create and edit them in the web UI, or over serial.

A macro is one command per line. Blank lines and `#` comments are ignored, and
`sleep <ms>` waits between steps:

```
# gold farm loop
key down w
sleep 800
key up w
mouse move 120 0
sleep 300
key tap space
sleep 5000
```

A `repeat <n>` line and a matching `end` line wrap a block, running it n times
without writing it out by hand:

```
repeat 20
key down w
sleep 800
key up w
sleep 5000
end
key tap space
```

Blocks are expanded when the macro is compiled, so they cost nothing at run time
and a typo inside one still fails at save time with its line number. Blocks cannot
be nested, and a macro cannot expand past 4000 steps.

Run it once with `macro run gold1`, or forever with `macro run gold1 loop`.
`macro stop` ends it and releases every held key and button.

Playback is a background task, so the web UI and serial console stay responsive
while a macro runs — `macro stop` always lands.

### Creating macros over serial

`macro save <name>` on its own line starts capture. Every following line is
buffered until you finish with `macro end` (or discard with `macro abort`):

```
macro save gold1
key down w
sleep 800
key up w
macro end
```

Over the API, send the body in the same command with embedded newlines:

```
curl -X POST http://PICO_IP/api \
  -H "Content-Type: application/json" \
  -d '{"cmd":"macro save gold1\nkey down w\nsleep 800\nkey up w","token":"mysecrettoken"}'
```

Macros are compile-checked when saved, so an unknown key or a malformed `sleep`
is rejected up front with the offending line number rather than failing halfway
through a run with keys held down.

### Writing macros: HID limits worth knowing

**Up to 6 keys at once, and the 7th is silently dropped.** Standard boot-protocol
rollover. Modifiers (`shift`, `ctrl`, `alt`, `gui`) are held in a separate byte and
do *not* count against those six, so `key down shift` costs nothing. A macro that
over-chords still returns `OK` — the extra key simply never registers.

**`key type` releases every held key.** It rewrites the whole keyboard report per
character and clears it at the end, so this does not do what it looks like:

```
key down w
key type hello     # w is released here
key up w           # no-op, w was already gone
```

Use `key tap` per character if you need to type while a key is held — that adds to
the held set instead of replacing it.

**Mouse buttons chord freely.** Left, right and middle are bits in one mask, so any
combination can be held at once, and `mouse release` clears all of them. Keyboard
and mouse are separate HID interfaces, so holding keys while dragging is fine.

**Mouse deltas are signed bytes.** Anything beyond ±127 per axis is split into
multiple reports automatically, so `mouse move 400 400` is valid — it just becomes
several reports rather than one.

### Autorun

The Pico can run a macro automatically on power-up, with no host and no WiFi:

```
macro autorun gold1 10000 loop
```

That runs `gold1` in a loop 10 seconds after boot. `macro autorun off` disables it.

> [!WARNING]
> Autorun means the Pico starts driving the attached machine every time it gets
> power. The startup delay is your only chance to intervene — Ctrl-C is disabled
> on the device — so `macro stop` sent during the delay window cancels the
> pending run. The minimum delay is 3000 ms for this reason, and `reboot` is
> rejected inside a macro because autorun plus a reboot is an unbreakable loop
> that needs a BOOTSEL reflash to clear.

The delay also gives USB HID time to enumerate on the host; a macro firing
instantly at boot sends its first keystrokes nowhere.

### BOOTSEL button

The onboard BOOTSEL button doubles as a physical start/stop, so a running macro
can always be halted without a host, a network, or a power cycle:

| State | Press does |
|---|---|
| Macro running | Stops it and releases every held key and button |
| Autorun waiting out its delay | Cancels it |
| Idle, autorun configured | Starts that macro immediately, skipping the delay |
| Idle, no autorun configured | Releases all keys and buttons |

Holding BOOTSEL *while plugging in* still enters UF2 flash mode as usual — that is
ROM behavior that runs before any of this code, so flashing is unaffected.

## Project Structure

```
device/          MicroPython code that runs on the Pico (frozen into firmware)
macros.d/        Saved macros on the Pico filesystem (created on first save)
host/            Setup scripts and interactive serial host
firmware/        Built UF2 firmware output
input_monitor/   Windows tool to detect real vs emulated input
```

## Building Firmware

The device code is frozen into a custom MicroPython firmware, producing a single `.uf2` file. The build runs in Docker. No local toolchain needed.

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/)

### Build

```
./build_firmware.sh
```

This builds MicroPython for `RPI_PICO2_W` with all `device/` code and the `usb-device-hid` library frozen in.

Two files are written to `firmware/`:

| File | Purpose |
|---|---|
| `pico-hid-proxy-<board>-<version>.uf2` | Versioned archive, one per build. Kept, never overwritten. |
| `pico_hid_firmware.uf2` | Copy of the latest build, stable name for scripts and CI. |

The version comes from `git describe`, so every image traces back to a commit. A
`-dirty` suffix means it was built from uncommitted changes — worth noticing before
you flash something you cannot reproduce.

Keeping the versioned copies means you always have a known-good image to roll back
to. The filename itself is irrelevant when flashing: the bootloader identifies a UF2
by its header and rejects images built for the wrong chip, so you can drag either
file onto the drive.

To update MicroPython version edit the `Dockerfile` or run with `--build-arg MICROPYTHON_TAG=v1.27.0` arg.

The first build takes a few minutes (cloning MicroPython, compiling toolchain). Subsequent builds after code changes are fast thanks to Docker layer caching.

To force a clean rebuild:

```
./build_firmware.sh --clean
```

## Host Script

An interactive serial console for sending commands directly to the Pico.

### Prerequisites

- Python 3.12+

Optionally create a conda environment:

```
conda create -n pico-hid python=3.12 -y
conda activate pico-hid
```

Install dependencies:

```
pip install -r requirements.txt
```

### Connect

```
python host/host.py          # auto-detect port
python host/host.py COM5     # manual port
```

Type `help` once connected for a list of commands.

## Commands

### Keyboard

| Command | Description |
|---|---|
| `key tap <name>` | Press and release a key |
| `key down <name>` / `key up <name>` | Hold / release a key |
| `key mod <mods> <key>` | Modifier combo (e.g. `key mod ctrl+shift esc`) |
| `key type <text>` | Type a string |
| `key release` | Release all held keys |

### Mouse

| Command | Description |
|---|---|
| `mouse move <dx> <dy>` | Relative mouse move |
| `mouse abs <x> <y>` | Absolute mouse move (0–32767) |
| `mouse click <btn>` | Click left/right/middle |
| `mouse down <btn>` / `mouse up <btn>` | Hold / release button |
| `mouse scroll <n>` | Scroll (positive = up) |
| `mouse release` | Release all held buttons |

### Macros

| Command | Description |
|---|---|
| `sleep <ms>` | Wait (only valid inside a macro) |
| `repeat <n>` | Start a block; `end` closes it. Runs it n times (macro only, no nesting) |
| `macro save <name>` | Start serial capture, or save a body sent in the same command |
| `macro end` / `macro abort` | Finish or discard a serial capture |
| `macro run <name> [loop]` | Run a macro once, or repeat until stopped |
| `macro stop` | Stop the running macro and cancel a pending autorun |
| `macro list` | List saved macros |
| `macro show <name>` | Print a macro body |
| `macro delete <name>` | Delete a macro |
| `macro status` | Show what is running |
| `macro autorun <name> <ms> [loop]` | Run `<name>` `<ms>` after boot (minimum 3000) |
| `macro autorun off` | Disable autorun |
| `macro autorun status` | Show the current autorun setting |

### WiFi

| Command | Description |
|---|---|
| `wifi set <ssid> <password>` | Save WiFi credentials without connecting |
| `wifi get` | Show saved credentials |
| `wifi connect [ssid] [password]` | Connect to WiFi (saves credentials if provided, uses saved if not) |
| `wifi disconnect` | Disconnect from WiFi |
| `wifi status` | Show connection status, IP, and signal strength |
| `wifi clear` | Delete saved credentials and disconnect |

### API

| Command | Description |
|---|---|
| `api token <value>` | Set the API token for web access |
| `api enable` | Enable the API |
| `api disable` | Disable the API (also disables web UI) |
| `api status` | Show whether the API is enabled or disabled |

### Web UI

| Command | Description |
|---|---|
| `webui enable` | Enable the web UI (also enables the API) |
| `webui disable` | Disable the web UI |
| `webui status` | Show whether the web UI is enabled or disabled |

### System

| Command | Description |
|---|---|
| `ping` | Test connection (returns PONG) |
| `status` | Show overall system status (wifi, api, webui, macro, autorun, memory, storage) |
| `reboot` | Restart the Pico |
| `reboot bootloader` | Reboot Pico into BOOTSEL (UF2 flash) mode |

## Input Monitor

A separate Windows tool that uses low-level hooks (`WH_KEYBOARD_LL` / `WH_MOUSE_LL`) to detect whether keyboard and mouse events are real hardware input or emulated/injected. Checks the `LLKHF_INJECTED` and `LLMHF_INJECTED` flags set by the OS on synthetic input.

Run the monitor (requires native Windows Python, does not work with WSL):

```
python input_monitor/main.py
```

Press Ctrl+C to stop the monitor.

## Licenses

This project's code is released under the [MIT License](LICENSE).

The firmware is built for Raspberry Pi Pico 2 W and includes MicroPython (MIT), Pico SDK (BSD-3-Clause), TinyUSB (MIT), lwIP (BSD), cyw43-driver and BTstack (licensed by Raspberry Pi Ltd for use with Pico W hardware).
