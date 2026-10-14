import pytest

from klim.control import Klim
from klim.device import MODES
from klim.fake import FakeKeyboard
from klim.tui.app import KlimApp
from klim.tui.widgets import Slider, Swatch


async def settle(app, pilot):
    """Wait until queued keyboard calls and their UI callbacks are done."""
    for _ in range(200):
        await pilot.pause(0.02)
        if not app.busy:
            return
    raise AssertionError("device queue never settled")


@pytest.fixture
def kb():
    return FakeKeyboard()


@pytest.mark.asyncio
async def test_initial_state_shown(kb):
    kb.state.brightness = 25
    app = KlimApp(Klim(kb), "test")
    async with app.run_test() as pilot:
        await settle(app, pilot)
        assert app.query_one("#brightness", Slider).value == 25
        assert app.query_one("#speed", Slider).value == 5  # raw 6 -> 5/10
        assert app.query_one("#swatch-1", Swatch).selected
        assert kb.writes == 0, "showing the state must not write it back"


@pytest.mark.asyncio
async def test_select_mode(kb):
    app = KlimApp(Klim(kb), "test")
    async with app.run_test() as pilot:
        await settle(app, pilot)
        # +1 for the list's top border
        await pilot.click("#mode-list", offset=(2, 1 + list(MODES).index("breathing")))
        await settle(app, pilot)
        assert kb.state.mode == MODES["breathing"]


@pytest.mark.asyncio
async def test_multicolor_mode_disables_swatches(kb):
    app = KlimApp(Klim(kb), "test")
    async with app.run_test() as pilot:
        await settle(app, pilot)
        app.apply_lighting(mode=MODES["wave"])
        await settle(app, pilot)
        assert kb.state.color == 8
        assert app.query_one("#swatch-1", Swatch).disabled
        assert app.query_one("#swatch-8", Swatch).selected


@pytest.mark.asyncio
async def test_slider_is_debounced(kb):
    app = KlimApp(Klim(kb), "test")
    async with app.run_test() as pilot:
        await settle(app, pilot)
        app.query_one("#brightness", Slider).focus()
        for _ in range(10):
            await pilot.press("left")
        await settle(app, pilot)
        assert kb.state.brightness == 26
        assert kb.writes == 1


@pytest.mark.asyncio
async def test_swatch_and_recolor(kb):
    app = KlimApp(Klim(kb), "test")
    async with app.run_test() as pilot:
        await settle(app, pilot)
        await pilot.click("#swatch-4")
        await settle(app, pilot)
        assert kb.state.color == 4
        inp = app.query_one("#palette-hex")
        assert inp.value == "#0000ff"
        inp.value = "#ff8800"
        await pilot.click("#palette-set")
        await settle(app, pilot)
        assert kb.palette[3] == bytes.fromhex("ff8800")
        await pilot.click("#palette-reset")
        await settle(app, pilot)
        assert kb.palette[3] == bytes.fromhex("0000ff")


@pytest.mark.asyncio
async def test_direction(kb):
    app = KlimApp(Klim(kb), "test")
    async with app.run_test() as pilot:
        await settle(app, pilot)
        await pilot.click("#dir-up")
        await settle(app, pilot)
        assert kb.state.direction == 3


async def open_tab(pilot, tab_id):
    await pilot.click(f"#--content-tab-{tab_id}")
    await pilot.pause()


@pytest.mark.asyncio
async def test_keys_usb_shown(kb):
    kb.game_mode = True
    kb.key_mask[0] &= ~0x02  # LWin disabled, as the vendor app's Win Lock does
    kb.report_rate, kb.response = 1, 4
    app = KlimApp(Klim(kb), "test")
    async with app.run_test(size=(110, 60)) as pilot:
        await settle(app, pilot)
        await open_tab(pilot, "keys-usb")
        assert app.query_one("#game-mode").value
        assert app.query_one("#win-lock").value
        assert app.query_one("#rate-250").value
        assert app.query_one("#response").value == 4  # 8 ms
        assert "lwin" in str(app.query_one("#disabled").render())
        assert kb.writes == 0


@pytest.mark.asyncio
async def test_keys_usb_changes(kb):
    kb.key_mask[6] &= ~0x01  # capslock disabled
    app = KlimApp(Klim(kb), "test")
    async with app.run_test(size=(110, 60)) as pilot:
        await settle(app, pilot)
        await open_tab(pilot, "keys-usb")
        await pilot.click("#game-mode")
        await pilot.click("#win-lock")
        await pilot.click("#rate-500")
        await settle(app, pilot)
        assert kb.game_mode and kb.report_rate == 2
        assert not kb.key_mask[0] & 0x02
        app.query_one("#response").focus()
        writes = kb.writes
        for _ in range(3):
            await pilot.press("right")
        await settle(app, pilot)
        assert kb.get_response_time() == 14  # 8 ms + 3 steps of 2 ms
        assert kb.writes == writes + 1, "debounced into one write"
        await pilot.click("#enable-all")
        await settle(app, pilot)
        assert kb.key_mask == bytearray([0xFF, 0xFF, 0x1F] * 6)
        assert not app.query_one("#win-lock").value


def rect_of(app, k):
    from klim.tui.keymap import KeyboardMap
    return next(r for r in app.query_one(KeyboardMap).rects if r.k == k and not r.continuation)


async def click_key(pilot, app, k):
    r = rect_of(app, k)
    # +1/+1: the map's border; padding adds 1 column
    await pilot.click("#map", offset=(r.x0 + 2, r.y + 1))


@pytest.mark.asyncio
async def test_perkey_paint_and_revert(kb):
    klim = Klim(kb)
    esc, w = klim.key_indices(["esc"])[0], klim.key_indices(["w"])[0]
    kb.rgb[0] = klim.filled_slot(bytes.fromhex("102030"))
    kb.state.mode = 0x33
    app = KlimApp(klim, "test")
    async with app.run_test(size=(110, 45)) as pilot:
        await settle(app, pilot)
        await open_tab(pilot, "per-key")
        await settle(app, pilot)
        await click_key(pilot, app, esc)
        await click_key(pilot, app, w)
        assert app.query_one("#map").selection == {esc, w}
        await pilot.click("#paint-1")  # palette entry 1 = red
        await settle(app, pilot)
        assert klim.key_color(kb.rgb[0], esc) == bytes.fromhex("ff0000")
        assert klim.key_color(kb.rgb[0], w) == bytes.fromhex("ff0000")
        other = klim.key_indices(["e"])[0]
        assert klim.key_color(kb.rgb[0], other) == bytes.fromhex("102030")
        app.query_one("#paint-hex").value = "#00ff80"
        app.query_one("#paint-hex").focus()
        await pilot.press("enter")
        await settle(app, pilot)
        assert klim.key_color(kb.rgb[0], esc) == bytes.fromhex("00ff80")
        await pilot.click("#revert")
        await settle(app, pilot)
        assert klim.key_color(kb.rgb[0], esc) == bytes.fromhex("102030")


@pytest.mark.asyncio
async def test_perkey_drag_select_and_slot_switch(kb):
    klim = Klim(kb)
    kb.state.mode = 0x33
    kb.rgb[2] = klim.filled_slot(bytes.fromhex("abcdef"))
    app = KlimApp(klim, "test")
    async with app.run_test(size=(110, 45)) as pilot:
        await settle(app, pilot)
        await open_tab(pilot, "per-key")
        await settle(app, pilot)
        a, d = rect_of(app, klim.key_indices(["a"])[0]), rect_of(app, klim.key_indices(["d"])[0])
        await pilot.mouse_down("#map", offset=(a.x0 + 2, a.y + 1))
        await pilot.hover("#map", offset=(d.x0 + 2, d.y + 1))
        await pilot.mouse_up("#map", offset=(d.x0 + 2, d.y + 1))
        assert app.query_one("#map").selection >= set(klim.key_indices(["a", "d"]))
        await pilot.click("#slot-2")
        await settle(app, pilot)
        assert kb.state.mode == 0x35
        assert not app.query_one("#map").selection
        esc = klim.key_indices(["esc"])[0]
        assert app.query_one("#map").key_colors[esc] == bytes.fromhex("abcdef")


@pytest.mark.asyncio
async def test_disable_keys_via_map(kb):
    from klim.control import ALL_KEYS_ENABLED
    from klim.device import key_enabled
    klim = Klim(kb)
    caps, lwin = klim.key_indices(["capslock"])[0], klim.key_indices(["lwin"])[0]
    app = KlimApp(klim, "test")
    async with app.run_test(size=(110, 60)) as pilot:
        await settle(app, pilot)
        await open_tab(pilot, "keys-usb")
        km = app.query_one("#disable-map")
        km.focus()
        km.cursor = caps
        await pilot.press("space")
        km.cursor = lwin
        await pilot.press("space")
        await settle(app, pilot)
        assert not key_enabled(kb.key_mask, caps) and not key_enabled(kb.key_mask, lwin)
        assert sum(not key_enabled(kb.key_mask, k) for k in range(126)) == 2
        assert app.query_one("#win-lock").value, "disabling LWin shows as Win Lock"
        assert "capslock" in str(app.query_one("#disabled").render())
        await pilot.click("#enable-all")
        await settle(app, pilot)
        assert kb.key_mask == bytearray(ALL_KEYS_ENABLED)
        assert not km.selection


@pytest.mark.asyncio
async def test_backup_and_restore(kb, tmp_path):
    from klim.tui.backup import find_backups
    klim = Klim(kb)
    app = KlimApp(klim, "test")
    async with app.run_test(size=(110, 50)) as pilot:
        await settle(app, pilot)
        await open_tab(pilot, "backup")
        app.query_one("#backup-dir").value = str(tmp_path)
        await pilot.click("#rescan")
        assert app.query_one("#restore").disabled
        await pilot.click("#backup-now")
        await settle(app, pilot)
        assert len(find_backups(tmp_path)) == 1
        assert not app.query_one("#restore").disabled

        kb.state.brightness, kb.palette[0], kb.game_mode = 3, b"\1\2\3", True
        kb.rgb[0] = bytearray(b"\x00\x11\x22\x33" * 128)

        await pilot.click("#restore")
        await pilot.pause()
        await pilot.click("#no")  # cancel: nothing changes
        await settle(app, pilot)
        assert kb.state.brightness == 3

        await pilot.click("#restore")
        await pilot.pause()
        await pilot.click("#yes")
        await settle(app, pilot)
        assert kb.state.brightness == 36 and kb.palette[0] == b"\xff\0\0" and not kb.game_mode
        assert kb.rgb[0][:8] == bytes(8)
        assert app.query_one("#brightness").value == 36, "UI reloaded after restore"


@pytest.mark.asyncio
async def test_restore_dialog_defaults_to_cancel(kb, tmp_path):
    klim = Klim(kb)
    klim.backup(tmp_path / "b1")
    kb.state.brightness = 7
    app = KlimApp(klim, "test")
    async with app.run_test(size=(110, 50)) as pilot:
        await settle(app, pilot)
        await open_tab(pilot, "backup")
        app.query_one("#backup-dir").value = str(tmp_path)
        await pilot.click("#rescan")
        await pilot.click("#restore")
        await pilot.pause()
        await pilot.press("enter")
        await settle(app, pilot)
        assert kb.state.brightness == 7, "Enter in the dialog cancels"
