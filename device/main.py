# main.py — Async command loop for USB HID keyboard+mouse + WiFi web control
# Reads newline-terminated ASCII commands from CDC serial and/or HTTP API,
# dispatches to keyboard/mouse HID devices.

import sys
import time
import select
import gc
import os
import machine
import micropython
import uasyncio as asyncio

from boot import keyboard, mouse, abs_mouse
from protocol import parse, Command, MIN_AUTORUN_DELAY_MS
import config
import wifi


def _migrate_legacy_macro_dir():
    """Move a pre-existing /macros store to /macros.d.

    /macros shadowed the frozen `macros` module (sys.path is
    ['', '.frozen', '/lib'], so the filesystem wins), which dropped the device
    to a REPL on the first boot after a macro was saved. This must run before
    `import macros` below.
    """
    try:
        os.stat("/macros")
    except OSError:
        return  # nothing to migrate
    try:
        os.stat("/macros.d")
    except OSError:
        try:
            os.rename("/macros", "/macros.d")
        except OSError:
            pass
        return
    # Both exist: move the files across, then drop the shadowing directory.
    try:
        names = os.listdir("/macros")
    except OSError:
        return
    for n in names:
        try:
            os.rename("/macros/" + n, "/macros.d/" + n)
        except OSError:
            pass
    try:
        os.rmdir("/macros")
    except OSError:
        pass


_migrate_legacy_macro_dir()

import macros


def _respond(msg):
    """Write a response line to serial output."""
    sys.stdout.write(msg + "\n")


_web_server_started = False

# Serial macro capture state: {"name": str, "lines": [str]} while capturing.
_capture = None

# Handle for a pending autorun task during its startup delay.
_autorun_handle = None


def _release_all():
    """Release every held key and mouse button."""
    keyboard.release_all()
    mouse.release_all()


def _save_macro(name, body):
    """Compile-check then persist a macro. Returns a response string."""
    steps = macros.compile_body(body)
    if isinstance(steps, str):
        return "ERR macro '{}' {}".format(name, steps)
    if not steps:
        return "ERR macro '{}' is empty (no runnable commands)".format(name)
    try:
        macros.save(name, body)
    except OSError as e:
        return "ERR macro save failed: {}".format(e)
    return "OK macro '{}' saved ({} steps)".format(name, len(steps))


def _stop_all():
    """Stop a running macro and cancel any autorun still in its delay window."""
    global _autorun_handle
    msgs = []
    if _autorun_handle is not None:
        _autorun_handle.cancel()
        _autorun_handle = None
        msgs.append("OK autorun cancelled")
    msgs.append(macros.player.stop())
    return "\n".join(msgs)


def _capture_feed(line):
    """Consume one serial line during macro capture. Returns a reply or None."""
    global _capture
    low = line.strip().lower()
    if low == "macro end":
        name = _capture["name"]
        body = "\n".join(_capture["lines"])
        _capture = None
        return _save_macro(name, body)
    if low == "macro abort":
        name = _capture["name"]
        _capture = None
        return "OK capture of '{}' aborted".format(name)
    _capture["lines"].append(line.rstrip())
    return None


def _resource_lines():
    """Return status lines for free RAM and filesystem space."""
    gc.collect()
    free = gc.mem_free()
    total = free + gc.mem_alloc()
    lines = ["mem: {} B free / {} B total".format(free, total)]
    try:
        st = os.statvfs("/")
        frsize = st[1]
        fs_total = st[2] * frsize
        fs_free = st[3] * frsize
        lines.append("flash: {} KB free / {} KB total".format(
            fs_free // 1024, fs_total // 1024))
    except OSError:
        lines.append("flash: unavailable")
    return lines


def _dispatch(cmd, from_web=False):
    """Execute a parsed command. Returns response string."""
    global _capture
    k = cmd.kind
    p = cmd.params

    # System
    if k == "ping":
        return "PONG"
    if k == "reboot":
        _respond("OK")
        time.sleep(0.1)
        machine.reset()
        return None
    if k == "reboot_bootloader":
        _respond("OK")
        time.sleep(0.1)
        machine.bootloader()
        return None

    # WiFi / Web
    if k == "wifi_set":
        config.set_wifi(p["ssid"], p["password"])
        return "OK credentials saved for '{}'".format(p["ssid"])
    if k == "wifi_get":
        ssid, password = config.get_wifi()
        if not ssid:
            return "no saved wifi credentials"
        if from_web:
            password = "****"
        return "ssid={} password={}".format(ssid, password)
    if k == "wifi_connect":
        ssid = p.get("ssid")
        password = p.get("password")
        if ssid and password:
            config.set_wifi(ssid, password)
        else:
            ssid, password = config.get_wifi()
            if not ssid or not password:
                return "ERR no saved wifi credentials (use wifi set <ssid> <password>)"
        ok, msg = wifi.connect(ssid, password)
        if ok:
            _try_start_web()
        return ("OK " + msg) if ok else ("ERR " + msg)
    if k == "wifi_disconnect":
        wifi.disconnect()
        return "OK disconnected"
    if k == "wifi_status":
        return wifi.status_str()
    if k == "wifi_clear":
        wifi.disconnect()
        config.clear_wifi()
        return "OK wifi credentials cleared"
    if k == "api_token":
        config.set_web_password(p["token"])
        if _web_server_started:
            import web
            web.set_password(p["token"])
        return "OK api token set"
    if k == "api_enable":
        if not config.get_web_password():
            return "ERR no api token set (use api token <value> first)"
        config.set_api_enabled(True)
        if _web_server_started:
            import web
            web.set_api_enabled(True)
        _try_start_web()
        return "OK api enabled"
    if k == "api_disable":
        config.set_api_enabled(False)
        config.set_webui_enabled(False)
        if _web_server_started:
            import web
            web.set_api_enabled(False)
            web.set_webui_enabled(False)
        return "OK api disabled (webui also disabled)"
    if k == "api_status":
        enabled = config.get_api_enabled()
        running = _web_server_started and enabled
        state = "enabled" if enabled else "disabled"
        return "api {} ({})".format(state, "running" if running else "stopped")
    if k == "webui_enable":
        if not config.get_web_password():
            return "ERR no api token set (use api token <value> first)"
        config.set_webui_enabled(True)
        config.set_api_enabled(True)
        if _web_server_started:
            import web
            web.set_webui_enabled(True)
            web.set_api_enabled(True)
        _try_start_web()
        return "OK webui enabled (api also enabled)"
    if k == "webui_disable":
        config.set_webui_enabled(False)
        if _web_server_started:
            import web
            web.set_webui_enabled(False)
        return "OK webui disabled"
    if k == "webui_status":
        enabled = config.get_webui_enabled()
        running = _web_server_started and enabled
        state = "enabled" if enabled else "disabled"
        return "webui {} ({})".format(state, "running" if running else "stopped")
    if k == "status":
        lines = []
        ssid, _ = config.get_wifi()
        lines.append("wifi credentials: {}".format("set" if ssid else "not set"))
        lines.append("wifi: {}".format(wifi.status_str()))
        api_on = config.get_api_enabled()
        api_running = _web_server_started and api_on
        lines.append("api: {} ({})".format(
            "enabled" if api_on else "disabled",
            "running" if api_running else "stopped"))
        webui_on = config.get_webui_enabled()
        webui_running = _web_server_started and webui_on
        lines.append("webui: {} ({})".format(
            "enabled" if webui_on else "disabled",
            "running" if webui_running else "stopped"))
        lines.append(macros.player.status())
        auto_name, auto_delay, auto_loop = config.get_autorun()
        if auto_name:
            lines.append("autorun: '{}' after {} ms{}".format(
                auto_name, auto_delay, " loop" if auto_loop else ""))
        else:
            lines.append("autorun: disabled")
        lines.extend(_resource_lines())
        return "\n".join(lines)

    # Keyboard
    if k == "key_tap":
        keyboard.press_key(p["mod"], p["code"])
        return "OK"
    if k == "key_down":
        keyboard.key_down(p["mod"], p["code"])
        return "OK"
    if k == "key_up":
        keyboard.key_up(p["mod"], p["code"])
        return "OK"
    if k == "key_mod":
        keyboard.mod_key(p["mod"], p["code"])
        return "OK"
    if k == "key_type":
        keyboard.type_chars(p["chars"])
        return "OK"
    if k == "key_release":
        keyboard.release_all()
        return "OK"

    # Mouse
    if k == "mouse_abs":
        abs_mouse.move_abs(p["x"], p["y"])
        return "OK"
    if k == "mouse_move":
        mouse.move(p["dx"], p["dy"])
        return "OK"
    if k == "mouse_click":
        mouse.click(p["button"])
        return "OK"
    if k == "mouse_down":
        mouse.button_down(p["button"])
        return "OK"
    if k == "mouse_up":
        mouse.button_up(p["button"])
        return "OK"
    if k == "mouse_scroll":
        mouse.scroll(p["amount"])
        return "OK"
    if k == "mouse_release":
        mouse.release_all()
        return "OK"

    # Macros
    if k == "macro_capture_begin":
        if from_web:
            return "ERR macro save over the API must include the body in the same command"
        if _capture is not None:
            return "ERR already capturing '{}' (macro end / macro abort)".format(
                _capture["name"])
        if macros.player.is_running():
            return "ERR a macro is running (macro stop first)"
        _capture = {"name": p["name"], "lines": []}
        return "OK capturing '{}' - finish with 'macro end' (or 'macro abort')".format(
            p["name"])
    if k == "macro_capture_end" or k == "macro_capture_abort":
        return "ERR not capturing (start with 'macro save <name>')"
    if k == "macro_save":
        if macros.player.is_running() and macros.player.name == p["name"]:
            return "ERR macro '{}' is running (macro stop first)".format(p["name"])
        return _save_macro(p["name"], p["body"])
    if k == "macro_run":
        return macros.player.start(p["name"], p["loop"])
    if k == "macro_stop":
        return _stop_all()
    if k == "macro_status":
        return macros.player.status()
    if k == "macro_list":
        names = macros.list_names()
        return "\n".join(names) if names else "no macros saved"
    if k == "macro_show":
        if not macros.exists(p["name"]):
            return "ERR macro '{}' not found".format(p["name"])
        try:
            return macros.load(p["name"])
        except OSError as e:
            return "ERR macro read failed: {}".format(e)
    if k == "macro_delete":
        name = p["name"]
        if not macros.exists(name):
            return "ERR macro '{}' not found".format(name)
        if macros.player.is_running() and macros.player.name == name:
            return "ERR macro '{}' is running (macro stop first)".format(name)
        try:
            macros.delete(name)
        except OSError as e:
            return "ERR macro delete failed: {}".format(e)
        auto_name, _, _ = config.get_autorun()
        if auto_name == name:
            config.clear_autorun()
            return "OK macro '{}' deleted (autorun cleared)".format(name)
        return "OK macro '{}' deleted".format(name)
    if k == "macro_autorun_set":
        if not macros.exists(p["name"]):
            return "ERR macro '{}' not found".format(p["name"])
        config.set_autorun(p["name"], p["delay"], p["loop"])
        return "OK autorun '{}' after {} ms{}".format(
            p["name"], p["delay"], " (loop)" if p["loop"] else "")
    if k == "macro_autorun_off":
        config.clear_autorun()
        return "OK autorun disabled"
    if k == "macro_autorun_status":
        name, delay, loop = config.get_autorun()
        if not name:
            return "autorun: disabled"
        missing = "" if macros.exists(name) else "  [macro not found]"
        return "autorun: '{}' after {} ms{}{}".format(
            name, delay, " loop" if loop else "", missing)

    return "ERR unknown command kind"


def _dispatch_from_web(cmd_str):
    """Entry point for web server — parse and execute a command string."""
    result = parse(cmd_str)
    if isinstance(result, str):
        return "ERR " + result
    try:
        resp = _dispatch(result, from_web=True)
        return resp if resp else "OK"
    except Exception as e:
        return "ERR " + str(e)


def _try_start_web():
    """Start web server if WiFi is connected, a token is set, and api/webui is enabled."""
    global _web_server_started
    if _web_server_started:
        return
    api_on = config.get_api_enabled()
    webui_on = config.get_webui_enabled()
    if not api_on and not webui_on:
        _respond("WEB skipped (api and webui disabled)")
        return
    web_pass = config.get_web_password()
    if not web_pass:
        _respond("WEB skipped (no webpass set)")
        return
    if not wifi.is_connected():
        return
    import web

    web.start(web_pass, _dispatch_from_web, api_on, webui_on)
    asyncio.create_task(web.run_server())
    _web_server_started = True
    ip = wifi.get_ip()
    _respond("WEB http://{}".format(ip))


async def _serial_task():
    """Async task: read and process serial commands."""
    poller = select.poll()
    poller.register(sys.stdin.buffer, select.POLLIN)
    buf = bytearray()

    while True:
        events = poller.poll(0)
        if events:
            data = sys.stdin.buffer.read(1)
            if data:
                b = data[0]
                if b == 0x0A:  # newline
                    try:
                        line = buf.decode("utf-8")
                    except Exception:
                        _respond("ERR invalid utf-8")
                        buf = bytearray()
                        await asyncio.sleep_ms(0)
                        continue
                    buf = bytearray()

                    if _capture is not None:
                        resp = _capture_feed(line)
                        if resp is not None:
                            _respond(resp)
                        await asyncio.sleep_ms(0)
                        continue

                    if not line.strip():
                        await asyncio.sleep_ms(0)
                        continue

                    result = parse(line)
                    if isinstance(result, str):
                        _respond("ERR " + result)
                    else:
                        try:
                            resp = _dispatch(result)
                            if resp is not None:
                                _respond(resp)
                        except Exception as e:
                            _respond("ERR " + str(e))
                elif b == 0x0D:  # ignore CR
                    pass
                else:
                    buf.append(b)
        else:
            await asyncio.sleep_ms(1)


def _button_action():
    """BOOTSEL press: stop whatever is running, else start the autorun macro."""
    if macros.player.is_running() or _autorun_handle is not None:
        return "BUTTON " + _stop_all().replace("\n", "; ")
    name, _delay, loop = config.get_autorun()
    if not name:
        # Nothing to start. Release anyway: with Ctrl-C disabled on the device
        # this is the only guaranteed way to clear a key stranded by a dropped
        # connection, and it is a no-op when nothing is held.
        _release_all()
        return "BUTTON idle (no autorun macro set) - released all keys"
    if not macros.exists(name):
        return "BUTTON autorun macro '{}' not found".format(name)
    # Started by hand, so skip the boot delay.
    return "BUTTON " + macros.player.start(name, loop)


async def _button_task():
    """Poll the BOOTSEL button as a physical start/stop.

    Each read blocks interrupts and flash access for
    MICROPY_HW_BOOTSEL_DELAY_US (8 us). At 20 Hz that is a ~0.02% duty cycle,
    well clear of anything USB HID timing would notice.
    """
    try:
        import rp2

        rp2.bootsel_button()
    except (ImportError, AttributeError):
        return  # not available on this build; feature simply stays off
    prev = False
    while True:
        try:
            now = bool(rp2.bootsel_button())
        except Exception:
            return
        if now and not prev:  # rising edge; 50 ms poll doubles as debounce
            try:
                _respond(_button_action())
            except Exception as e:
                _respond("BUTTON ERR " + str(e))
        prev = now
        await asyncio.sleep_ms(50)


async def _autorun_task(name, delay, loop):
    """Wait out the startup window, then start the configured macro."""
    global _autorun_handle
    _respond("AUTORUN '{}' in {} ms (send 'macro stop' to cancel)".format(
        name, delay))
    await asyncio.sleep_ms(delay)
    _autorun_handle = None
    _respond(macros.player.start(name, loop))


def _start_autorun():
    """Schedule the autorun macro. Runs whether or not WiFi came up."""
    global _autorun_handle
    name, delay, loop = config.get_autorun()
    if not name:
        return
    if not macros.exists(name):
        _respond("AUTORUN skipped (macro '{}' not found)".format(name))
        return
    if delay < MIN_AUTORUN_DELAY_MS:
        delay = MIN_AUTORUN_DELAY_MS
    _autorun_handle = asyncio.create_task(_autorun_task(name, delay, loop))


async def _main_async():
    """Connect WiFi if configured, start web server, run serial loop."""
    macros.player.bind(_dispatch, _respond, _release_all)

    ssid, password = config.get_wifi()
    if ssid and password:
        try:
            ok, msg = wifi.connect(ssid, password)
            if ok:
                _respond("WIFI " + msg)
                _try_start_web()
            else:
                _respond("WIFI " + msg)
        except Exception:
            pass

    # Autorun is deliberately independent of WiFi so the device works
    # standalone; the delay window and the BOOTSEL button are the ways to
    # intervene.
    asyncio.create_task(_button_task())
    _start_autorun()

    await _serial_task()


def main():
    time.sleep(2)
    micropython.kbd_intr(-1)

    try:
        asyncio.run(_main_async())
    except KeyboardInterrupt:
        pass


main()
