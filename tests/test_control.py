import pytest

from klim.control import ALL_KEYS_ENABLED, Klim
from klim.device import MODES, key_enabled
from klim.fake import FakeKeyboard


@pytest.fixture
def klim():
    return Klim(FakeKeyboard())


def test_set_lighting_validates(klim):
    for bad in ({"mode": 0x07}, {"speed": 0}, {"speed": 11}, {"brightness": 51},
                {"color": 0}, {"color": 9}, {"direction": 5}):
        with pytest.raises(ValueError):
            klim.set_lighting(**bad)
    assert klim.kb.writes == 0, "nothing invalid reaches the keyboard"


def test_speed_is_user_facing(klim):
    klim.set_lighting(speed=10)
    assert klim.kb.state.speed == 1  # fastest = shortest delay
    assert klim.info().speed == 10


def test_multicolor_only_modes(klim):
    klim.set_lighting(mode=MODES["wave"], color=2)
    assert klim.kb.state.color == 8


def test_disable_keys_and_win_lock(klim):
    klim.set_keys_enabled(["capslock"], False)
    klim.set_win_lock(True)
    info = klim.info()
    assert set(info.disabled_keys) == {"capslock", "lwin"} and info.win_lock
    klim.set_disabled(set())
    assert klim.kb.key_mask == bytearray(ALL_KEYS_ENABLED)
    with pytest.raises(KeyError):
        klim.set_keys_enabled(["nope"], False)


def test_paint_keys_maps_to_leds(klim):
    klim.paint_keys(1, [(["esc"], b"\xff\0\0")], base=b"\0\0\x10")
    buf = klim.kb.rgb[1]
    assert buf[4 * 5 + 1:4 * 5 + 4] == b"\xff\0\0"  # Esc is LED 5 (verified on hardware)
    assert klim.kb.state.mode == 0x34, "switched to DIY2"


def test_backup_restore_round_trip(klim, tmp_path):
    kb = klim.kb
    kb.palette[2] = b"\1\2\3"
    klim.set_lighting(mode=MODES["breathing"], brightness=20)
    klim.set_keys_enabled(["f1"], False)
    kb.rgb[4][:4] = b"\0\x10\x20\x30"
    klim.backup(tmp_path)

    klim.reset_palette()
    klim.set_lighting(mode=MODES["constant"], brightness=50)
    klim.set_disabled(set())
    kb.rgb[4] = bytearray(512)
    restored = klim.restore(tmp_path)

    assert "palette" in restored and "key mask" in restored
    assert kb.palette[2] == b"\1\2\3"
    assert kb.state.mode == MODES["breathing"] and kb.state.brightness == 20
    assert not key_enabled(kb.key_mask, klim.key_indices(["f1"])[0])
    assert kb.rgb[4][:4] == b"\0\x10\x20\x30"


def test_restore_missing_dir(klim, tmp_path):
    with pytest.raises(ValueError):
        klim.restore(tmp_path / "nope")


def test_keys_resolve_to_physical_positions(klim):
    from klim.device import COLS
    from klim.tui.keymap import ALL_KEYS
    # the factory keymap has Ctrl+digit entries at non-existent numpad positions
    for i in klim.key_indices(["numbers"]):
        assert i // COLS == 4, "digits live on the number row"
    named = ["letters", "numbers", "fkeys", "arrows", "nav", "mods", "esc", "space", "enter",
             "backspace", "tab", "capslock", "grave", "minus", "equal", "lbracket", "rbracket",
             "semicolon", "quote", "backslash", "comma", "period", "slash", "iso",
             "printscreen", "scrolllock", "pause"]
    assert set(klim.key_indices(named, strict=False)) <= set(ALL_KEYS), "every named key is on the map"


def test_fn_key_by_name(klim):
    from klim.tui.keymap import m
    assert klim.key_indices(["fn"]) == [m(0, 10)]


def test_dracula_theme(klim):
    from klim.themes import THEMES, to_led
    from klim.tui.keymap import ALL_KEYS
    theme = THEMES["dracula"]
    klim.apply_theme(theme, slot=1, palette=True)
    buf = klim.kb.rgb[1]
    colors = {i: klim.key_color(buf, i) for i in ALL_KEYS}
    assert colors[klim.key_indices(["esc"])[0]] == to_led("ff5555")
    assert colors[klim.key_indices(["fn"])[0]] == to_led("ff79c6")
    assert colors[klim.key_indices(["1"])[0]] == to_led("50fa7b"), "digits on the number row"
    base = to_led(theme.base)
    on_base = {klim.key_name(i) for i, c in colors.items() if c == base}
    assert on_base == {"space", "printscreen", "scrolllock", "pause"}, "every key is themed"
    assert klim.kb.palette[3] == to_led("bd93f9")
    assert klim.kb.state.mode == 0x34


def test_theme_gamma_1_sends_screen_colors(klim):
    from klim.themes import THEMES
    klim.apply_theme(THEMES["dracula"], palette=True, gamma=1)
    assert klim.kb.palette[0] == bytes.fromhex("ff5555")
    assert klim.kb.writes == 7, "palette only, no slot written"
