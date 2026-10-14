# klim

Lighting control for the KLIM Dash TKL keyboard, replacing the vendor app.

```sh
uv run klim info                                     # current mode/state
uv run klim mode constant --color red                # or breathing, wave, diy1...
uv run klim palette red ff8000                       # recolor palette entry 1 (or --reset)
uv run klim brightness 70%                           # 0..50 raw, or a percentage
uv run klim speed 8                                  # 1 (slowest) .. 10 (fastest)
uv run klim mode wave --direction up --speed 7
uv run klim keys --base 000020 esc=ff0000 wasd=00ff00  # per-key colors
uv run klim winlock on                               # or: gamemode on, disable capslock, enable --all
uv run klim rate 1000                                # USB polling: 125, 250, 500, 1000 Hz
uv run klim response 8                               # key debounce: 2..20 ms, even
uv run klim backup backup/full                       # state + keymap + all RGB slots
uv run klim restore backup/full
```

Key names are positional US-QWERTY (`q` is the AZERTY `A` key). Groups:
`wasd`, `arrows`, `fkeys`, `numbers`, `letters`, `nav`, `mods`; raw HID usages
like `0x29` also work.

## Protocol

Holtek MCU, USB `04D9:A231`, vendor interface 3 (usage page `0xFF01`).
Recovered from `KLIMDashTKL.exe` disassembly and verified on hardware.

Every command is a 9-byte feature report:

```
[0x00] CMD b2 b3 COUNT b5 b6 b7 CHK      CHK = 0xFF - sum(CMD..b7)
```

Writes have bit 7 clear; the read is `CMD | 0x80` (set feature, get feature,
then `COUNT` x 64-byte input reports). Bulk writes follow the feature report
with `COUNT` x 64-byte output reports, ~5 ms apart.

| Write | Read | Payload |
|---|---|---|
| `08 02 mode speed bright color dir` | `88` | lighting state (reply bytes 3..7); speed is a delay, 10 (slow)..1 (fast); brightness 0 (off)..50; direction 1 →, 2 ←, 3 ↑, 4 ↓ |
| `14 00 n R G B` | `94 00 n` | palette entry n (0..6), applies immediately |
| `12 00 slot 08` + 512 B | `92 00 slot 08` | per-key RGB, 128 x `[0,R,G,B]` in LED order |
| `01 n` | `81` | USB report rate, n = 0..3 → 125/250/500/1000 Hz (reply byte 2) |
| `04 n` | `84` | response time (debounce), n = ms / 2, 2..20 ms |
| `09 val` | `89` | game mode (reply byte 2); Print Screen lights white when on |
| `0E 00 00 12` + 64 B | `8E 00 00 12` + 64 B | key enable mask: 6 rows (bottom first) x LE 21-bit column mask, 0 = disabled. Win Lock clears LWin |
| `0D 00 00 08` + 512 B | `8D` | keymap, 128 x `[type,mod,usage,0]` — **not used here** |

- Modes: `01` Constant, `02` Breathing, `03` Wave, `04` Reactive, `05` Chase,
  `06` Ripple, `08` Spectrum, `0A` Raindrop, `0B` Vortex, `0C` Spotlight,
  `0D` Radar, `33`..`37` DIY1..5 (custom RGB slot 0..4). Wave, Spectrum and
  Raindrop are always multicolor.
- Color `01`..`07` = palette entry 0..6 (read with `94 00 n`: red, green, yellow, blue,
  cyan, magenta, white by default); `08` = multicolor, which the firmware forces
  to `01` in static mode.
- An uploaded RGB slot only shows after re-sending `08 02 …`.
- Key layout is a 6 x 21 grid. Keymap index `k = row*21 + col` (bottom row
  first); LED index `col*6 + row`.
- `91 00 n` (n=0..31) returns 3 x 64 bytes, probably macros; `11 00 n 03`
  likely writes them.
- The firmware stores out-of-range values without complaint (e.g. `01 08`); the tool
  validates everything it sends.
- Unidentified: `80` (reads `02 01`, maybe a firmware version).
- `13 FF` is sent before the app re-reads everything: most likely a factory reset.
  Never sent by this tool.
