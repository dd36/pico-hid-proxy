# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Versions are cut automatically from conventional commit messages by
`.github/workflows/release.yml` on every push to `main`.

## [Unreleased]

### Added

- On-device macros: named command sequences stored on the Pico filesystem under
  `/macros/`, so a sequence keeps running with no host connected.
  - `macro save` / `end` / `abort` / `run` / `stop` / `list` / `show` / `delete` / `status`
  - `sleep <ms>` step, valid only inside a macro
  - `macro save <name>` alone begins line capture over serial; the API takes the
    body in the same command with embedded newlines
  - Playback runs as a background task and yields between steps, so the web UI
    and serial console stay responsive and `macro stop` always lands
  - Bodies are compile-checked on save and on start, rejecting an unknown key or
    malformed `sleep` with its line number rather than failing mid-run
  - Held keys and mouse buttons are always released when a macro stops, finishes,
    or raises
- Autorun: `macro autorun <name> <ms> [loop]` runs a macro after boot with a
  configurable delay, independently of WiFi so the device works standalone.
  `macro autorun off` disables it. Guarded by a 3000 ms minimum delay, cancellable
  with `macro stop` during that window, and `reboot` is rejected inside macro
  bodies — autorun plus a reboot is an unbreakable loop needing a BOOTSEL reflash,
  and Ctrl-C is disabled on the device.
- Macro editor and autorun panel in the web UI.
- `status` now reports free RAM and filesystem space.
- `CLAUDE.md` and this changelog.

### Fixed

- API request bodies were capped at 1 KB and read with a single `read()` call,
  which could return short even under the cap. Bodies are now read until
  content-length with a 16 KB cap; previously a multi-line request could be
  silently truncated into invalid JSON.

## [2.0.1] - 2026-07-04

### Changed

- Update MicroPython to v1.28.0 (#5).
- Release on `deps:` commits so MicroPython updates cut a release.
- Add a workflow to check for MicroPython updates.
- Remove the hardcoded MicroPython version from the README.
- Standardize the project name to Pico HID Proxy.

### Added

- MIT license.

## [2.0.0] - 2026-02-26

### Changed

- **Breaking:** renamed commands for consistent `category_action` naming (#4) —
  for example `tap` became `key tap` and `move` became `mouse move`.

## [1.3.0] - 2026-02-26

### Added

- Setup scripts for Windows and Linux (#3).

## [1.2.0] - 2026-02-26

### Added

- The API and web UI can be enabled independently (#2); both are off by default.

## [1.1.1] - 2026-02-26

### Fixed

- Make the build script executable.

## [1.1.0] - 2026-02-26

### Added

- WiFi web control interface: token-authenticated JSON API and a served web page
  for sending commands from any device on the network (#1).

## [1.0.0] - 2026-02-13

### Added

- Initial release: Pico 2 W as a USB HID keyboard and mouse, driven by a text
  command protocol over CDC serial, with keyboard, mouse, and absolute mouse
  HID interfaces and a Docker-based firmware build.

[Unreleased]: https://github.com/rbnkr/pico-hid-proxy/compare/v2.0.1...HEAD
[2.0.1]: https://github.com/rbnkr/pico-hid-proxy/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/rbnkr/pico-hid-proxy/compare/v1.3.0...v2.0.0
[1.3.0]: https://github.com/rbnkr/pico-hid-proxy/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/rbnkr/pico-hid-proxy/compare/v1.1.1...v1.2.0
[1.1.1]: https://github.com/rbnkr/pico-hid-proxy/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/rbnkr/pico-hid-proxy/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/rbnkr/pico-hid-proxy/releases/tag/v1.0.0
