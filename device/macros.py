# Macro storage and playback for Pico HID Proxy
# Macros are plain text files under /macros/, one command per line.
# Blank lines and lines starting with '#' are ignored.

import os
import uasyncio as asyncio

from protocol import parse, valid_macro_name

# NOTE: this must NOT be a valid module name. sys.path is ['', '.frozen', '/lib'],
# so a directory at the filesystem root shadows the frozen module of the same
# name -- "/macros" made `import macros` resolve to the directory and dropped
# the device to a REPL on the first boot after any macro was saved.
_DIR = "/macros.d"
_EXT = ".txt"

# Command kinds that must never run from inside a macro.
# reboot would boot-loop when combined with autorun; nested macro control
# would recurse or fight with the running player.
_FORBIDDEN = ("reboot", "reboot_bootloader", "usb_mode_set")

# Compiled step kinds
_SLEEP = 0
_CMD = 1

# repeat blocks expand inline at compile time, so a runaway count would eat RAM
# rather than being caught at runtime. Cap the expanded program instead.
_MAX_STEPS = 4000
_MAX_REPEAT = 1000


def _path(name):
    return _DIR + "/" + name + _EXT


def _ensure_dir():
    try:
        os.mkdir(_DIR)
    except OSError:
        pass  # already exists


def list_names():
    """Return sorted macro names, or [] if none/no directory."""
    try:
        names = [f[: -len(_EXT)] for f in os.listdir(_DIR) if f.endswith(_EXT)]
    except OSError:
        return []
    names.sort()
    return names


def exists(name):
    try:
        os.stat(_path(name))
        return True
    except OSError:
        return False


def load(name):
    with open(_path(name), "r") as f:
        return f.read()


def save(name, body):
    _ensure_dir()
    with open(_path(name), "w") as f:
        f.write(body)


def delete(name):
    os.remove(_path(name))


def compile_body(body):
    """Compile macro text into a list of steps.

    Returns a list of (kind, value) tuples, or an error string.
    Parsing up front means a typo surfaces at save/start time rather than
    halfway through a run with keys already held down.
    """
    steps = []
    lineno = 0
    # repeat block state: None when not inside one
    rep_count = None
    rep_steps = None
    rep_line = 0

    for raw in body.split("\n"):
        lineno += 1
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split(None, 1)
        verb = parts[0].lower()

        if verb == "repeat":
            if rep_count is not None:
                return "line {}: repeat cannot be nested".format(lineno)
            if len(parts) < 2 or not parts[1].strip():
                return "line {}: repeat needs <count>".format(lineno)
            try:
                n = int(parts[1].strip())
            except ValueError:
                return "line {}: repeat count must be an integer".format(lineno)
            if n < 1 or n > _MAX_REPEAT:
                return "line {}: repeat count must be 1-{}".format(lineno, _MAX_REPEAT)
            rep_count = n
            rep_steps = []
            rep_line = lineno
            continue

        if verb == "end":
            if rep_count is None:
                return "line {}: 'end' without a matching 'repeat'".format(lineno)
            if not rep_steps:
                return "line {}: repeat block is empty".format(lineno)
            total = len(steps) + len(rep_steps) * rep_count
            if total > _MAX_STEPS:
                return ("line {}: repeat expands to {} steps, over the {} limit"
                        .format(lineno, total, _MAX_STEPS))
            for _ in range(rep_count):
                steps.extend(rep_steps)
            rep_count = None
            rep_steps = None
            continue

        # Inside a repeat block, steps accumulate instead of emitting directly.
        out = rep_steps if rep_count is not None else steps

        if verb == "sleep":
            if len(parts) < 2 or not parts[1].strip():
                return "line {}: sleep needs <ms>".format(lineno)
            try:
                ms = int(parts[1].strip())
            except ValueError:
                return "line {}: sleep ms must be an integer".format(lineno)
            if ms < 0:
                return "line {}: sleep ms must be >= 0".format(lineno)
            out.append((_SLEEP, ms))
            continue

        cmd = parse(line)
        if isinstance(cmd, str):
            return "line {}: {}".format(lineno, cmd)
        if cmd.kind in _FORBIDDEN or cmd.kind.startswith("macro_"):
            return "line {}: '{}' is not allowed inside a macro".format(
                lineno, parts[0].lower()
            )
        out.append((_CMD, cmd))
        if len(steps) + (len(rep_steps) if rep_steps is not None else 0) > _MAX_STEPS:
            return "line {}: macro is too long (over {} steps)".format(lineno, _MAX_STEPS)

    if rep_count is not None:
        return "line {}: 'repeat' without a matching 'end'".format(rep_line)

    return steps


class _Player:
    """Runs one macro at a time as a background asyncio task."""

    def __init__(self):
        self.task = None
        self.name = None
        self.loop = False
        self.iteration = 0
        self._dispatch = None
        self._log = None
        self._release = None

    def bind(self, dispatch_fn, log_fn, release_fn):
        self._dispatch = dispatch_fn
        self._log = log_fn
        self._release = release_fn

    def is_running(self):
        return self.task is not None

    def start(self, name, loop=False):
        if self.is_running():
            return "ERR macro '{}' already running (use macro stop)".format(self.name)
        if not valid_macro_name(name):
            return "ERR macro: invalid name '{}'".format(name)
        if not exists(name):
            return "ERR macro '{}' not found".format(name)
        try:
            body = load(name)
        except OSError as e:
            return "ERR macro read failed: {}".format(e)

        steps = compile_body(body)
        if isinstance(steps, str):
            return "ERR macro '{}' {}".format(name, steps)
        if not steps:
            return "ERR macro '{}' is empty".format(name)

        self.name = name
        self.loop = loop
        self.iteration = 0
        self.task = asyncio.create_task(self._run(steps))
        return "OK macro '{}' started{}".format(name, " (loop)" if loop else "")

    def stop(self):
        if not self.is_running():
            return "macro not running"
        task = self.task
        name = self.name
        self.task = None
        task.cancel()
        self._release_all()
        return "OK macro '{}' stopped".format(name)

    def status(self):
        if not self.is_running():
            return "macro: not running"
        return "macro: running '{}'{} (iteration {})".format(
            self.name, " loop" if self.loop else "", self.iteration
        )

    def _release_all(self):
        """Never leave keys or buttons held after a macro ends."""
        try:
            if self._release:
                self._release()
        except Exception:
            pass

    async def _run(self, steps):
        try:
            while True:
                self.iteration += 1
                for kind, value in steps:
                    if kind == _SLEEP:
                        await asyncio.sleep_ms(value)
                    else:
                        self._dispatch(value)
                        # Yield so the web server stays responsive and
                        # 'macro stop' can land mid-run.
                        await asyncio.sleep_ms(0)
                if not self.loop:
                    break
                await asyncio.sleep_ms(0)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if self._log:
                self._log("MACRO ERR {}".format(e))
        finally:
            self._release_all()
            self.task = None


player = _Player()
