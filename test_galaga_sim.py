"""Safety check for patch_galaga.py. Needs no game data and no ROM file.

WHEN TO RUN IT
  Every time you change patch_galaga.py (new hook, moved code, different padding area,
  a new feature, a fix) and before you build a release. Also if you ever wonder whether the
  patch is still safe. It takes a few seconds and needs only Python.

WHY
  The patch hooks into the game's own hi-score routines and boot code. The danger is changing
  something the game relies on (a register, a flag, a memory byte, the stack) so that it crashes
  or misbehaves at some point you did not happen to test by hand. This test checks that
  systematically, with thousands of random cases, so real hardware only has to confirm the result.

USAGE
  python test_galaga_sim.py        (patch_galaga.py must be in the same folder)
  It prints "ALL TESTS PASSED" at the end. Anything else (an AssertionError or an exception)
  means the change broke something: do not release it.

WHAT IT DOES
  Builds a stand-in ROM in a temporary folder, from the bytes the patcher checks, patches it,
  and runs the patched code on a small SM83 simulator:
    - only the intended bytes changed (the 60 bank writes, headers, hooks, new code);
    - boot hook: a valid save is restored; missing, damaged or non-digit saves are ignored;
      Down + Select at power-on writes the defaults; other button combinations do not;
    - the two games' own hi-score routines, original against patched: same registers, flags, RAM
      and exit point, and the save is written exactly when the game copies a new hi-score;
    - a saved record comes back after a simulated power cycle; random garbage is never accepted.
  It cannot test things only real hardware shows (mapper behaviour, timing, battery RAM).
"""
import random, importlib.util, zlib, tempfile, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp()
spec = importlib.util.spec_from_file_location("p", os.path.join(HERE, "patch_galaga.py"))
p = importlib.util.module_from_spec(spec); spec.loader.exec_module(p)
R = random.Random(7)

class CPU:
    def __init__(s, img, sram, dpad=0, btn=0):
        s.mem = bytearray(0x10000); s.mem[:0x8000] = img; s.sram = sram; s.en = False
        s.r = dict.fromkeys("abcdehl", 0); s.z = s.n = s.hf = s.cf = False
        s.sp = 0xDFFF; s.pc = 0; s.sel = 0x30; s.dpad, s.btn = dpad, btn; s.sw = s.sr = 0; s.bankw = []
    def F(s): return s.z << 7 | s.n << 6 | s.hf << 5 | s.cf << 4
    def setF(s, f): s.z, s.n, s.hf, s.cf = bool(f & 128), bool(f & 64), bool(f & 32), bool(f & 16)
    def rp(s, a, b): return s.r[a] << 8 | s.r[b]
    def sp16(s, a, b, v): v &= 0xFFFF; s.r[a], s.r[b] = v >> 8, v & 255
    def rd(s, a):
        if a < 0x8000: return s.mem[a]
        if 0xA000 <= a < 0xC000:
            if s.en: s.sr += 1; return s.sram[a - 0xA000]
            return 0xFF
        if a == 0xFF00:
            v = 0x0F
            if not s.sel & 0x10: v &= ~s.dpad & 15
            if not s.sel & 0x20: v &= ~s.btn & 15
            return 0xC0 | s.sel | v
        return s.mem[a]
    def wr(s, a, v):
        if a < 0x2000: s.en = (v & 15) == 0xA; return
        if a < 0x8000: s.bankw.append((a, v)); return
        if 0xA000 <= a < 0xC000:
            if s.en: s.sw += 1; s.sram[a - 0xA000] = v
            return
        if a == 0xFF00: s.sel = v & 0x30; return
        s.mem[a] = v
    def f8(s): v = s.rd(s.pc); s.pc += 1; return v
    def f16(s): lo = s.f8(); return lo | s.f8() << 8
    def push(s, v): s.sp -= 1; s.wr(s.sp, v >> 8); s.sp -= 1; s.wr(s.sp, v & 255)
    def pop(s): lo = s.rd(s.sp); s.sp += 1; hi = s.rd(s.sp); s.sp += 1; return hi << 8 | lo
    def cp(s, v): a = s.r['a']; s.z = a == v; s.n = True; s.hf = (a & 15) < (v & 15); s.cf = a < v
    def run(s, start, stop, limit=20000):
        s.pc = start; r = s.r
        for _ in range(limit):
            if s.pc == stop: return
            op = s.f8()
            if op == 0x00: pass
            elif op == 0x06: r['b'] = s.f8()
            elif op == 0x0E: r['c'] = s.f8()
            elif op == 0x3E: r['a'] = s.f8()
            elif op == 0x21: r['l'] = s.f8(); r['h'] = s.f8()
            elif op == 0x11: r['e'] = s.f8(); r['d'] = s.f8()
            elif op == 0xEA: a = s.f16(); s.wr(a, r['a'])
            elif op == 0xF0: r['a'] = s.rd(0xFF00 + s.f8())
            elif op == 0xE0: s.wr(0xFF00 + s.f8(), r['a'])
            elif op == 0x2A: r['a'] = s.rd(s.rp('h', 'l')); s.sp16('h', 'l', s.rp('h', 'l') + 1)
            elif op == 0x3A: r['a'] = s.rd(s.rp('h', 'l')); s.sp16('h', 'l', s.rp('h', 'l') - 1)
            elif op == 0x12: s.wr(s.rp('d', 'e'), r['a'])
            elif op == 0x1A: r['a'] = s.rd(s.rp('d', 'e'))
            elif op == 0x7E: r['a'] = s.rd(s.rp('h', 'l'))
            elif op == 0x47: r['b'] = r['a']
            elif op == 0x4F: r['c'] = r['a']
            elif op == 0x79: r['a'] = r['c']
            elif op == 0x81:
                v = r['a'] + r['c']; s.hf = (r['a'] & 15) + (r['c'] & 15) > 15; s.cf = v > 255; s.n = False
                r['a'] = v & 255; s.z = r['a'] == 0
            elif op == 0xB8: s.cp(r['b'])
            elif op == 0xB9: s.cp(r['c'])
            elif op == 0xFE: s.cp(s.f8())
            elif op == 0xA7: s.z = r['a'] == 0; s.n = False; s.hf = True; s.cf = False
            elif op == 0xE6: r['a'] &= s.f8(); s.z = r['a'] == 0; s.n = False; s.hf = True; s.cf = False
            elif op == 0xAF: r['a'] = 0; s.z = True; s.n = s.hf = s.cf = False
            elif op in (0x05, 0x0D):
                k = 'b' if op == 0x05 else 'c'; s.hf = (r[k] & 15) == 0; r[k] = (r[k] - 1) & 255; s.z = r[k] == 0; s.n = True
            elif op == 0x13: s.sp16('d', 'e', s.rp('d', 'e') + 1)
            elif op == 0x1B: s.sp16('d', 'e', s.rp('d', 'e') - 1)
            elif op == 0x23: s.sp16('h', 'l', s.rp('h', 'l') + 1)
            elif op == 0x2B: s.sp16('h', 'l', s.rp('h', 'l') - 1)
            elif op in (0x18, 0x20, 0x28, 0x30, 0x38):
                o = s.f8(); o -= 256 if o > 127 else 0
                if op == 0x18 or (op == 0x20 and not s.z) or (op == 0x28 and s.z) or \
                   (op == 0x30 and not s.cf) or (op == 0x38 and s.cf): s.pc += o
            elif op == 0xC8:
                if s.z: s.pc = s.pop()
            elif op == 0xD0:
                if not s.cf: s.pc = s.pop()
            elif op == 0xC9: s.pc = s.pop()
            elif op == 0xC3: s.pc = s.f16()
            elif op == 0xCD: t = s.f16(); s.push(s.pc); s.pc = t
            elif op == 0xF5: s.push(r['a'] << 8 | s.F())
            elif op == 0xC5: s.push(s.rp('b', 'c'))
            elif op == 0xD5: s.push(s.rp('d', 'e'))
            elif op == 0xE5: s.push(s.rp('h', 'l'))
            elif op == 0xF1: v = s.pop(); r['a'] = v >> 8; s.setF(v & 255)
            elif op == 0xC1: s.sp16('b', 'c', s.pop())
            elif op == 0xD1: s.sp16('d', 'e', s.pop())
            elif op == 0xE1: s.sp16('h', 'l', s.pop())
            else: raise Exception(f"unimplemented opcode {op:02X} at {s.pc - 1:04X}")
        raise Exception("did not finish")

# ---- stand-in ROM: the real bytes the patcher checks, plus the 60 bank writes
orig = bytearray(0x20000)
orig[0x134:0x143] = b"GALAGA&GALAXIAN"; orig[0x147] = 1; orig[0x148] = 2; orig[0x149] = 0
for a, b in (p.BOOT_CONTEXT, p.DEFAULTS, p.DEFAULT_DATA, (p.GALAXIAN_AT, p.GALAXIAN_ROUTINE), (p.GALAGA_AT, p.GALAGA_ROUTINE)):
    orig[a:a + len(b)] = b
orig[p.FREE[0]:p.FREE[1]] = b"\xFF" * (p.FREE[1] - p.FREE[0])
sites = []
while len(sites) < 60:
    x = R.randrange(0x400, 0x3D00) + R.choice([0, 0x4000, 0x8000, 0xC000, 0x10000, 0x1C000])
    if all(abs(x - y) > 4 for y in sites) and not (p.GALAXIAN_AT - 4 <= x < p.GALAXIAN_AT + 60) \
       and not (p.GALAGA_AT - 4 <= x < p.GALAGA_AT + 60) and not (0x160 <= x < 0x1A0) and not (0x1670 <= x < 0x16A0):
        sites.append(x)
for x in sites: orig[x:x + 3] = p.MAPPER_OLD
assert len(p.find_all(orig, p.MAPPER_OLD)) == 60
open(os.path.join(TMP, "ga.gb"), "wb").write(orig)

import sys
real_crc = p.BASE_CRC32; p.BASE_CRC32 = zlib.crc32(bytes(orig))
p.main(os.path.join(TMP, "ga.gb"))
out = bytearray(open(os.path.join(TMP, "ga (hi-score save).gb"), "rb").read())
p.main(os.path.join(TMP, "ga.gb"), header_only=True); p.main(os.path.join(TMP, "ga.gb"), mode="load"); p.main(os.path.join(TMP, "ga.gb"), mode="save")
p.BASE_CRC32 = real_crc

code, labels = p.build(p.FREE[0])
allowed = {0x147, 0x149, 0x14D, 0x14E, 0x14F} | set(range(p.BOOT_HOOK, p.BOOT_HOOK + 5)) \
    | set(range(p.GALAXIAN_HOOK, p.GALAXIAN_HOOK + 3)) | set(range(p.GALAGA_HOOK, p.GALAGA_HOOK + 3)) \
    | set(range(p.FREE[0], p.FREE[0] + len(code))) | {x + k for x in sites for k in (1, 2)}
changed = [i for i in range(len(orig)) if orig[i] != out[i]]
assert set(changed) <= allowed, [hex(i) for i in changed if i not in allowed]
assert all(out[x:x + 3] == p.MAPPER_NEW for x in sites) and p.MAPPER_OLD not in out
assert out[p.BOOT_HOOK:p.BOOT_HOOK + 5] == b"\xCD" + labels["Load"].to_bytes(2, "little") + b"\0\0"
assert out[p.GALAXIAN_HOOK] == 0xC3 and out[p.GALAGA_HOOK] == 0xC3
assert out[0x147] == 3 and out[0x149] == 2 and out[0x148] == 2
assert out[p.FREE[0] + len(code):p.FREE[1]] == b"\xFF" * (p.FREE[1] - p.FREE[0] - len(code))
assert b"\xEA\xFF\x3F" not in out
g = (sum(out) - out[0x14E] - out[0x14F]) & 0xFFFF; assert out[0x14E] << 8 | out[0x14F] == g
c = 0
for b in out[0x134:0x14D]: c = (c - b - 1) & 0xFF
assert out[0x14D] == c
for name, mode in (("hdr", None),):
    pass
hdr = bytearray(open(os.path.join(TMP, "ga (header only).gb"), "rb").read())
assert [i for i in range(len(orig)) if orig[i] != hdr[i]] and p.FREE[0] not in [i for i in range(len(orig)) if orig[i] != hdr[i]]
ld = bytearray(open(os.path.join(TMP, "ga (load only).gb"), "rb").read()); sv = bytearray(open(os.path.join(TMP, "ga (save only).gb"), "rb").read())
assert ld[p.GALAXIAN_HOOK:p.GALAXIAN_HOOK+3] == orig[p.GALAXIAN_HOOK:p.GALAXIAN_HOOK+3] and ld[p.BOOT_HOOK] == 0xCD
assert sv[p.BOOT_HOOK:p.BOOT_HOOK+5] == orig[p.BOOT_HOOK:p.BOOT_HOOK+5] and sv[p.GALAXIAN_HOOK] == 0xC3
print(f"bytes changed: {len(changed)} (all inside the intended places); {len(code)} bytes of new code, 60 bank writes fixed; diagnostic builds OK")

def image(rom, bank): return bytes(rom[:0x4000]) + bytes(rom[bank * 0x4000:(bank + 1) * 0x4000])
def rec(b): return bytearray(list(b) + [(0xA5 + sum(b)) & 255]) + bytearray(8192 - 11)
DEF = [0, 0, 5, 0, 0, 0, 0, 0, 3, 0]                       # D70D..D716: Galaxian 5000, Galaga 30000
def digits(n): return [R.randrange(10) for _ in range(n)]

# ---- boot: original vs patched, from the hook point $0186 to $018B
def boot(rom, sram, ram, dpad=0, btn=0, regs=None):
    c = CPU(image(rom, 1), sram, dpad, btn); c.sp = 0xDFFF
    for i, v in enumerate(ram): c.mem[p.HI + i] = v
    for k in c.r: c.r[k] = (regs or {}).get(k, 0)
    c.run(0x0186, 0x018B); return c
def hi(c): return [c.mem[p.HI + i] for i in range(10)]

for _ in range(300):
    regs = {k: R.randrange(256) for k in "bcdehl"}
    o = boot(orig, bytearray(8192), DEF, regs=regs)
    for sram in (bytearray(8192), bytearray(b"\xFF" * 8192), bytearray(R.randbytes(8192)), rec(digits(10))):
        n = boot(out, sram, DEF, regs=regs)
        for k in "bcdehl": assert n.r[k] == o.r[k], k
        assert n.r['a'] == 1 and n.mem[0xD719] == 1 and n.sp == o.sp == 0xDFFF and not n.en and n.sel == 0x30
        assert [i for i in range(0xC000, 0xE000) if o.mem[i] != n.mem[i] and not p.HI <= i < p.HI + 10 and i < 0xDFF0] == []
        assert n.bankw == [] and n.sw == 0
good = digits(10)
assert hi(boot(out, rec(good), DEF)) == good
assert hi(boot(out, bytearray(8192), DEF)) == DEF and hi(boot(out, bytearray(b"\xFF" * 8192), DEF)) == DEF
t = rec(good); t[10] ^= 1; assert hi(boot(out, t, DEF)) == DEF                      # bad check byte
t = rec(good); t[3] ^= 1; assert hi(boot(out, t, DEF)) == DEF                       # bad data
bad = list(good); bad[4] = 10; assert hi(boot(out, rec(bad), DEF)) == DEF           # check ok, digit invalid
bad = list(good); bad[9] = 0x30; assert hi(boot(out, rec(bad), DEF)) == DEF
s = rec(good); c = boot(out, s, DEF, dpad=0x08, btn=0x04)
assert hi(c) == DEF and bytes(s[:11]) == bytes(rec(DEF)[:11]), "combo must write the defaults"
assert hi(boot(out, s, [1] * 10)) == DEF, "the wipe must stick"
for btn, dpad in ((0, 0), (4, 0), (0, 8), (8, 8), (0x0F, 0x07), (0x0B, 0x00), (0x0F, 0x00), (0x03, 0x04)):
    s = rec(good); assert hi(boot(out, s, DEF, dpad=dpad, btn=btn)) == good, (btn, dpad)
    assert bytes(s[:11]) == bytes(rec(good)[:11])
assert hi(boot(out, rec(good), DEF, dpad=0x0F, btn=0x0F)) == DEF                    # superset incl. Down+Select
print("boot / restore / integrity / reset combo / four-button no-wipe: OK")

# ---- the games' own copy routines, original vs patched
def update(rom, bank, entry, hi_at, sc_at, score, hivals, sram, regs):
    c = CPU(image(rom, bank), sram); c.sp = 0xDFF0; c.push(0x7FF0)
    for i, v in enumerate(score): c.mem[sc_at + i] = v
    for i, v in enumerate(hivals): c.mem[p.HI + i] = v
    c.r.update(regs); c.run(entry, 0x7FF0); return c
games = (("Galaxian", 3, 0x49CB, 0xC558, 5, 0), ("Galaga", 6, 0x4FA7, 0xCC7A, 5, 5))
tot = {}
for name, bank, entry, sc_at, nd, off in games:
    copies = same = 0
    for _ in range(4000):
        score = digits(nd); hv = digits(10)
        m = R.random()
        if m < .2: hv[off:off + nd] = score                   # equal: no copy
        elif m < .45:                                         # differ only in one digit
            hv[off:off + nd] = score; k = R.randrange(nd); hv[off + k] = (hv[off + k] + R.choice([1, -1])) % 10
        regs = {k: R.randrange(256) for k in "abcdehl"}
        sram = rec(digits(10)) if R.random() < .5 else bytearray(8192); before = bytes(sram)
        o = update(orig, bank, entry, None, sc_at, score, hv, bytearray(8192), regs)
        n = update(out, bank, entry, None, sc_at, score, hv, sram, regs)
        assert o.pc == n.pc == 0x7FF0 and o.sp == n.sp == 0xDFF0
        for k in "abcdehl": assert o.r[k] == n.r[k], (name, k, score, hv)
        assert (o.z, o.n, o.hf, o.cf) == (n.z, n.n, n.hf, n.cf), (name, "flags")
        assert [i for i in range(0xC000, 0xE000) if o.mem[i] != n.mem[i] and i < 0xDFE0] == []
        assert n.bankw == [] and not n.en
        if hi(o) != hv:                                       # the game copied a new hi-score
            copies += 1; assert bytes(sram[:11]) == bytes(rec(hi(o))[:11]), (name, "save record")
            assert hi(boot(out, sram, DEF)) == hi(o)          # and it comes back after a power cycle
        else:
            same += 1; assert n.sw == 0 and n.sr == 0 and bytes(sram) == before, (name, "touched SRAM")
    tot[name] = (copies, same)
print("update routines identical to the originals (registers, flags, RAM, exit); saved on copies, SRAM untouched otherwise:", tot)

ok = sum(hi(boot(out, bytearray(R.randbytes(8192)), DEF)) != DEF for _ in range(20000))
print("random garbage accepted as a save:", ok, "of 20000 (expected ~0)")
assert ok == 0
print("ALL TESTS PASSED")
