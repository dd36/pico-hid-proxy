# Persistent JSON config on Pico flash filesystem
# Stores WiFi credentials and web API token at /config.json

import json

_PATH = "/config.json"


def load():
    try:
        with open(_PATH, "r") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(cfg):
    with open(_PATH, "w") as f:
        json.dump(cfg, f)


def get_wifi():
    cfg = load()
    return cfg.get("wifi_ssid"), cfg.get("wifi_pass")


def set_wifi(ssid, password):
    cfg = load()
    cfg["wifi_ssid"] = ssid
    cfg["wifi_pass"] = password
    save(cfg)


def get_web_password():
    return load().get("web_pass")


def clear_wifi():
    cfg = load()
    cfg.pop("wifi_ssid", None)
    cfg.pop("wifi_pass", None)
    save(cfg)


def set_web_password(password):
    cfg = load()
    cfg["web_pass"] = password
    save(cfg)


def get_api_enabled():
    return load().get("api_enabled", False)


def set_api_enabled(val):
    cfg = load()
    cfg["api_enabled"] = bool(val)
    save(cfg)


def get_webui_enabled():
    return load().get("webui_enabled", False)


def set_webui_enabled(val):
    cfg = load()
    cfg["webui_enabled"] = bool(val)
    save(cfg)


def get_autorun():
    """Return (macro_name, delay_ms, loop). name is None when disabled."""
    cfg = load()
    return (
        cfg.get("autorun_macro"),
        cfg.get("autorun_delay", 5000),
        cfg.get("autorun_loop", False),
    )


def set_autorun(name, delay_ms, loop):
    cfg = load()
    cfg["autorun_macro"] = name
    cfg["autorun_delay"] = int(delay_ms)
    cfg["autorun_loop"] = bool(loop)
    save(cfg)


def clear_autorun():
    cfg = load()
    cfg.pop("autorun_macro", None)
    cfg.pop("autorun_delay", None)
    cfg.pop("autorun_loop", None)
    save(cfg)
