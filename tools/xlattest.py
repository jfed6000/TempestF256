#!/usr/bin/env python3
"""xlattest.py - the differential test on the translated game (plan D6, step 3).

Loads the module m65to09.py built (xlat/tempest.bin), finds each routine by its label, and runs it
against Atari's own routine in the Rev 3 ROM on the same inputs, with d6pilot.py's rig: all of
arcade RAM, vector RAM, the POKEY image and A/X/Y compared, at two code/data layouts.

    xlattest.py                  every routine with a case generator
    xlattest.py MODSND -n 2000   one routine
"""

import argparse
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.dirname(__file__))
import d6pilot                                  # noqa: E402
import m65parse                                 # noqa: E402
import romalign                                 # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
XLAT = os.path.join(ROOT, "xlat")


def load_module():
    code = open(os.path.join(XLAT, "tempest.bin"), "rb").read()
    labels = {}
    for line in open(os.path.join(XLAT, "tempest.lst")):
        if line.startswith("[ G]"):
            name, val = line[4:].split()
            labels[name] = int(val, 16)
    return code, labels


def inimat_then(mb):
    def before():
        d6pilot.inimat(mb)
    return before


def cases_modsnd_valid(rng, n):
    """d6pilot's MODSND states with POINT inside the real sound table.  Rev 3's table ends at
    IPEXPL, SOUND+$E5, so the 9-bit half (the ELSE of IFCC) never runs in the game, and a POINT past
    the table reads code bytes - which the port's module does not have in the same place."""
    s = d6pilot.syms()
    for arc, vr, a, x, y in d6pilot.cases_modsnd(rng, n):
        for ch in range(16):
            if arc[s["POINT"] + ch] > 0x6E:     # (POINT+2)*2+3 below IPEXPL-SOUND = $E5
                arc[s["POINT"] + ch] = rng.randrange(1, 0x6F)
        yield arc, vr, a, x, y


# routine -> (case generator, set-up before each 6502 call)
def routines(mb):
    return {
        "MODSND": (cases_modsnd_valid, None),
        "DSPNYM": (d6pilot.cases_dspnym, None),
    }


# Variables whose values the game keeps in a small range; the fuzz respects them.
DOMAIN = {"PLAYUP": (0, 1),
          # the dispatchers' indices: even entries of their tables (ROUTAD 16, DROUTAD 12,
          # SPARAD/NPARAD 7 words)
          "QSTATE": tuple(range(0, 32, 2)), "QDSTAT": tuple(range(0, 24, 2)),
          "TYPCOD": tuple(range(0, 14, 2))}
# Register inputs of routines, where the game passes a small range: (A, X, Y), None = any.
# SBCLOG/SBCSWI/SBCACT take a display-buffer group, BCINFO..BCSTAR = 0..8 (ALEXEC.MAP).
REG_DOMAIN = {"SBCLOG": (range(9), None, None), "SBCSWI": (range(9), None, None),
              "SBCACT": (range(9), None, None),
              "JSRCAM": (range(0, 0x24, 2), None, None),      # a cam opcode (TABJSR, 18 words)
              "SPECIA": (None, None, range(0, 8, 2)),         # XSUBR, 4 words
              "NEWTY2": (range(5), None, None), "NEWTYP": (None, range(5), None)}   # NYMTAD


class XRig(d6pilot.Rig):
    """The pilot's rig with every big-endian pointer mapped (not just VGLIST) and the hardware
    shadow cleared per case."""

    # Arcade and port addresses coincide (data area at $0000, window at $2000), so a pointer's
    # value needs no relocation, only its bytes swapped: TEMP3/TEMP4 is a pointer in one routine
    # and two scalars in another, and relocating "pointer values" would corrupt the scalars.  The
    # module still runs at two code addresses; d6pilot.py tests relocated data areas.
    LAYOUTS = [dict(code=0x8000, data=0x0000, window=0x2000),
               dict(code=0x8123, data=0x0000, window=0x2000)]    # the module is ~28K: it must fit

    def __init__(self, *args, pointers=(), **kw):
        code = args[2]
        for cfg in self.LAYOUTS:
            if cfg["code"] + len(code) > 0xFE00:
                raise ValueError("module does not fit at $%04X" % cfg["code"])
        saved = d6pilot.CONFIGS[:]
        d6pilot.CONFIGS[:] = self.LAYOUTS
        try:
            super().__init__(*args, **kw)
        finally:
            d6pilot.CONFIGS[:] = saved
        self.ptrs = sorted(pointers)
        self.violations = []
        for c in self.cpus:
            lo = c.cfg["code"]
            hi = lo + len(self.code) - 1

            def guard(a, v, c=c):
                self.violations.append("store to its own code at $%04X (offset $%04X) from pc $%04X"
                                       % (a, a - c.cfg["code"], c.pc - c.cfg["code"]))
            c.map_io(lo, hi, None, guard)

    def run6809(self, c, entry, arcade, vram, a, x, y):
        cfg = c.cfg
        d, w = cfg["data"], cfg["window"]

        def to_port(v):
            if 0x2000 <= v < 0x3000:
                return (v - 0x2000 + w) & 0xFFFF
            if v < 0x800:
                return (v + d) & 0xFFFF
            return v

        def to_arcade(v):
            if w <= v < w + 0x1000:
                return v - w + 0x2000
            if d <= v < d + 0x800:
                return v - d
            return v

        c.mem[0:0x10000] = bytes(0x10000)           # nothing left over from the last case
        c.mem[cfg["code"]:cfg["code"] + len(self.code)] = self.code
        c.static.clear()
        c.mem[d:d + 0x800] = arcade
        c.mem[d + 0x800:d + 0xA00] = bytes(0x200)
        c.mem[w:w + 0x1000] = vram
        for p in self.ptrs:
            v = to_port(arcade[p] | arcade[p + 1] << 8)
            c.mem[d + p], c.mem[d + p + 1] = v >> 8, v & 0xFF
        c.mem[d + 0x810], c.mem[d + 0x811] = w >> 8, w & 0xFF        # VWIN: window A
        c.mem[d + 0xB8] = c.mem[d + 0xBA] = d >> 8
        c.mem[d + 0xB9] = x
        c.mem[d + 0xBB] = y
        c.a, c.b = a, random.randrange(256)
        c.x = c.y = random.randrange(0x10000)
        c.u, c.dp, c.s = d, d >> 8, d6pilot.STACK
        c.cc = 0x50
        cyc = c.call(cfg["code"] + self.labels[entry], limit=2_000_000)
        out = bytearray(c.mem[d:d + 0x800])
        for p in self.ptrs:
            v = to_arcade(c.mem[d + p] << 8 | c.mem[d + p + 1])
            out[p], out[p + 1] = v & 0xFF, v >> 8
        return cyc, out, bytes(c.mem[w:w + 0x1000]), bytes(c.mem[d + 0x800:d + 0x810]), \
            (c.a, c.mem[d + 0xB9], c.mem[d + 0xBB])


SYMS = {}


def fuzz(ref, pokey, al, code, labels, n, seed, only=None, trace=False):
    """Every routine a JSR reaches, on random RAM with the pointers aimed at vector RAM."""
    import m65to09
    from cpu6502 import Halt as Halt65
    from cpu6809 import Halt as Halt09
    t = m65to09.Translator()
    SYMS.update(al.parsers["ALWELG"].syms)
    rig = XRig(ref, "B", code, labels, os.path.join(XLAT, "tempest.lst"), pointers=t.pointers)
    rig.pokey = pokey
    # the ROM must not be written through a random pointer
    ref.map_io(0x9000, 0xFFFF, None, lambda a, v: None)
    ref.map_io(0x3000, 0x3FFF, None, lambda a, v: None)
    cur = {"mode": None, "base": None}
    # A data read of ROM code means the input was outside what the game can produce (an index past
    # a table's end): such a case is skipped, not compared.  Instruction fetches do not go through
    # rd(), so only data reads are seen.
    data_bytes = set()
    for node in t.nodes:
        if node.kind == "data" and node.addr is not None and node.size:
            data_bytes.update(range(node.addr, node.addr + node.size))
    strayed = []
    # contiguous stretches of ROM data: the port keeps each one whole, but not what lies between
    run_of = {}
    run = 0
    for a_ in range(0x9000, 0xE000):
        if a_ in data_bytes:
            if a_ - 1 not in data_bytes:
                run += 1
            run_of[a_] = run

    def rom_read(a):
        if cur.get("mode") in ("izy", "izx"):
            strayed.append(a)               # a pointer into ROM: relocated at start-up on the port
        elif a not in data_bytes:
            strayed.append(a)               # code read as data
        elif cur.get("base") is not None and run_of.get(cur["base"]) != run_of.get(a):
            strayed.append(a)               # an index carried the read out of its table's stretch
        return ref.mem[a]
    ref.map_io(0x9000, 0xDFFF, rom_read, None)

    def vrom_read(a):
        if cur.get("mode") in ("izy", "izx"):
            strayed.append(a)               # likewise a pointer into vector ROM
        return ref.mem[a]
    ref.io.insert(0, (0x3000, 0x3FFF, vrom_read, None))

    def elsewhere(a, v=None):
        if cur.get("mode") in ("izy", "izx"):
            strayed.append(a)               # a pointer outside RAM and vector RAM
        if v is None:
            return ref.mem[a]
        ref.mem[a] = v
    for lo_, hi_ in ((0x0800, 0x1FFF), (0x7000, 0x8FFF), (0xE000, 0xEFFF)):
        ref.io.insert(0, (lo_, hi_, elsewhere, elsewhere))
    for lo_, hi_ in ((0x4000, 0x6FFF),):
        ref.io.append((lo_, hi_, elsewhere, None))

    def pokey_write(a, v):
        base = cur.get("base")
        if base is not None and not 0x60C0 <= base <= 0x60DF:
            strayed.append(a)               # an index carried another device's write onto POKEY
        if 0x60C0 <= a <= 0x60C7:
            pokey[a - 0x60C0] = v
        elif 0x60D0 <= a <= 0x60D7:
            pokey[8 + a - 0x60D0] = v
    ref.io.insert(0, (0x60C0, 0x60DF, None, pokey_write))
    # an indexed access landing on a pointer byte (which the port keeps big-endian) is likewise
    # outside the game's domain: the source names its pointers directly
    from cpu6502 import OPS

    def hook(cpu, pc, mn):
        mode = OPS[cpu.mem[pc]][1]
        cur["mode"] = mode
        cur["base"] = cpu.mem[pc + 1] | cpu.mem[pc + 2] << 8 if mode in ("abx", "aby") else None
    ref.step_hook = hook
    ptr_bytes = set(range(0xB8, 0xBC))         # and the pseudo-registers' bytes
    ptr_bytes |= set(range(0x1D0, 0x200))      # and the 6502's stack, where the harness's JSR is
    for pv in t.pointers:
        ptr_bytes |= {pv, pv + 1}

    def ptr_touch(a, v=None):
        if cur["mode"] in ("zpx", "zpy", "abx", "aby", "izy", "izx"):
            strayed.append(a)
        if v is None:
            return ref.mem[a]
        ref.mem[a] = v
    for pv in sorted(ptr_bytes):
        ref.map_io(pv, pv, ptr_touch, ptr_touch)

    # The Math Box is replaced by hand (WORSCR's coprocessor divide, pilot/worscr.a): a case that
    # reads a Math Box result is outside what the mechanical translation is tested for.
    def mathbox_read(a):
        strayed.append(a)
        return 0
    for a_ in (0x6040, 0x6060, 0x6070):
        ref.io.insert(0, (a_, a_, mathbox_read, None))
    entries = sorted({t.nodes[k.call].idx for k in t.nodes if k.call is not None})
    results = {}
    wraps = set()
    for e in entries:
        node = t.nodes[e]
        name = t.names[(node.file, node.labels[0])] if node.labels else None
        if name is None or name not in labels or (only and name not in only):
            continue
        rng = random.Random(seed)
        random.seed(seed)
        ok = skipped = 0
        fail = None
        for k in range(n):
            arc = bytearray(rng.randrange(256) for _ in range(0x800))
            for p in t.pointers:
                v = rng.randrange(0x2000, 0x2F00)
                arc[p], arc[p + 1] = v & 0xFF, v >> 8
            for sym, vals in DOMAIN.items():
                arc[SYMS[m65parse.sym6(sym)]] = rng.choice(vals)
            vram = bytes(rng.randrange(256) for _ in range(0x1000))
            regs = [rng.randrange(256), rng.randrange(256), rng.randrange(256)]
            for k, dom in enumerate(REG_DOMAIN.get(name, (None, None, None))):
                if dom is not None:
                    regs[k] = rng.choice(list(dom))
            try:
                ref.mem[0x0800:0x2000] = bytes(0x1800)      # all but ROM, cleared per case
                ref.mem[0x4000:0x9000] = bytes(0x5000)
                ref.mem[0xE000:0xF000] = bytes(0x1000)
                strayed.clear()
                ref.zpwrap.clear()
                ref.badbcd.clear()
                res = rig.case(node.addr, name, arc, vram, *regs, pokey)
                if strayed:
                    raise KeyError("read ROM code as data")
                if ref.badbcd:
                    raise KeyError("decimal arithmetic on digits that are not BCD")
                if ref.zpwrap:
                    wraps.update(ref.zpwrap)
                    raise KeyError("zero-page index wrapped")
            except (Halt65, Halt09, IndexError, KeyError, NotImplementedError) as ex:
                skipped += 1
                rig.violations.clear()          # a skipped case's stores are not the next one's
                continue
            except AssertionError as ex:
                fail = ["code overwritten or mis-decoded: %s" % str(ex)[:120]]
                break
            if rig.violations:
                fail = rig.violations[:2]
                rig.violations.clear()
                if trace:
                    trace_case(rig, t, al, name, node.addr, arc, vram, regs, pokey)
                    rig.violations.clear()
                break
            if res[2]:
                fail = res[2][:4]
                if trace:
                    trace_case(rig, t, al, name, node.addr, arc, vram, regs, pokey)
                break
            ok += 1
        results[name] = (node.file, ok, skipped, fail)
        print("  %-8s %-6s %3d ok %3d skipped %s" % (name, node.file, ok, skipped,
                                                     "FAIL %s" % fail if fail else ""), flush=True)
    rig.wraps = wraps
    return results, rig


def trace_case(rig, t, al, name, entry65, arc, vram, regs, pokey):
    """Run one case on both CPUs and print where their source-line paths first part."""
    import re as _re
    ref = rig.ref
    by_addr = {}
    for (f, no), (addr, size) in al.addr_of_line.items():
        if size:
            by_addr[addr] = "%s:%d" % (f, no)
    lst_src = {}
    for line in open(os.path.join(XLAT, "tempest.lst")):
        m = _re.match(r"([0-9A-F]{4}) [0-9A-F]+\s+\(.*?\):\d+ \[.*?\]\s.*?\b(AL[A-Z0-9]+:\d+)", line)
        if m:
            lst_src[int(m.group(1), 16)] = m.group(2)
    p65, p09 = [], []

    def tr65(cpu, pc, mn):
        if pc in by_addr:
            p65.append((by_addr[pc], cpu.a, cpu.x, cpu.y, cpu.p))
    c = rig.cpus[0]
    base = c.cfg["code"]

    def tr09(cpu, pc):
        s = lst_src.get(pc - base)
        if s and (not p09 or p09[-1][0] != s):
            d = c.cfg["data"]
            p09.append((s, cpu.a, cpu.mem[d + 0xB9], cpu.mem[d + 0xBB], cpu.cc))
    ref.trace, c.trace = tr65, tr09
    try:
        res = rig.case(entry65, name, arc, vram, *regs, pokey)
    finally:
        ref.trace = c.trace = None
    # collapse repeats in the 6502 path the same way, and drop lines that emit no 6809 code
    emitted = set(lst_src.values())
    q65 = []
    for x in p65:
        if x[0] in emitted and (not q65 or q65[-1][0] != x[0]):
            q65.append(x)
    i = j = 0
    while i < len(q65) and j < len(p09):
        a, b = q65[i], p09[j]
        if a[0] != b[0]:
            # a line one side runs and the other does not (an RTS dispatch, a folded JMP): resync
            if i + 1 < len(q65) and q65[i + 1][0] == b[0]:
                i += 1
                continue
            if j + 1 < len(p09) and p09[j + 1][0] == a[0]:
                j += 1
                continue
        if a[0] != b[0] or a[1:4] != b[1:4]:
            print("paths part at 6502 step %d:" % i)
            for d in range(-6, 3):
                x = q65[i + d] if 0 <= i + d < len(q65) else ("-", 0, 0, 0, 0)
                y = p09[j + d] if 0 <= j + d < len(p09) else ("-", 0, 0, 0, 0)
                print("  6502 %-12s A=%02X X=%02X Y=%02X P=%02X | 6809 %-12s A=%02X X=%02X Y=%02X CC=%02X" %
                      (x[0], x[1], x[2], x[3], x[4], y[0], y[1], y[2], y[3], y[4]))
            return res
        i += 1
        j += 1
    print("same path for %d steps; results: %s" % (min(len(q65), len(p09)), res[2][:4]))
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="*")
    ap.add_argument("-n", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--fuzz", action="store_true", help="every called routine, random RAM")
    ap.add_argument("--trace", action="store_true", help="on a failure, show where the paths part")
    a = ap.parse_args()
    if a.fuzz:
        ref, mb, pokey = d6pilot.make_ref()
        al = romalign.Aligner().run()
        code, labels = load_module()
        results, rig = fuzz(ref, pokey, al, code, labels, a.n, a.seed, set(a.names) or None,
                            trace=a.trace)
        passed = [k for k, v in results.items() if not v[3] and v[1]]
        print("%d routines: %d pass (%d cases each unless skipped), %d fail, %d never ran" % (
            len(results), len(passed), a.n, sum(1 for v in results.values() if v[3]),
            sum(1 for v in results.values() if not v[3] and not v[1])))
        for k, (f, ok, sk, fail) in sorted(results.items(), key=lambda x: x[1][0]):
            if fail:
                print("  FAIL %-8s %s (%d ok, %d skipped): %s" % (k, f, ok, sk, fail))
        print("zero-page indexed accesses that wrapped on some random input (cases skipped): %s" %
              ", ".join("$%04X" % w for w in sorted(rig.wraps)))
        return
    ref, mb, pokey = d6pilot.make_ref()
    al = romalign.Aligner().run()
    code, labels = load_module()
    rig = d6pilot.Rig(ref, "B", code, labels, os.path.join(XLAT, "tempest.lst"))
    rig.pokey = pokey
    table = routines(mb)
    names = a.names or list(table)
    failed = False
    for name in names:
        gen, before = table[name]
        rng = random.Random(a.seed)
        random.seed(a.seed)
        c65, c09 = [], []
        fail = None
        for arc, vr, ra, rx, ry in gen(rng, a.n):
            if before:
                before()
            x, y, diffs, cfg = rig.case(al.labels[name], name, arc, vr, ra, rx, ry, pokey)
            if diffs:
                fail = diffs[:6]
                break
            c65.append(x)
            c09.append(y)
        if name == "MODSND" and not fail:
            p65, p09, pf = d6pilot.sound_sequence(rig, al.labels["FSNDON"], al.labels["MODSND"], rng, 5000)
            if pf:
                fail = pf
        if fail:
            failed = True
            print("%-8s FAIL after %d cases: %s" % (name, len(c65), fail))
        else:
            print("%-8s %d cases byte-exact; cycles 6502 mean %.0f, 6809 mean %.0f (ratio %.2f)" % (
                name, len(c65), statistics.mean(c65), statistics.mean(c09),
                statistics.mean(c09) / statistics.mean(c65)))
    print("%d instruction cycle counts checked against the listing" % len(rig.checked))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
