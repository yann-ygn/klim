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
    async with app.run_test(size=(100, 40)) as pilot:
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
    async with app.run_test(size=(100, 40)) as pilot:
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
