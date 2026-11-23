#!/usr/bin/env python3
"""Add hi-score saving (cartridge RAM) to "Galaga & Galaxian (E) [S][!].gb" and make it run on
cartridges with a non-MBC1 bank register layout (MBC5-style clones).

Usage:  python patch_galaga.py "roms\\Galaga & Galaxian (E) [S][!].gb"
Output: same folder, "<name> (hi-score save).gb". The original is not modified.
Only the .gb file is accepted (CRC32 D06B3F8A). The .sgb copy is the same data: rename it.

Diagnostics (to find out which part of the patch causes a problem):
  --header-only   only the cartridge header is changed (RAM declared) and the mapper fix is applied
  --load-only     + boot hook: a saved hi-score is restored, nothing is saved
  --save-only     + update hooks: the hi-scores are saved, nothing is restored

What it changes (bank switching itself is not touched, no interrupt is hooked)
  header 0x147   01 -> 03   MBC1 -> MBC1+RAM+BATTERY
  header 0x149   00 -> 02   8 KB cartridge RAM
  60 places      "ld ($3FFF),a" -> "ld ($2000),a": the game selects ROM banks by writing to
                 $3FFF. A real MBC1 treats $2000-$3FFF as one register; MBC5-style clones do not
                 ($3000-$3FFF is the 9th bank bit there), so the game never switched banks on them.
                 Same instruction length, same effect on a real MBC1.
  0x0186         "ld a,1 ; ld ($D719),a" (5 bytes) -> "call Load ; nop ; nop"
                 (Load ends with the same two instructions)
  bank 3 $49F5   "ld (de),a ; dec de ; ret" (Galaxian: end of the routine that copies a new
                 hi-score) -> "jp StubGalaxian"
  bank 6 $4FCE   "ld a,(hl) ; ld (de),a ; ret" (Galaga: same, for its hi-score)
                 -> "jp StubGalaga"
                 (each stub repeats the replaced instructions, saves, and returns with every
                 register and flag as the game expects)
  0x3D3A-        SaveAll, the two stubs and Load: in the unused 0xFF padding at the end of bank 0
                 (bank 0 is always mapped, so the stubs work whichever bank is selected)

Game RAM
  Galaxian hi-score  $D70D-$D711   Galaga hi-score  $D712-$D716   (10 bytes together)
  One decimal digit per byte (low nibble), lowest digit first; the units digit (always 0) is
  not stored. The defaults 5000 and 30000 are written at boot ($0174-$0183, routine $1678)
  right after the RAM clear, before Load runs. The routines at bank 3 $49CB and bank 6 $4FA7
  compare score and hi-score digit by digit from the top and copy only if the score is strictly
  higher; that copy is the only write to the hi-scores after boot.

Save RAM at $A000: the 10 bytes, then a check byte = $A5 + their sum (mod 256).
Load accepts a record only if every byte is 0-9 and the check byte matches.
Reset: Down + Select held at power-on writes the default hi-scores (both games) to the save.
The game's four-button soft reset does not include Down, so it never triggers it.
"""
import sys
import zlib
from pathlib import Path

BASE_CRC32 = 0xD06B3F8A
HI, HI_LEN, SRAM = 0xD70D, 10, 0xA000
FREE = (0x3D3A, 0x4000)

MAPPER_OLD, MAPPER_NEW, MAPPER_SITES = bytes([0xEA, 0xFF, 0x3F]), bytes([0xEA, 0x00, 0x20]), 60

BOOT_HOOK = 0x0186
BOOT_ORIG = bytes.fromhex("3E01EA19D7")                      # ld a,1 ; ld ($D719),a
BOOT_CONTEXT = (0x016B, bytes.fromhex(                       # 016B-018F, from the disassembly
    "2100C0" "01F01F" "CD7703" "2111D7" "118916" "CD7816" "2116D7" "118F16" "CD7816"
    "3E01" "EA19D7" "AF" "EA09D7"))
DEFAULTS = (0x1678, bytes.fromhex("0E05" "1A" "13" "E60F" "32" "0D" "20F8" "C9"))       # 1678-1682
DEFAULT_DATA = (0x1689, bytes.fromhex("2020353030" "3020" "33303030"))               # 1689-1693

GALAXIAN_AT = 0xC9CB                                         # bank 3 $49CB
GALAXIAN_HOOK = 0xC9F5                                       # bank 3 $49F5
GALAXIAN_ROUTINE = bytes.fromhex(
    "2112D7" "115DC5" "0E06" "2B" "1B" "0D" "79" "A7" "C8" "1A" "47" "7E" "B8" "28F4" "3801" "D0"
    "1111D7" "215CC5" + "3A121B" * 5 + "C9")
GALAXIAN_ORIG = bytes.fromhex("121BC9")                      # ld (de),a ; dec de ; ret

GALAGA_AT = 0x18FA7                                          # bank 6 $4FA7
GALAGA_HOOK = 0x18FCE                                        # bank 6 $4FCE
GALAGA_ROUTINE = bytes.fromhex(
    "2117D7" "117FCC" "0E06" "2B" "1B" "0D" "C8" "1A" "47" "7E" "B8" "28F6" "3801" "C9"
    "1116D7" "217ECC" + "3A121B" * 4 + "7E12C9")
GALAGA_ORIG = bytes.fromhex("7E12C9")                        # ld a,(hl) ; ld (de),a ; ret


def h(s):
    return bytes.fromhex(s.replace(" ", ""))


def assemble(org, items):
    """items: bytes, label (str), ('jr', opcode, label), ('call'|'jp', label)."""
    labels, size = {}, 0
    for it in items:
        if isinstance(it, str):
            labels[it] = org + size
        elif isinstance(it, bytes):
            size += len(it)
        else:
            size += 2 if it[0] == "jr" else 3
    out = bytearray()
    for it in items:
        if isinstance(it, str):
            continue
        if isinstance(it, bytes):
            out += it
        elif it[0] == "jr":
            off = labels[it[2]] - (org + len(out) + 2)
            assert -128 <= off <= 127, f"jr to {it[2]} out of range"
            out += bytes([it[1], off & 255])
        else:
            t = labels[it[1]]
            out += bytes([0xCD if it[0] == "call" else 0xC3, t & 255, t >> 8])
    return bytes(out), labels


def build(org):
    items = [
        # ---- SaveAll: write the 10 hi-score bytes + check byte to $A000. Clobbers A,B,C,D,E,H,L.
        "SaveAll", h("3E0A EA0000 21 0D D7 11 00 A0 06 0A 0E A5"),
        "s_loop", h("2A 12 13 81 4F 05"), ("jr", 0x20, "s_loop"),
        h("79 12 AF EA0000 C9"),
        # ---- stubs: repeat the replaced instructions, save, return with everything preserved
        "StubGalaxian", h("12 1B"), ("jr", 0x18, "SaveRet"),                 # ld (de),a ; dec de
        "StubGalaga", h("7E 12"), ("jr", 0x18, "SaveRet"),                   # ld a,(hl) ; ld (de),a
        "SaveRet", h("F5 C5 D5 E5"), ("call", "SaveAll"), h("E1 D1 C1 F1 C9"),
        # ---- Load: restore the hi-scores at boot; Down+Select held writes the defaults instead
        "Load", h("C5 D5 E5"),
        h("3E20 E000 F000 F000 E608"), ("jr", 0x20, "l_nocombo"),            # Down held? (active low)
        h("3E10 E000 F000 F000 F000 F000 E604"), ("jr", 0x20, "l_nocombo"),  # Select held?
        ("call", "SaveAll"), ("jr", 0x18, "l_fin"),
        "l_nocombo", h("3E0A EA0000 21 00 A0 06 0A 0E A5"),
        "l_sum", h("7E FE0A"), ("jr", 0x30, "l_bad"), h("81 4F 23 05"), ("jr", 0x20, "l_sum"),
        h("7E B9"), ("jr", 0x20, "l_bad"),
        h("21 00 A0 11 0D D7 06 0A"),
        "l_cp", h("2A 12 13 05"), ("jr", 0x20, "l_cp"),
        "l_bad", h("AF EA0000"),
        "l_fin", h("3E30 E000 E1 D1 C1 3E01 EA19D7 C9"),
    ]
    return assemble(org, items)


def fix_checksums(rom):
    c = 0
    for b in rom[0x134:0x14D]:
        c = (c - b - 1) & 0xFF
    rom[0x14D] = c
    g = (sum(rom) - rom[0x14E] - rom[0x14F]) & 0xFFFF
    rom[0x14E], rom[0x14F] = g >> 8, g & 0xFF


def find_all(rom, pat):
    out, i = [], rom.find(pat)
    while i != -1:
        out.append(i)
        i = rom.find(pat, i + 1)
    return out


def expect(rom, addr, want, what):
    got = bytes(rom[addr:addr + len(want)])
    if got != want:
        sys.exit(f"Refusing to patch: {what} at 0x{addr:05X} is {got.hex(' ')}, expected {want.hex(' ')}.")


def patch(rom, mode=None, header_only=False):
    """rom: bytearray of the original (already checked). Returns the patched bytearray."""
    sites = find_all(rom, MAPPER_OLD)
    if len(sites) != MAPPER_SITES:
        sys.exit(f"Refusing to patch: found {len(sites)} writes to $3FFF, expected {MAPPER_SITES}.")
    expect(rom, BOOT_CONTEXT[0], BOOT_CONTEXT[1], "boot code")
    expect(rom, DEFAULTS[0], DEFAULTS[1], "default hi-score routine")
    expect(rom, DEFAULT_DATA[0], DEFAULT_DATA[1], "default hi-score data")
    expect(rom, GALAXIAN_AT, GALAXIAN_ROUTINE, "Galaxian hi-score routine")
    expect(rom, GALAGA_AT, GALAGA_ROUTINE, "Galaga hi-score routine")
    expect(rom, FREE[0], b"\xFF" * (FREE[1] - FREE[0]), "padding area")

    for i in sites:
        rom[i:i + 3] = MAPPER_NEW
    rom[0x147], rom[0x149] = 0x03, 0x02
    if not header_only:
        code, labels = build(FREE[0])
        if FREE[0] + len(code) > FREE[1]:
            sys.exit("The new code does not fit.")
        rom[FREE[0]:FREE[0] + len(code)] = code
        print(f"New code: {len(code)} bytes at 0x{FREE[0]:04X} "
              f"(SaveAll {labels['SaveAll']:04X}, StubGalaxian {labels['StubGalaxian']:04X}, "
              f"StubGalaga {labels['StubGalaga']:04X}, Load {labels['Load']:04X}; "
              f"{FREE[1] - FREE[0] - len(code)} bytes left)")
        if mode in (None, "save"):
            rom[GALAXIAN_HOOK:GALAXIAN_HOOK + 3] = bytes([0xC3]) + labels["StubGalaxian"].to_bytes(2, "little")
            rom[GALAGA_HOOK:GALAGA_HOOK + 3] = bytes([0xC3]) + labels["StubGalaga"].to_bytes(2, "little")
        if mode in (None, "load"):
            rom[BOOT_HOOK:BOOT_HOOK + 5] = bytes([0xCD]) + labels["Load"].to_bytes(2, "little") + b"\x00\x00"
    fix_checksums(rom)
    return rom


def main(path, header_only=False, mode=None):
    src = Path(path)
    data = src.read_bytes()
    if zlib.crc32(data) != BASE_CRC32:
        sys.exit(f"Refusing to patch: CRC32 is {zlib.crc32(data):08X}, expected {BASE_CRC32:08X} "
                 "(Galaga & Galaxian (E) [S][!]). Use the .gb file, and an unpatched copy.")
    rom = patch(bytearray(data), mode, header_only)
    suffix = "header only" if header_only else {None: "hi-score save", "load": "load only", "save": "save only"}[mode]
    dst = src.with_name(f"{src.stem} ({suffix}).gb")
    dst.write_bytes(rom)
    print(f"Written: {dst}" + ("" if mode is None and not header_only else "  (diagnostic build, not the full patch)"))
    return dst


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)
    flags = {"--load-only": "load", "--save-only": "save"}
    main(args[0], header_only="--header-only" in sys.argv,
         mode=next((v for k, v in flags.items() if k in sys.argv), None))
