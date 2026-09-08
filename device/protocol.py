# Command parser for USB HID text protocol
# All commands are newline-terminated ASCII.

from keycodes import keyname_to_code, char_to_report, MODIFIER_KEYS


class Command:
    """Parsed command with type and parameters."""
    __slots__ = ("kind", "params")

    def __init__(self, kind, params=None):
        self.kind = kind
        self.params = params or {}


def parse(line):
    """Parse a command line into a Command object.

    Returns a Command on success, or a string error message on failure.
    """
    line = line.strip()
    if not line:
        return "empty command"

    parts = line.split(None, 1)
    verb = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""

    # --- System commands ---
    if verb == "ping":
        return Command("ping")

    if verb == "sleep":
        return ("sleep: only valid inside a macro "
                "(use the API 'delay' field for a one-off wait)")

    if verb == "status":
        return Command("status")

    if verb == "reboot":
        if not rest:
            return Command("reboot")
        sub = rest.split()[0].lower()
        if sub == "bootloader":
            return Command("reboot_bootloader")
        return "reboot: unknown subcommand '{}' (bootloader)".format(sub)

    # --- WiFi / Web commands ---
    if verb == "wifi":
        if not rest:
            return "wifi: missing subcommand (set/get/connect/disconnect/status/clear)"
        wifi_parts = rest.split(None, 1)
        sub = wifi_parts[0].lower()
        sub_rest = wifi_parts[1] if len(wifi_parts) > 1 else ""

        if sub == "set":
            args = sub_rest.split(None, 1)
            if len(args) < 2:
                return "wifi set: need <ssid> <password>"
            return Command("wifi_set", {"ssid": args[0], "password": args[1]})

        if sub == "connect":
            args = sub_rest.split(None, 1)
            if len(args) == 0 or not args[0]:
                return Command("wifi_connect", {})
            if len(args) < 2:
                return "wifi connect: need both <ssid> <password>, or no arguments to use saved"
            return Command("wifi_connect", {"ssid": args[0], "password": args[1]})

        if sub == "get":
            return Command("wifi_get")

        if sub == "disconnect":
            return Command("wifi_disconnect")

        if sub == "status":
            return Command("wifi_status")

        if sub == "clear":
            return Command("wifi_clear")

        return "wifi: unknown subcommand '{}' (set/get/connect/disconnect/status/clear)".format(sub)

    if verb == "api":
        if not rest:
            return "api: missing subcommand (token/enable/disable/status)"
        api_parts = rest.split(None, 1)
        sub = api_parts[0].lower()
        sub_rest = api_parts[1] if len(api_parts) > 1 else ""

        if sub == "token":
            if not sub_rest.strip():
                return "api token: missing token value"
            return Command("api_token", {"token": sub_rest.strip()})

        if sub == "enable":
            return Command("api_enable")

        if sub == "disable":
            return Command("api_disable")

        if sub == "status":
            return Command("api_status")

        return "api: unknown subcommand '{}'".format(sub)

    if verb == "webui":
        if not rest:
            return "webui: missing subcommand (enable/disable/status)"
        sub = rest.split()[0].lower()

        if sub == "enable":
            return Command("webui_enable")

        if sub == "disable":
            return Command("webui_disable")

        if sub == "status":
            return Command("webui_status")

        return "webui: unknown subcommand '{}'".format(sub)

    # --- Macro commands ---
    if verb == "macro":
        return _parse_macro(rest)

    # --- Keyboard commands ---
    if verb == "key":
        if not rest:
            return "key: missing subcommand (tap/down/up/mod/type/release)"
        sub_parts = rest.split(None, 1)
        sub = sub_parts[0].lower()
        sub_rest = sub_parts[1] if len(sub_parts) > 1 else ""

        if sub == "tap":
            if not sub_rest:
                return "key tap: missing key name"
            resolved = keyname_to_code(sub_rest.strip())
            if resolved is None:
                return "key tap: unknown key '{}'".format(sub_rest.strip())
            mod, code = resolved
            return Command("key_tap", {"mod": mod, "code": code})

        if sub == "down":
            if not sub_rest:
                return "key down: missing key name"
            resolved = keyname_to_code(sub_rest.strip())
            if resolved is None:
                return "key down: unknown key '{}'".format(sub_rest.strip())
            mod, code = resolved
            return Command("key_down", {"mod": mod, "code": code})

        if sub == "up":
            if not sub_rest:
                return "key up: missing key name"
            resolved = keyname_to_code(sub_rest.strip())
            if resolved is None:
                return "key up: unknown key '{}'".format(sub_rest.strip())
            mod, code = resolved
            return Command("key_up", {"mod": mod, "code": code})

        if sub == "mod":
            if not sub_rest:
                return "key mod: missing modifiers and key"
            mod_parts = sub_rest.split()
            if len(mod_parts) < 2:
                return "key mod: need <mods> <key>"
            mod_str = mod_parts[0]
            key_name = mod_parts[1]
            # Parse modifier combo like "ctrl+shift"
            mod_bits = 0
            for m in mod_str.lower().split("+"):
                m = m.strip()
                if m not in MODIFIER_KEYS:
                    return "key mod: unknown modifier '{}'".format(m)
                mod_bits |= MODIFIER_KEYS[m]
            resolved = keyname_to_code(key_name)
            if resolved is None:
                return "key mod: unknown key '{}'".format(key_name)
            _, code = resolved
            return Command("key_mod", {"mod": mod_bits, "code": code})

        if sub == "type":
            if not sub_rest:
                return "key type: missing text"
            # Validate all characters are typeable
            chars = []
            for ch in sub_rest:
                result = char_to_report(ch)
                if result is None:
                    return "key type: unsupported character '{}'".format(ch)
                chars.append(result)
            return Command("key_type", {"chars": chars})

        if sub == "release":
            return Command("key_release")

        return "key: unknown subcommand '{}' (tap/down/up/mod/type/release)".format(sub)

    # --- Mouse commands ---
    if verb == "mouse":
        if not rest:
            return "mouse: missing subcommand"
        sub_parts = rest.split(None, 1)
        sub = sub_parts[0].lower()
        sub_rest = sub_parts[1] if len(sub_parts) > 1 else ""

        if sub == "abs":
            args = sub_rest.split()
            if len(args) < 2:
                return "mouse abs: need <x> <y>"
            try:
                x = int(args[0])
                y = int(args[1])
            except ValueError:
                return "mouse abs: x/y must be integers"
            return Command("mouse_abs", {"x": x, "y": y})

        if sub == "move":
            args = sub_rest.split()
            if len(args) < 2:
                return "mouse move: need <dx> <dy>"
            try:
                dx = int(args[0])
                dy = int(args[1])
            except ValueError:
                return "mouse move: dx/dy must be integers"
            return Command("mouse_move", {"dx": dx, "dy": dy})

        if sub == "click":
            btn = sub_rest.strip().lower()
            if not btn:
                return "mouse click: missing button"
            btn_bit = _parse_button(btn)
            if btn_bit is None:
                return "mouse click: unknown button '{}'".format(btn)
            return Command("mouse_click", {"button": btn_bit})

        if sub == "down":
            btn = sub_rest.strip().lower()
            if not btn:
                return "mouse down: missing button"
            btn_bit = _parse_button(btn)
            if btn_bit is None:
                return "mouse down: unknown button '{}'".format(btn)
            return Command("mouse_down", {"button": btn_bit})

        if sub == "up":
            btn = sub_rest.strip().lower()
            if not btn:
                return "mouse up: missing button"
            btn_bit = _parse_button(btn)
            if btn_bit is None:
                return "mouse up: unknown button '{}'".format(btn)
            return Command("mouse_up", {"button": btn_bit})

        if sub == "scroll":
            if not sub_rest.strip():
                return "mouse scroll: missing amount"
            try:
                amount = int(sub_rest.strip())
            except ValueError:
                return "mouse scroll: amount must be integer"
            return Command("mouse_scroll", {"amount": amount})

        if sub == "release":
            return Command("mouse_release")

        return "mouse: unknown subcommand '{}'".format(sub)

    return "unknown command '{}'".format(verb)


def _one_name(arg, ctx):
    """Return (name, None) or (None, error). Rejects extra tokens outright so
    'macro save bad name' fails loudly instead of quietly saving as 'bad'."""
    parts = arg.split()
    if not parts:
        return None, "{}: missing name".format(ctx)
    if len(parts) > 1:
        return None, "{}: unexpected extra argument '{}' (names cannot contain spaces)".format(
            ctx, parts[1])
    if not valid_macro_name(parts[0]):
        return None, "{}: invalid name '{}' (letters, digits, - and _ only, max {} chars)".format(
            ctx, parts[0], _MAX_NAME_LEN)
    return parts[0], None


def _parse_macro(rest):
    """Parse a 'macro ...' command.

    'macro save <name>' followed by newline-separated body lines saves
    immediately (the web/API path). 'macro save <name>' alone begins
    line-by-line capture over serial, ended with 'macro end'.
    """
    if not rest:
        return ("macro: missing subcommand "
                "(save/end/abort/run/stop/list/show/delete/status/autorun)")

    nl = rest.find("\n")
    if nl == -1:
        head, body = rest, None
    else:
        head, body = rest[:nl], rest[nl + 1 :]

    hparts = head.split(None, 1)
    sub = hparts[0].lower()
    arg = hparts[1].strip() if len(hparts) > 1 else ""

    if sub == "save":
        name, err = _one_name(arg, "macro save")
        if err:
            return err
        if body is None:
            return Command("macro_capture_begin", {"name": name})
        return Command("macro_save", {"name": name, "body": body})

    if sub == "end":
        return Command("macro_capture_end")

    if sub == "abort":
        return Command("macro_capture_abort")

    if sub == "run":
        args = arg.split()
        if not args:
            return "macro run: missing name"
        if not valid_macro_name(args[0]):
            return "macro run: invalid name '{}'".format(args[0])
        loop = False
        if len(args) > 1:
            if args[1].lower() != "loop":
                return "macro run: unknown option '{}' (loop)".format(args[1])
            loop = True
        return Command("macro_run", {"name": args[0], "loop": loop})

    if sub == "stop":
        return Command("macro_stop")

    if sub == "list":
        return Command("macro_list")

    if sub == "status":
        return Command("macro_status")

    if sub == "show":
        name, err = _one_name(arg, "macro show")
        if err:
            return err
        return Command("macro_show", {"name": name})

    if sub == "delete":
        name, err = _one_name(arg, "macro delete")
        if err:
            return err
        return Command("macro_delete", {"name": name})

    if sub == "autorun":
        args = arg.split()
        if not args or args[0].lower() == "status":
            return Command("macro_autorun_status")
        if args[0].lower() == "off":
            return Command("macro_autorun_off")

        name = args[0]
        if not valid_macro_name(name):
            return "macro autorun: invalid name '{}'".format(name)
        if len(args) < 2:
            return "macro autorun: need <name> <delay_ms> [loop]"
        try:
            delay = int(args[1])
        except ValueError:
            return "macro autorun: delay must be an integer (ms)"
        if delay < MIN_AUTORUN_DELAY_MS:
            return ("macro autorun: delay must be >= {} ms "
                    "(startup window to send 'macro stop')".format(
                        MIN_AUTORUN_DELAY_MS))
        loop = False
        if len(args) > 2:
            if args[2].lower() != "loop":
                return "macro autorun: unknown option '{}' (loop)".format(args[2])
            loop = True
        return Command("macro_autorun_set",
                       {"name": name, "delay": delay, "loop": loop})

    return ("macro: unknown subcommand '{}' "
            "(save/end/abort/run/stop/list/show/delete/status/autorun)".format(sub))


# Minimum autorun delay. Ctrl-C is disabled on the device
# (micropython.kbd_intr(-1) in main.py), so this startup window is the only
# chance to send "macro stop" before an autorun macro takes over the console.
MIN_AUTORUN_DELAY_MS = 3000

_NAME_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
_MAX_NAME_LEN = 24


def valid_macro_name(name):
    """Macro names become filenames, so keep them short and path-safe."""
    if not name or len(name) > _MAX_NAME_LEN:
        return False
    for ch in name:
        if ch not in _NAME_CHARS:
            return False
    return True


# Mouse button name -> bit mask
_BUTTONS = {
    "left": 0x01,
    "right": 0x02,
    "middle": 0x04,
}


def _parse_button(name):
    return _BUTTONS.get(name)
