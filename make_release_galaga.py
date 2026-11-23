#!/usr/bin/env python3
"""Build the release package for the Galaga & Galaxian hi-score-save hack.

Usage (patch_galaga.py must be in the same folder):
    python make_release_galaga.py "roms\\Galaga & Galaxian (E) [S][!].gb" --author "Your Name"
        [--version 1.0] [--repo https://github.com/<you>/<repo>]

Creates  release\\Galaga & Galaxian - Hi-score Save v<version>.zip  containing
  - a BPS patch (recommended: checks that you have the right base ROM)
  - an IPS patch (for tools that only know IPS)
  - README.txt (with the base ROM's size, CRC32, MD5 and SHA-1)
The zip contains only what is needed to patch the game: neither the ROM nor the
Python scripts are included (the scripts belong in the repository).
Also writes release\\README.md, the same information as a GitHub README.
Both patches are applied again to the original and compared with the real output
before the zip is written.
"""
import argparse
import datetime
import hashlib
import shutil
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import patch_galaga as pb  # noqa: E402

NAME = "Galaga & Galaxian - Hi-score Save"
FILE_NAME = NAME
# Edit this to name what you really tested (it appears in both READMEs):
TESTED_ON = ("Emulators: BGB and mGBA.\n"
             "Real hardware: EZ Flash Jr and generic single-game rewritable cartridges, played on Game Boy,\n"
             "Game Boy Color, Super Game Boy, Analogue Pocket and ModRetro Chromatic. Tested: saving, loading,\n"
             "hi-score reset and soft resets, in both games.")


# ---------------------------------------------------------------- IPS
def make_ips(src, dst, gap=6):
    assert len(src) == len(dst) <= 0x1000000
    runs, i, n = [], 0, len(dst)
    while i < n:
        if src[i] == dst[i]:
            i += 1
            continue
        j = i + 1
        last = i                      # last differing byte seen
        while j < n and j - last <= gap:
            if src[j] != dst[j]:
                last = j
            j += 1
        runs.append((i, last + 1))
        i = last + 1
    out = bytearray(b"PATCH")
    for a, b in runs:
        while a < b:
            size = min(b - a, 0xFFFF)
            assert a != 0x454F46, "offset collides with the IPS 'EOF' marker"
            out += a.to_bytes(3, "big") + size.to_bytes(2, "big") + dst[a:a + size]
            a += size
    return bytes(out + b"EOF")


def apply_ips(src, patch):
    assert patch[:5] == b"PATCH" and patch[-3:] == b"EOF"
    out, p = bytearray(src), 5
    while patch[p:p + 3] != b"EOF" or p + 3 != len(patch):
        off = int.from_bytes(patch[p:p + 3], "big")
        size = int.from_bytes(patch[p + 3:p + 5], "big")
        p += 5
        if size == 0:                                   # RLE record
            run = int.from_bytes(patch[p:p + 2], "big")
            out[off:off + run] = bytes([patch[p + 2]]) * run
            p += 3
        else:
            out[off:off + size] = patch[p:p + size]
            p += size
    return bytes(out)


# ---------------------------------------------------------------- BPS
def bps_num(n):
    out = bytearray()
    while True:
        x = n & 0x7F
        n >>= 7
        if n == 0:
            out.append(0x80 | x)
            return bytes(out)
        out.append(x)
        n -= 1


def make_bps(src, dst, metadata=b""):
    assert len(src) == len(dst)
    out = bytearray(b"BPS1")
    out += bps_num(len(src)) + bps_num(len(dst)) + bps_num(len(metadata)) + metadata
    i, n = 0, len(dst)
    while i < n:
        j = i
        same = src[i] == dst[i]
        while j < n and (src[j] == dst[j]) == same:
            j += 1
        length = j - i
        if same:                                        # SourceRead
            out += bps_num(((length - 1) << 2) | 0)
        else:                                           # TargetRead
            out += bps_num(((length - 1) << 2) | 1) + dst[i:j]
        i = j
    out += zlib.crc32(src).to_bytes(4, "little") + zlib.crc32(dst).to_bytes(4, "little")
    out += zlib.crc32(out).to_bytes(4, "little")
    return bytes(out)


def apply_bps(src, patch):
    assert patch[:4] == b"BPS1"
    assert zlib.crc32(patch[:-4]) == int.from_bytes(patch[-4:], "little"), "patch CRC"
    assert zlib.crc32(src) == int.from_bytes(patch[-12:-8], "little"), "wrong base ROM"

    def num(p):
        data, shift = 0, 1
        while True:
            x = patch[p]
            p += 1
            data += (x & 0x7F) * shift
            if x & 0x80:
                return data, p
            shift <<= 7
            data += shift

    p = 4
    ssize, p = num(p)
    tsize, p = num(p)
    msize, p = num(p)
    p += msize
    out = bytearray()
    while p < len(patch) - 12:
        data, p = num(p)
        cmd, length = data & 3, (data >> 2) + 1
        if cmd == 0:
            out += src[len(out):len(out) + length]
        elif cmd == 1:
            out += patch[p:p + length]
            p += length
        else:
            raise NotImplementedError("this encoder only emits SourceRead/TargetRead")
    assert len(out) == tsize
    assert zlib.crc32(out) == int.from_bytes(patch[-8:-4], "little"), "target CRC"
    return bytes(out)


# ---------------------------------------------------------------- README
README = """\
{name}
Version {version}  -  by {author}  -  {date}
==============================================================================

DESCRIPTION
  Adds saving of the hi-scores to Galaga & Galaxian (Game Boy, Europe, Super Game Boy
  enhanced). The game itself is unchanged: no new screens, no new menus. The hi-score of
  each game, Galaga and Galaxian, is simply still there the next time you play, instead of
  going back to its default (30000 and 5000) every time the console is switched on.
  It also fixes a compatibility problem: the original ROM selects its ROM banks in a way that
  only works on a genuine MBC1, so on many cheap rewritable cartridges (MBC5-style mappers)
  its graphics came out garbled. With this patch it also runs on those.

BASE ROM
  The patch applies to this exact file and no other:
      Name  : {rom_name}
      Size  : {size} bytes
      CRC32 : {crc32}
      MD5   : {md5}
      SHA-1 : {sha1}
  A copy named .sgb with the same CRC32 is the same data: rename it to .gb (some flash
  cartridges cannot read .sgb files). Check your copy before patching. A different dump (or one
  with a header) will not work. The BPS patch refuses to apply to a wrong ROM; the IPS patch
  cannot tell and would produce a broken game.

PATCHING
  Use the online patcher at https://www.romhacking.net/patch/ (it works in your
  browser, so there is nothing to install) or any other IPS/BPS patcher. Apply
  the BPS patch if you can (it verifies the base ROM); the IPS patch is identical
  in effect. Keep your original ROM; the patcher gives you a new file.

REQUIREMENTS
  Saving needs cartridge RAM that keeps its contents when the power is off:
    - Emulators: any emulator that supports MBC1 + RAM + battery. A .sav file is
      created next to the ROM (BGB, SameBoy, mGBA, etc.).
    - Real hardware: a flash cart or rewritable cartridge that supports MBC1 with
      8 KB of save RAM. Battery-backed RAM and non-volatile FRAM both qualify.
  On hardware without save RAM the game still plays normally, but, as in the
  original game, the hi-scores are lost when the console is switched off.

HOW IT WORKS FOR THE PLAYER
  - Nothing to do. A hi-score is stored automatically whenever you beat it.
  - The game's four-button soft reset keeps the hi-scores, as in the original game.
  - To reset both hi-scores to their defaults: switch the console on while holding
    DOWN + SELECT.
  - On a Super Game Boy the Game Boy version uses the same saved hi-scores as on any
    other Game Boy.

KNOWN LIMITATIONS
  - Only the hi-scores are saved; nothing else.
  - The save has a check byte and every digit is validated, so a damaged save is ignored
    and the game starts with its default hi-scores.

TECHNICAL NOTES
  Changes to the ROM (no interrupt is hooked and the game's bank switching is untouched):
    Header          0x147 01 -> 03 (MBC1+RAM+BATTERY), 0x149 00 -> 02 (8 KB RAM),
                    header and global checksums recalculated.
    60 places       "ld ($3FFF),a" -> "ld ($2000),a". The game selects ROM banks by writing
                    to $3FFF. A real MBC1 treats $2000-$3FFF as one bank register, but on an
                    MBC5-style mapper $3000-$3FFF is the 9th bank bit, so the bank never
                    changed there. Same instruction length, same effect on a real MBC1.
    0x0186          "ld a,1 ; ld ($D719),a" in the boot code replaced by
                    "call ${load_addr:04X} ; nop ; nop" (boot hook; the new code ends with the same two
                    instructions).
    bank 3 $49F5    end of Galaxian's hi-score copy routine ("ld (de),a ; dec de ; ret")
                    replaced by "jp ${gx_addr:04X}".
    bank 6 $4FCE    end of Galaga's hi-score copy routine ("ld a,(hl) ; ld (de),a ; ret")
                    replaced by "jp ${gg_addr:04X}". Each stub repeats the replaced instructions,
                    saves, and returns with every register and flag as the game expects.
    0x{save_addr:04X}-0x{end_addr:04X}  the new code, {total_len} bytes, in unused padding at the end of bank 0
                    (bank 0 is always mapped, so the stubs work whichever bank is selected).
  Game RAM:   Galaxian hi-score $D70D-$D711, Galaga hi-score $D712-$D716: five bytes each,
              one decimal digit per byte (low nibble), lowest digit first; the units
              digit (always 0) is not stored. The defaults are written at boot, right
              after the game clears its RAM and before the load runs.
  Save RAM at $A000: the ten bytes, then a check byte ($A5 + their sum).
  Load runs once per boot, after the game has set its defaults; a valid record replaces
  them, a missing or damaged one (bad check byte or a non-digit) leaves them alone. With
  DOWN + SELECT held it writes the defaults to the save instead.
  Save runs only when the game's own routine has copied a score that is higher than the
  hi-score (the routines at bank 3 $49CB and bank 6 $4FA7). Nothing runs every frame.
  If you have Python, you can try this yourself using the scripts from the
  repository{repo_note}:
  {patcher_script} rebuilds the patched ROM from your original ROM, and
  {release_script} builds the patches, READMEs and zip.

TESTING
  {tested_on}

VERSION HISTORY
  {version}  Initial release.

LEGAL
  This package contains no game data, only the differences. You need your own
  copy of the original game. Galaga and Galaxian are the property of their respective
  owners; this is an unofficial fan modification and is not affiliated with them.
"""

README_MD = """\
# {name}

**Hi-score saving** for *Galaga & Galaxian* (Game Boy, Europe, Super Game Boy enhanced). The game is
unchanged: no new screens or menus. The hi-score of each game, Galaga and Galaxian, is simply still
there next time, instead of going back to its default (30000 and 5000) whenever the console is switched off.

It also fixes a compatibility problem: the original ROM selects its ROM banks in a way that only works
on a genuine MBC1, so on many cheap rewritable cartridges (MBC5-style mappers) its graphics came out
garbled. With this patch it also runs on those.

**Download:** see the [latest release]({releases_url}) (BPS and IPS patches).
This repository contains no game data; you need your own copy of the ROM.

## Base ROM

The patch applies to exactly this file:

| This | Should be this |
|-------|-----|
| Name | `{rom_name}` |
| Size | {size} bytes |
| CRC32 | `{crc32}` |
| MD5 | `{md5}` |
| SHA-1 | `{sha1}` |

A copy named `.sgb` with the same CRC32 is the same data: rename it to `.gb` (some flash cartridges
cannot read `.sgb` files). The BPS patch verifies the ROM and refuses to apply to anything else; the
IPS patch cannot.

## Patching

Apply the `.bps` patch (preferred) or the `.ips` patch to your ROM with the online patcher at
<https://www.romhacking.net/patch/> (it works in your browser, so there is nothing to
install) or any other IPS/BPS patcher. Your original is not modified.

## Requirements

Saving needs cartridge RAM:

- **Emulators:** anything that supports MBC1 + RAM + battery (BGB, SameBoy, mGBA, ...).
  A `.sav` file appears next to the ROM.
- **Hardware:** a flash cart or rewritable cartridge supporting MBC1 with 8 KB of save
  RAM. Battery-backed RAM and non-volatile FRAM both qualify.

Without save RAM the game still plays, but, as in the original game, the hi-scores are lost when
the console is switched off.

## Using it

- Nothing to do: a hi-score is stored automatically whenever you beat it.
- The game's four-button soft reset keeps the hi-scores, as in the original game.
- **Reset both hi-scores to their defaults:** switch the console on while holding **Down + Select**.
- On a Super Game Boy the Game Boy version uses the same saved hi-scores as on any other Game Boy.

## Limitations

- Only the hi-scores are saved.
- The save has a check byte and every digit is validated, so a damaged save is ignored and the
  game starts with its default hi-scores.

## How it works

No interrupt is hooked and the game's bank switching is untouched. The header is changed to
MBC1+RAM+BATTERY (`0x147` 01 to 03, `0x149` 00 to 02) and its checksums are recalculated.

| Where | What |
|---|---|
| 60 places | `ld ($3FFF),a` becomes `ld ($2000),a`. The game selects ROM banks by writing to `$3FFF`. A real MBC1 treats `$2000`-`$3FFF` as one bank register, but on an MBC5-style mapper `$3000`-`$3FFF` is the 9th bank bit, so the bank never changed there. Same instruction length, same effect on a real MBC1 |
| `0x0186` | boot hook: `ld a,1 ; ld ($D719),a` becomes `call ${load_addr:04X} ; nop ; nop` (the new code ends with the same two instructions) |
| bank 3 `$49F5` | end of Galaxian's hi-score copy routine becomes `jp ${gx_addr:04X}` |
| bank 6 `$4FCE` | end of Galaga's hi-score copy routine becomes `jp ${gg_addr:04X}`. Each stub repeats the replaced instructions, saves, and returns with every register and flag as the game expects |
| `0x{save_addr:04X}`-`0x{end_addr:04X}` | the new code, {total_len} bytes, in unused padding at the end of bank 0 (always mapped, so the stubs work whichever bank is selected) |

Game RAM: Galaxian hi-score `$D70D`-`$D711`, Galaga hi-score `$D712`-`$D716`: five bytes each, one
decimal digit per byte (low nibble), lowest digit first; the units digit (always 0) is not stored.
The defaults are written at boot, right after the game clears its RAM and before the load runs.
Save RAM at `$A000`: the ten bytes plus a check byte (`$A5` + their sum).

- The **load routine** runs once per boot, after the game has set its defaults. A valid record replaces
  them; a missing or damaged one (bad check byte or a non-digit) leaves them alone. With Down + Select
  held it writes the defaults to the save instead.
- The **save routine** runs only when the game's own routine has copied a score higher than the
  hi-score (bank 3 `$49CB`, bank 6 `$4FA7`). Nothing runs every frame.

If you have Python, you can try this yourself using the scripts from the repository:
`{patcher_script}` rebuilds the patched ROM from your original ROM, and
`{release_script}` builds the patches, READMEs and zip.

## Tested

{tested_on}

## Legal

No game data is included, only the differences. *Galaga* and *Galaxian* belong to their respective
owners; this is an unofficial fan modification and is not affiliated with them.
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("rom")
    ap.add_argument("--author", default="Your Name")
    ap.add_argument("--version", default="1.0")
    ap.add_argument("--outdir", default="release")
    ap.add_argument("--repo", default="", help="repository URL, used in README.txt and for the release link in README.md")
    a = ap.parse_args()

    src_path = Path(a.rom)
    src = src_path.read_bytes()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_src = Path(tmp) / src_path.name
        shutil.copy(src_path, tmp_src)
        patched_path = pb.main(str(tmp_src))      # the patcher says where it wrote the ROM
        dst = Path(patched_path).read_bytes()

    ips, bps = make_ips(src, dst), make_bps(src, dst)
    assert apply_ips(src, ips) == dst, "IPS round trip failed"
    assert apply_bps(src, bps) == dst, "BPS round trip failed"
    print(f"IPS: {len(ips)} bytes, BPS: {len(bps)} bytes (both verified against the real output)")
    print(f"Patched ROM: CRC32 {zlib.crc32(dst):08X}  SHA-1 {hashlib.sha1(dst).hexdigest().upper()}")

    base = f"{FILE_NAME} v{a.version}"
    # layout numbers come from the patcher, so the README can never drift from the code
    code, labels = pb.build(pb.FREE[0])
    names = dict(patcher_script=Path(pb.__file__).name, release_script=Path(__file__).name,
                 save_addr=pb.FREE[0], end_addr=pb.FREE[0] + len(code) - 1, total_len=len(code),
                 load_addr=labels["Load"], gx_addr=labels["StubGalaxian"], gg_addr=labels["StubGalaga"],
                 tested_on=TESTED_ON)
    hashes = dict(rom_name=src_path.name, size=len(src), crc32=f"{zlib.crc32(src):08X}",
                  md5=hashlib.md5(src).hexdigest().upper(), sha1=hashlib.sha1(src).hexdigest().upper())
    names_txt = dict(names, tested_on=TESTED_ON.replace("\n", "\n  "))   # keep README.txt's indentation
    readme = README.format(repo_note=f" ({a.repo})" if a.repo else "", **names_txt, **hashes,
                           name=NAME, version=a.version, author=a.author,
                           date=datetime.date.today().isoformat())
    releases_url = f"{a.repo.rstrip('/')}/releases/latest" if a.repo else "../../releases/latest"
    readme_md = README_MD.format(**names, **hashes, releases_url=releases_url, name=NAME)

    outdir = Path(a.outdir)
    outdir.mkdir(exist_ok=True)
    (outdir / "README.md").write_text(readme_md, encoding="utf-8")
    zpath = outdir / f"{base}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{base}.bps", bps)
        z.writestr(f"{base}.ips", ips)
        z.writestr("README.txt", readme)
    print(f"Written: {zpath}")
    print(f"Base ROM CRC32 {hashes['crc32']}  SHA-1 {hashes['sha1']}")


if __name__ == "__main__":
    main()
