# klim

Lighting control for the KLIM Dash TKL keyboard, replacing the vendor app.

```sh
uv run klim info                                     # current mode/state
uv run klim mode 1 --color 1                         # static red
uv run klim brightness 70%                           # 0..50 raw, or a percentage
uv run klim keys --base 000020 esc=ff0000 wasd=00ff00  # per-key colors
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
| `08 02 mode speed bright color dir` | `88` | lighting state (reply bytes 3..7); brightness 0 (off)..50 |
| `12 00 slot 08` + 512 B | `92 00 slot 08` | per-key RGB, 128 x `[0,R,G,B]` in LED order |
| `0D 00 00 08` + 512 B | `8D` | keymap, 128 x `[type,mod,usage,0]` — **not used here** |

- Modes: `01`(static) `02 03 04 05 06 08 0A 0B 0C 0D`, `33`..`37` = custom RGB slot 0..4.
- Color `01`..`07` = palette entry 0..6 (read with `94 00 n`: red, green, yellow, blue,
  cyan, magenta, white by default); `08` = multicolor, which the firmware forces
  to `01` in static mode.
- An uploaded RGB slot only shows after re-sending `08 02 …`.
- Key layout is a 6 x 21 grid. Keymap index `k = row*21 + col` (bottom row
  first); LED index `col*6 + row`.
- `91 00 n` (n=0..31) returns 3 x 64 bytes, probably macros; `11 00 n 03`
  likely writes them. `14` likely writes palette entries.
- Unidentified: `80 81 84 89 8E` / `01 04 09 13`. `81` changed `01` -> `03`
  after applying settings in the vendor app.
- Print Screen stays white in every mode (firmware indicator?).
