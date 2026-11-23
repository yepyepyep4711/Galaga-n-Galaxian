# Galaga & Galaxian - Hi-score Save

**Hi-score saving** for *Galaga & Galaxian* (Game Boy, Europe, Super Game Boy enhanced). The game is
unchanged: no new screens or menus. The hi-score of each game, Galaga and Galaxian, is simply still
there next time, instead of going back to its default (30000 and 5000) whenever the console is switched off.

It also fixes a compatibility problem: the original ROM selects its ROM banks in a way that only works
on a genuine MBC1, so on many cheap rewritable cartridges (MBC5-style mappers) its graphics came out
garbled. With this patch it also runs on those.

**Download:** see the [latest release](https://github.com/yepyepyep4711/Galaga-n-Galaxian/releases/latest) (BPS and IPS patches).
This repository contains no game data; you need your own copy of the ROM.

## Base ROM

The patch applies to exactly this file:

| This | Should be this |
|-------|-----|
| Name | `Galaga & Galaxian (E) [S][!].gb` |
| Size | 131072 bytes |
| CRC32 | `D06B3F8A` |
| MD5 | `08F46BB59E52562F08C76F4E6C0040C5` |
| SHA-1 | `59EA594AF8520732F78C337F5C96A5BA2BDDF1CB` |

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
| `0x0186` | boot hook: `ld a,1 ; ld ($D719),a` becomes `call $3D6C ; nop ; nop` (the new code ends with the same two instructions) |
| bank 3 `$49F5` | end of Galaxian's hi-score copy routine becomes `jp $3D58` |
| bank 6 `$4FCE` | end of Galaga's hi-score copy routine becomes `jp $3D5C`. Each stub repeats the replaced instructions, saves, and returns with every register and flag as the game expects |
| `0x3D3A`-`0x3DC9` | the new code, 144 bytes, in unused padding at the end of bank 0 (always mapped, so the stubs work whichever bank is selected) |

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
`patch_galaga.py` rebuilds the patched ROM from your original ROM, and
`make_release_galaga.py` builds the patches, READMEs and zip.

## Tested

Emulators: BGB and mGBA.
Real hardware: EZ Flash Jr and generic single-game rewritable cartridges, played on Game Boy,
Game Boy Color, Super Game Boy, Analogue Pocket and ModRetro Chromatic. Tested: saving, loading,
hi-score reset and soft resets, in both games.

## Legal

No game data is included, only the differences. *Galaga* and *Galaxian* belong to their respective
owners; this is an unofficial fan modification and is not affiliated with them.
