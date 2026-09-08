# Macro storage and playback for Pico HID Proxy
# Macros are plain text files under /macros/, one command per line.
# Blank lines and lines starting with '#' are ignored.

import os
import uasyncio as asyncio

from protocol import parse, valid_macro_name

_DIR = "/macros"
_EXT = ".txt"

# Command kinds that must never run from inside a macro.
# reboot would boot-loop when combined with autorun; nested macro control
# would recurse or fight with the running player.
_FORBIDDEN = ("reboot", "reboot_bootloader")

# Compiled step kinds
_SLEEP = 0
_CMD = 1


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
    for raw in body.split("\n"):
        lineno += 1
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split(None, 1)
        if parts[0].lower() == "sleep":
            if len(parts) < 2 or not parts[1].strip():
                return "line {}: sleep needs <ms>".format(lineno)
            try:
                ms = int(parts[1].strip())
            except ValueError:
                return "line {}: sleep ms must be an integer".format(lineno)
            if ms < 0:
                return "line {}: sleep ms must be >= 0".format(lineno)
            steps.append((_SLEEP, ms))
            continue

        cmd = parse(line)
        if isinstance(cmd, str):
            return "line {}: {}".format(lineno, cmd)
        if cmd.kind in _FORBIDDEN or cmd.kind.startswith("macro_"):
            return "line {}: '{}' is not allowed inside a macro".format(
                lineno, parts[0].lower()
            )
        steps.append((_CMD, cmd))

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
