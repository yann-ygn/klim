import subprocess
import types

import pytest

from klim.tui import kblayout


def test_parsers():
    assert kblayout.parse_setxkbmap("rules:      evdev\nmodel:      pc105\nlayout:     fr,us\n") == "fr"
    assert kblayout.parse_gsettings("[('xkb', 'fr+azerty'), ('xkb', 'us')]") == "fr"
    assert kblayout.parse_gsettings("@a(ss) []") is None
    assert kblayout.parse_localectl("   System Locale: LANG=fr_FR.UTF-8\n       X11 Layout: fr\n") == "fr"
    assert kblayout.parse_localectl("   X11 Layout: n/a") == "n/a"


@pytest.mark.parametrize("xkb,legends", [("fr", "fr"), ("fr(oss)", "fr"), ("be", "fr"),
                                         ("us", "us"), ("de", "us"), ("n/a", "us")])
def test_legends_for(xkb, legends):
    assert kblayout.legends_for(xkb) == legends


def fake_run(outputs):
    """subprocess.run stand-in answering by program name; missing programs raise."""
    def run(cmd, **kw):
        if cmd[0] not in outputs:
            raise FileNotFoundError(cmd[0])
        return types.SimpleNamespace(stdout=outputs[cmd[0]])
    return run


def test_linux_x11(monkeypatch):
    monkeypatch.setattr(kblayout.sys, "platform", "linux")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("XKB_DEFAULT_LAYOUT", raising=False)
    monkeypatch.setattr(subprocess, "run", fake_run({"setxkbmap": "layout:     fr\n"}))
    assert kblayout.detect_layout() == "fr"


def test_linux_wayland_prefers_desktop_setting(monkeypatch):
    monkeypatch.setattr(kblayout.sys, "platform", "linux")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.delenv("XKB_DEFAULT_LAYOUT", raising=False)
    monkeypatch.setattr(subprocess, "run", fake_run({
        "setxkbmap": "layout:     us\n",  # XWayland default, not the real layout
        "gsettings": "[('xkb', 'fr')]",
    }))
    assert kblayout.detect_layout() == "fr"


def test_linux_env_and_fallbacks(monkeypatch):
    monkeypatch.setattr(kblayout.sys, "platform", "linux")
    monkeypatch.setenv("XKB_DEFAULT_LAYOUT", "fr,us")
    assert kblayout.detect_layout() == "fr"
    monkeypatch.delenv("XKB_DEFAULT_LAYOUT")
    monkeypatch.setattr(subprocess, "run", fake_run({}))  # no tools installed
    assert kblayout.detect_layout() == "us"


def test_open_failure_explains_udev(monkeypatch):
    from klim import device

    class Dev:
        def open_path(self, path):
            raise OSError("open failed")

    monkeypatch.setattr(device.sys, "platform", "linux")
    monkeypatch.setattr(device.hid, "enumerate", lambda vid, pid: [
        {"interface_number": 3, "path": b"/dev/hidraw3"}])
    monkeypatch.setattr(device.hid, "device", Dev)
    with pytest.raises(RuntimeError, match="hidraw3.*udev rule"):
        device.Keyboard()
