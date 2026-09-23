#!/usr/bin/env python3
"""xlattest.py - the differential test on the translated game (plan D6, step 3).

Loads the module m65to09.py built (xlat/tempest.bin), finds each routine by its label, and runs it
against Atari's own routine in the Rev 3 ROM on the same inputs, with d6pilot.py's rig: all of
arcade RAM, vector RAM, the POKEY image and A/X/Y compared, at two code/data layouts.

    xlattest.py                  every routine with a case generator
    xlattest.py MODSND -n 2000   one routine
    xlattest.py --src ...        the same on src/, the hand-finished game (assembled into src/build/)
"""

import argparse
import os
import random
import statistics
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
import d6pilot                                  # noqa: E402
import m65parse                                 # noqa: E402
import romalign                                 # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
XLAT = os.path.join(ROOT, "xlat")
SRC = os.path.join(ROOT, "src")
LST = os.path.join(XLAT, "tempest.lst")      # the listing under test (main() moves it for --src)


def build_src():
    """Assemble src/tempest.a as m65to09.py assembles the draft; return the listing's path."""
    out = os.path.join(SRC, "build")
    os.makedirs(out, exist_ok=True)
    binp, lst = os.path.join(out, "tempest.bin"), os.path.join(out, "tempest.lst")
    r = subprocess.run(["lwasm.orig", "--6809", "--format=raw", "--pragma=nosymbolcase", "-I", SRC,
                        "-o", binp, "--list=" + lst, "--symbols", os.path.join(SRC, "tempest.a")],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit((r.stdout + r.stderr)[:4000] + "\nsrc/ does not assemble")
    return lst


def load_module():
    code = open(LST[:-4] + ".bin", "rb").read()
    labels = {}
    for line in open(LST):
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


def cases_cascal(rng, n):
    """CASCAL's states: the object at or below the well's top (PYL >= $10) or above it, and every
    path of the divide: YDEUNI below and above $80, the divisor PYL-EY near zero on both sides
    (the Math Box's own loop), negative, exactly $8000, over 256 (the bit-at-a-time second step)
    and in play's range, with VGLIST anywhere in vector RAM over a random background."""
    s = d6pilot.syms()
    s.update({k: SYMS[k] for k in ("YDEUNI", "SCFL", "BFACTR", "VGY") if k in SYMS})
    for k in range(n):
        m = d6pilot.rand_arcade(rng)
        kind = k % 8
        py = m[s["PYL"]] = rng.choice([rng.randrange(0x10, 0x100), rng.randrange(0x10, 0x100),
                                       0x10, rng.randrange(0x10)])
        if kind == 0:                                   # play: eye at -HOLEYL, YDEUNI = $10+HOLEYL
            h = rng.choice([0x18, 0x1C, 0x0F, 0x0A, 0x10, 0x0C, 0x14])
            ey, m[s["YDEUNI"]] = -h, 0x10 + h
        elif kind == 1:                                 # the Math Box's loop: |dy| < 64
            ey = py - rng.randrange(-63, 64)
        elif kind == 2:                                 # the wave's start: eye far back
            ey = rng.randrange(-0x600, -0x100)
        elif kind == 3:                                 # dy = $8000 or near the ends
            ey = py - rng.choice([0x8000, 0x7FFF, -0x7FFF, 0x8001])
        elif kind == 4:                                 # behind the eye: dy negative
            ey = py + rng.randrange(1, 0x800)
        else:
            ey = rng.randrange(-0x8000, 0x8000)
        if kind in (1, 3, 5) and rng.random() < 0.3:
            m[s["YDEUNI"]] = rng.randrange(0x80, 0x100)
        ey &= 0xFFFF
        m[s["EYL"]], m[s["EYH"]] = ey & 0xFF, ey >> 8
        va = rng.randrange(0x2000, 0x2FFE)
        m[d6pilot.VGLIST], m[d6pilot.VGLIST + 1] = va & 0xFF, va >> 8
        # a list offset: the game adds it into VGLIST long before it nears $FF, where the draft's
        # folded INY (sta 1,x) and the 6502's wrapped Y part company
        m[s["VGY"]] = rng.choice([0, 0, rng.randrange(0xF0)]) if va + 0xFF < 0x3000 else 0
        vr = bytes(rng.randrange(256) for _ in range(0x1000))
        yield m, vr, rng.randrange(256), rng.randrange(256), rng.randrange(256)


def vram_ptr(rng):
    return rng.randrange(0x2000, 0x2F00)


def cases_pointers(ptrs, regs=(None, None, None)):
    """Random RAM and vector RAM with the named pointers aimed where the game aims them: ptrs maps
    a variable to a function of rng giving its (arcade) value.  regs: A, X, Y ranges or None."""
    def gen(rng, n):
        for _ in range(n):
            m = d6pilot.rand_arcade(rng)
            for sym, vals in DOMAIN.items():
                m[SYMS[m65parse.sym6(sym)]] = rng.choice(vals)
            for var, f in ptrs.items():
                v = f(rng)
                a = SYMS[var]
                m[a], m[a + 1] = v & 0xFF, v >> 8
            vr = bytes(rng.randrange(256) for _ in range(0x1000))
            r = [rng.choice(list(g)) if g is not None else rng.randrange(256) for g in regs]
            yield (m, vr, *r)
    return gen


def bcd(rng, top=100):
    v = rng.randrange(top)
    return (v // 10) << 4 | v % 10


def cases_upscor(rng, n):
    """UPSCOR's states: BCD scores and points, a bonus interval from TBLIFI (ALLANG:289), the
    points from the table (X < 8) or from TEMP0-2, and scores near a 10K boundary so the bonus
    division (ALEXEC:568, a decimal SBC in a loop) runs."""
    for k in range(n):
        m = d6pilot.rand_arcade(rng)
        for sym, vals in DOMAIN.items():
            m[SYMS[m65parse.sym6(sym)]] = rng.choice(vals)
        for base in ("LSCORL", "RSCORL"):
            for i in range(3):
                m[SYMS[base] + i] = bcd(rng)
            if rng.random() < 0.5:
                m[SYMS[base] + 1] = rng.choice([0x99, 0x98, 0x95])     # about to pass 10K
        for t_ in ("TEMP0", "TEMP1", "TEMP2"):
            m[SYMS[t_]] = bcd(rng, rng.choice([10, 100]))
        m[SYMS["BLIFIN"]] = rng.choice([2, 1, 3, 4, 5, 6, 7, 0])
        m[SYMS["LIVES1"]] = rng.randrange(8)
        m[SYMS["LIVES1"] + 1] = rng.randrange(8)
        x = rng.choice([rng.randrange(8), rng.randrange(8, 256)])
        yield m, bytes(0x1000), rng.randrange(256), x, rng.randrange(256)


def cases_prorat(rng, n):
    """PRORAT's states: the seconds count BCD (ALWELG:206, a decimal SBC), the frame count about to
    run out, the rest random."""
    for k in range(n):
        m = d6pilot.rand_arcade(rng)
        for sym, vals in DOMAIN.items():
            m[SYMS[m65parse.sym6(sym)]] = rng.choice(vals)
        m[SYMS["QTMPAU"]] = rng.choice([0, 1, 0x10, 0x09, bcd(rng, 16), bcd(rng)])
        m[SYMS["TIMHIS"]] = rng.choice([0, 0, rng.randrange(256)])
        for var in ("INDYLO", "TEMP3"):                 # pointers, which CONTOUR reloads
            v = vram_ptr(rng)
            m[SYMS[var]], m[SYMS[var] + 1] = v & 0xFF, v >> 8
        yield m, bytes(0x1000), rng.randrange(256), rng.randrange(256), rng.randrange(256)


def cases_moolah(rng, n):
    """MOOLAH's states (COIN65): the switch byte, the mechs' debounce and pulse timers, the coin
    and bonus counts, the coin mode and the counters' pulses, over their real ranges and edges."""
    for k in range(n):
        m = d6pilot.rand_arcade(rng)
        m[SYMS["$COINA"]] = rng.randrange(256)
        for i in range(3):
            m[SYMS["$CNSTT"] + i] = rng.choice([0, 0x1B, 0x1F, 0x3F, 0xFF, rng.randrange(256)])
            m[SYMS["$PSTSL"] + i] = rng.choice([0, 1, 2, 0x78, rng.randrange(256)])
            m[SYMS["$CCTIM"] + i] = rng.choice([0, 1, 0x10, 0x11, 0x20, rng.randrange(256)])
        m[SYMS["$LMTIM"]] = rng.choice([0, 0, 1, 0xF0, rng.randrange(256)])
        m[SYMS["$BCCNT"]] = rng.randrange(16)
        m[SYMS["$CNCT"]] = rng.randrange(8)
        m[SYMS["$BC"]] = rng.randrange(8)
        m[SYMS["$$CRDT"]] = rng.randrange(40)
        yield m, bytes(0x1000), rng.randrange(256), rng.randrange(256), rng.randrange(256)


def coin_sequence(rig, moolah, rng, steps):
    """The coin routine as the game runs it: MOOLAH once an interrupt on the 6502's own state,
    coins dropped on the three mechs (the switch closed for 20-40 ms) and the odd slam, the 6809
    compared at every step."""
    ref = rig.ref
    arc = bytearray(0x800)
    arc[SYMS["$CMODE"]] = rng.randrange(256)
    close = [0, 0, 0]
    for t_ in range(steps):
        sw = 0x08                                   # slam open
        if rng.random() < 0.0005:
            sw = 0
        for i in range(3):
            if close[i] == 0 and rng.random() < 0.004:
                close[i] = rng.randrange(5, 11)     # 4 ms interrupts
            if close[i]:
                close[i] -= 1
                sw |= 1 << (2 - i)
        arc[SYMS["$COINA"]] = sw
        arc[SYMS["$INTCT"]] = t_ & 0xFF
        if t_ % 3000 == 0:
            arc[SYMS["$CMODE"]] = rng.randrange(256)
        c65, c09, diffs, cfg = rig.case(moolah, "MOOLAH", bytes(arc), bytes(0x1000),
                                        rng.randrange(256), rng.randrange(256), rng.randrange(256),
                                        rig.pokey)
        if diffs:
            return [(t_, diffs[:4])]
        arc = bytearray(ref.mem[0:0x800])
    return []


MOOLAH65 = 0xCF24          # ALCOIN's only label (ALEXEC.MAP; the alignment has none inside macros)
ENTRY65 = {"MOOLAH": MOOLAH65}

MSGTABS = (0xD031, 0xD06D, 0xD0A9, 0xD0E5)     # ENGMSG, FREMSG, GERMSG, SPAMSG (ALLANG, Rev 3)


# routine -> (case generator, set-up before each 6502 call, big-endian pointers, little-endian
# pointers).  The pointers are mapped between the arcade's addresses and the port's; with --src
# every routine runs with the code, the data area and window A all away from the arcade's places.
def routines(mb):
    vg = {"VGLIST": vram_ptr}
    return {
        "MODSND": (cases_modsnd_valid, None, (), ()),
        "DSPNYM": (d6pilot.cases_dspnym, None, ("VGLIST",), ()),
        "WORSCR": (d6pilot.cases_worscr, inimat_then(mb), (), ()),              # by hand
        "CASCAL": (cases_cascal, inimat_then(mb), ("VGLIST",), ()),             # by hand
        # reloc.a's users (src/ only)
        "SBCLOG": (cases_pointers(vg, (range(9), None, None)), inimat_then(mb), ("VGLIST",), ()),
        "SBCACT": (cases_pointers({"INDYLO": vram_ptr}, (range(9), None, None)), inimat_then(mb),
                   ("INDYLO",), ()),
        "SBCSWI": (cases_pointers({"VGLIST": vram_ptr, "INDYLO": vram_ptr}, (range(9), None, None)),
                   inimat_then(mb), ("VGLIST", "INDYLO"), ()),
        "BIGTEX": (cases_pointers(vg), inimat_then(mb), ("VGLIST",), ()),
        "DSBOOM": (cases_pointers({"VGLIST": vram_ptr, "SVGLIS": vram_ptr}), inimat_then(mb), ("VGLIST",),
                   ("SVGLIS",)),
        "CONTOU": (cases_pointers({"INDYLO": vram_ptr, "TEMP3": vram_ptr}), inimat_then(mb),
                   ("INDYLO", "TEMP3"), ()),
        "INILIT": (cases_pointers({"LITRAL": lambda r: r.choice(MSGTABS)}), inimat_then(mb), ("LITRAL",), ()),
        "MSGS": (cases_pointers({"LITRAL": lambda r: r.choice(MSGTABS), "VGLIST": vram_ptr,
                                 "INDYLO": vram_ptr, "SECUVG": vram_ptr},
                                (None, range(0, 60, 2), None)), inimat_then(mb),
                 ("LITRAL", "VGLIST", "INDYLO", "SECUVG"), ()),
        "UPSCLI": (cases_pointers({"VGLIST": vram_ptr, "INDYLO": vram_ptr},
                                  (range(2), None, range(2))), inimat_then(mb),
                   ("VGLIST", "INDYLO"), ()),          # A = scale, Y = player (INFO's calls)
        # the flag and decimal sites (src/ only)
        "UPSCOR": (cases_upscor, inimat_then(mb), (), ()),
        "PRORAT": (cases_prorat, inimat_then(mb), ("INDYLO", "TEMP3"), ()),   # falls into CONTOUR
        "ENDGAM": (cases_pointers({}), inimat_then(mb), (), ()),
        "LINER": (cases_pointers({}), inimat_then(mb), (), ()),
        "MAYBLR": (cases_pointers({}), inimat_then(mb), (), ()),
        "MOOLAH": (cases_moolah, None, (), ()),                                  # by hand
        "INFO": (cases_pointers({"LITRAL": lambda r: r.choice(MSGTABS), "VGLIST": vram_ptr,
                                 "INDYLO": vram_ptr, "SECUVG": vram_ptr}), inimat_then(mb),
                 ("LITRAL", "VGLIST", "INDYLO", "SECUVG"), ()),
    }


# Registers a routine leaves holding a byte of an address, which differ once the data moves:
# BIGTEX's A (VGLIST's high byte), DSBOOM's A and Y (SWAPVG's).
ADDR_REGS = {"BIGTEX": "A", "DSBOOM": "AY"}

RELOC_USERS = ("SBCLOG", "SBCACT", "SBCSWI", "BIGTEX", "DSBOOM", "CONTOU", "INILIT", "MSGS",
               "UPSCLI", "INFO")
HAND_ONLY = ("WORSCR", "CASCAL", "MOOLAH", "UPSCOR", "PRORAT", "ENDGAM", "LINER", "MAYBLR") + RELOC_USERS


# Variables whose values the game keeps in a small range; the fuzz respects them.
DOMAIN = {"PLAYUP": (0, 1), "NUMPLA": (0, 1),
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
              "NEWTY2": (range(5), None, None), "NEWTYP": (None, range(5), None),
              "UPSCLI": (range(2), None, range(2))}       # scale, player (INFO's calls)   # NYMTAD


class Mapper:
    """Arcade addresses to one layout's port addresses and back: RAM into the data area, vector RAM
    into window A, the tables reloc.a copies into their copies, vector ROM and the rest of the ROM
    (where the module holds the ROM's bytes, as in data) into the module."""

    def __init__(self, cfg, codelen, labels, al, code=None, rom=None):
        self.cfg, self.codelen = cfg, codelen
        self.tables = []                    # (ROM address, length, data-area offset)
        if "RELINI" in labels:
            for lab, ln, dst in (("BUFASL", 54, "R.BUF"), ("LNGTAB", 8, "R.LNG"),
                                 ("WTABLE", 112, "R.WTAB")):
                self.tables.append((al.labels[lab], ln, labels[dst]))
            self.tables.append((0xD031, 240, labels["R.MSG"]))     # ENGMSG..SPAMSG
        self.vrom = labels.get("VROM")
        pairs = sorted((al.labels[n], labels[n]) for n in al.labels
                       if n in labels and 0x9000 <= al.labels[n] < 0xE000)
        if "MSGLBS" in labels:          # ALLANG's messages: 1:1 from MSGLBS ($D121) to LNGTAB
            pairs = sorted(pairs + [(0xD121, labels["MSGLBS"])])
        if code is not None:
            # only where the module holds the ROM's bytes (data), so the mapping has an inverse
            pairs = [(r, m) for r, m in pairs if code[m:m + 2] == bytes(rom[r:r + 2])]
        self.code, self.rom = code, rom
        self.rom2mod = pairs
        self.mod2rom = sorted((m, r) for r, m in pairs)

    def to_port(self, v):
        d, w, c = self.cfg["data"], self.cfg["window"], self.cfg["code"]
        if v < 0x800:
            return (v + d) & 0xFFFF
        if 0x2000 <= v < 0x3000:
            return (v - 0x2000 + w) & 0xFFFF
        if 0x3000 <= v < 0x4000 and self.vrom is not None:
            return c + self.vrom + v - 0x3000
        for r, ln, off in self.tables:
            if r <= v < r + ln:
                return d + off + v - r
        if 0x9000 <= v < 0xE000:
            best = None
            for r, m in self.rom2mod:
                if r > v:
                    break
                best = (r, m)
            if best and (self.code is None or
                         self.code[best[1] + v - best[0]:best[1] + v - best[0] + 1] == bytes(self.rom[v:v + 1])
                         and all(self.code[best[1] + i] == self.rom[best[0] + i] for i in range(v - best[0]))):
                return c + best[1] + v - best[0]
        return v

    def to_arcade(self, p):
        d, w, c = self.cfg["data"], self.cfg["window"], self.cfg["code"]
        if d <= p < d + 0x800:
            return p - d
        if w <= p < w + 0x1000:
            return p - w + 0x2000
        for r, ln, off in self.tables:
            if d + off <= p < d + off + ln:
                return r + p - d - off
        if self.vrom is not None and c + self.vrom <= p < c + self.vrom + 0x1000:
            return 0x3000 + p - c - self.vrom
        if c <= p < c + self.codelen:
            best = None
            for m, r in self.mod2rom:
                if c + m > p:
                    break
                best = (m, r)
            if best and (self.code is None or all(self.code[best[0] + i] == self.rom[best[1] + i]
                                                   for i in range(p - c - best[0] + 1))):
                return best[1] + p - c - best[0]
        return p


class XRig(d6pilot.Rig):
    """The pilot's rig with the named pointers mapped (not just VGLIST), memory and the hardware
    shadows cleared per case, and reloc.a's tables in place (RELINI run once per layout)."""

    # For the fuzz, arcade and port addresses coincide (data area at $0000, window at $2000), so a
    # pointer's value needs no relocation, only its bytes swapped: TEMP3/TEMP4 is a pointer in one
    # routine and two scalars in another, and relocating "pointer values" would corrupt the
    # scalars.  The module still runs at two code addresses.
    LAYOUTS = [dict(code=0x8000, data=0x0000, window=0x2000),
               dict(code=0x8123, data=0x0000, window=0x2000)]    # the module is ~28K: it must fit
    # For the named tests, where each routine's pointers are known: everything moved.
    REL_LAYOUTS = [dict(code=0x8000, data=0x1000, window=0x4000),
                   dict(code=0x8321, data=0x5300, window=0x6000)]

    def __init__(self, *args, pointers=(), le_pointers=(), swapped=(), layouts=None, al=None,
                 addr_regs="", soft=(), **kw):
        code = args[2]
        layouts = layouts or self.LAYOUTS
        for cfg in layouts:
            if cfg["code"] + len(code) > 0xFE00:
                raise ValueError("module does not fit at $%04X" % cfg["code"])
        saved = d6pilot.CONFIGS[:]
        d6pilot.CONFIGS[:] = layouts
        try:
            super().__init__(*args, **kw)
        finally:
            d6pilot.CONFIGS[:] = saved
        self.ptrs = sorted(pointers)
        self.le_ptrs = sorted(le_pointers)
        # the other big-endian pointer variables: their bytes swapped, their values left alone
        self.swapped = sorted(set(swapped) - set(pointers))
        self.addr_regs = addr_regs          # registers left holding an address byte: not compared
        # swapped pointers that may end holding a module address where the 6502's holds the ROM's:
        # equal, or equal once mapped back (recorded states)
        self.soft = sorted(soft)
        self.hw = {}                        # arcade hardware address -> value its shadow holds
        # RANDOM and RANDO2: the port's generator (hw.a), read for read on both CPUs
        self.frozen = []
        if al is not None and "RNDST" in self.labels:
            for name in ("ZPOKST", "ZPONTS"):       # neutralised: they read a frozen POKEY
                if name in al.labels:
                    self.frozen.append((al.labels[name], al.labels[name] + 40))
            if not getattr(self.ref, "rnd_hooked", False):
                self.ref.rnd_hooked = True
                for a_ in (0x60CA, 0x60DA):
                    self.ref.io.insert(0, (a_, a_, lambda a: XRig.rnd_rig.rnd_read(), None))
        self.relsnap = {}
        for c in self.cpus:
            c.mapper = Mapper(c.cfg, len(code), self.labels, al, code, self.ref.mem) if al else None
        self.violations = []
        for c in self.cpus:
            lo = c.cfg["code"]
            hi = lo + len(self.code) - 1

            def guard(a, v, c=c):
                self.violations.append("store to its own code at $%04X (offset $%04X) from pc $%04X"
                                       % (a, a - c.cfg["code"], c.pc - c.cfg["code"]))
            c.map_io(lo, hi, None, guard)

    rnd_rig = None

    def rnd_read(self):
        pc = self.ref.opc
        if any(lo <= pc < hi for lo, hi in self.frozen):
            return 0
        self.rnd = rnd_step(self.rnd)
        return self.rnd & 0xFF

    def case(self, *args, **kw):
        XRig.rnd_rig = self
        self.seed = self.rnd = random.randrange(1, 0x10000)
        self.rnd_end = {}
        r = super().case(*args, skip_regs=self.addr_regs, accept=self.accept if self.soft else None,
                         **kw)
        if "RNDST" in self.labels and not r[2]:
            for c in self.cpus:
                if self.rnd_end.get(id(c), self.rnd) != self.rnd:
                    return r[0], None, ["RANDOM: the two generators end in different states"], c.cfg
        return r

    def accept(self, c, i, want):
        d = c.cfg["data"]
        for p in self.soft:
            if i in (p, p + 1) and c.mapper:
                pv = c.mem[d + p] << 8 | c.mem[d + p + 1]
                v = c.mapper.to_arcade(pv)
                if (v & 0xFF, v >> 8) == (want[p], want[p + 1]):
                    return True
                # half a pointer: its page left over, a scalar since stored in its low byte
                # (TEMP4 after CONTOUR): the port's page must map to the 6502's
                return (i == p + 1 and (pv & 0xFF) == want[p] and
                        any(c.mapper.to_arcade(pv & 0xFF00 | lo) >> 8 == want[p + 1] and
                            c.mapper.to_arcade(pv & 0xFF00 | lo) != pv & 0xFF00 | lo for lo in range(256)))
        return False

    def relocated(self, c):
        """reloc.a's tables for this layout: RELINI run once, its output kept."""
        cfg = c.cfg
        if id(c) not in self.relsnap:
            d, w = cfg["data"], cfg["window"]
            lo, hi = self.labels["RELTAB"], self.labels["RELEND"]
            c.mem[0:0x10000] = bytes(0x10000)
            c.mem[cfg["code"]:cfg["code"] + len(self.code)] = self.code
            c.mem[d + 0x810], c.mem[d + 0x811] = w >> 8, w & 0xFF
            c.u, c.dp, c.s = d, d >> 8, d6pilot.STACK
            c.call(cfg["code"] + self.labels["RELINI"])
            self.relsnap[id(c)] = bytes(c.mem[d + lo:d + hi])
            c.static.clear()
        return self.relsnap[id(c)]

    def run6809(self, c, entry, arcade, vram, a, x, y):
        cfg = c.cfg
        d, w = cfg["data"], cfg["window"]
        if c.mapper:
            to_port, to_arcade = c.mapper.to_port, c.mapper.to_arcade
        else:
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
        rel = self.relocated(c) if "RELINI" in self.labels else None
        c.mem[0:0x10000] = bytes(0x10000)           # nothing left over from the last case
        c.mem[cfg["code"]:cfg["code"] + len(self.code)] = self.code
        c.static.clear()
        c.mem[d:d + 0x800] = arcade
        c.mem[d + 0x800:d + 0xA00] = bytes(0x200)
        if "RNDST" in self.labels:
            r_ = d + self.labels["RNDST"]
            c.mem[r_], c.mem[r_ + 1] = self.seed >> 8, self.seed & 0xFF
        if rel is not None:
            lo = self.labels["RELTAB"]
            c.mem[d + lo:d + lo + len(rel)] = rel
        c.mem[w:w + 0x1000] = vram
        given = {}
        for p in self.ptrs:
            v = to_port(arcade[p] | arcade[p + 1] << 8)
            c.mem[d + p], c.mem[d + p + 1] = v >> 8, v & 0xFF
            given[p] = v
        for p in self.le_ptrs:
            v = to_port(arcade[p] | arcade[p + 1] << 8)
            c.mem[d + p], c.mem[d + p + 1] = v & 0xFF, v >> 8
            given[p] = v
        for p in self.swapped:
            c.mem[d + p], c.mem[d + p + 1] = arcade[p + 1], arcade[p]
        c.mem[d + 0x810], c.mem[d + 0x811] = w >> 8, w & 0xFF        # VWIN: window A
        for a_, v_ in self.hw.items():
            if "HW_%04X" % a_ in self.labels:
                c.mem[d + self.labels["HW_%04X" % a_]] = v_
        c.mem[d + 0xB8] = c.mem[d + 0xBA] = d >> 8
        c.mem[d + 0xB9] = x
        c.mem[d + 0xBB] = y
        c.a, c.b = a, random.randrange(256)
        c.x = c.y = random.randrange(0x10000)
        c.u, c.dp, c.s = d, d >> 8, d6pilot.STACK
        c.cc = 0x50
        cyc = c.call(cfg["code"] + self.labels[entry], limit=2_000_000)
        if "RNDST" in self.labels:
            r_ = d + self.labels["RNDST"]
            self.rnd_end[id(c)] = c.mem[r_] << 8 | c.mem[r_ + 1]
        out = bytearray(c.mem[d:d + 0x800])
        # a pointer left as it was given compares as the arcade value it came from
        for p in self.ptrs:
            pv = c.mem[d + p] << 8 | c.mem[d + p + 1]
            v = arcade[p] | arcade[p + 1] << 8 if pv == given[p] else to_arcade(pv)
            out[p], out[p + 1] = v & 0xFF, v >> 8
        for p in self.le_ptrs:
            pv = c.mem[d + p] | c.mem[d + p + 1] << 8
            v = arcade[p] | arcade[p + 1] << 8 if pv == given[p] else to_arcade(pv)
            out[p], out[p + 1] = v & 0xFF, v >> 8
        for p in self.swapped:
            out[p], out[p + 1] = c.mem[d + p + 1], c.mem[d + p]
        return cyc, out, bytes(c.mem[w:w + 0x1000]), bytes(c.mem[d + 0x800:d + 0x810]), \
            (c.a, c.mem[d + 0xB9], c.mem[d + 0xBB])


SYMS = {}


def rnd_step(x):
    """hw.a's RANDOM generator: xorshift16 (7, 9, 8)."""
    x ^= (x << 7) & 0xFFFF
    x ^= x >> 9
    x ^= (x << 8) & 0xFFFF
    return x


def reloc_split(al, labels):
    """The ROM tables reloc.a replaces in the module (none in the draft)."""
    if "RELINI" not in labels:
        return ()
    return ((al.labels["BUFASL"], 54), (al.labels["LNGTAB"], 8), (0xD031, 240),
            (al.labels["WTABLE"], 112))


def domain_checks(ref, t, pokey, mb=None, rom_ptrs_ok=False, split=()):
    """The rules for "a case the game cannot produce", installed on the 6502: each such access
    appends to the list returned, and a case that leaves it non-empty is skipped, not compared.
    mb: the Math Box is modelled (src/, where WORSCR and CASCAL are done by hand).  rom_ptrs_ok: a
    read of ROM data through a pointer is in the domain (src/'s named tests, whose pointers come
    from reloc.a's tables or are mapped; in the fuzz a random pointer can land anywhere).
    split: (ROM address, length) of tables the port no longer holds as the ROM's bytes (reloc.a's):
    each is a stretch of its own, which an index may not carry a read into."""
    cur = {"mode": None, "base": None, "ywrap": False}

    class Strayed(list):
        def clear(self):                    # a new case: no Y wrap carried over
            super().clear()
            cur["ywrap"] = False
    strayed = Strayed()
    # the ROM must not be written through a random pointer
    ref.map_io(0x9000, 0xFFFF, None, lambda a, v: None)
    ref.map_io(0x3000, 0x3FFF, None, lambda a, v: None)
    # A data read of ROM code means the input was outside what the game can produce (an index past
    # a table's end): such a case is skipped, not compared.  Instruction fetches do not go through
    # rd(), so only data reads are seen.
    data_bytes = set()
    for node in t.nodes:
        if node.kind == "data" and node.addr is not None and node.size:
            data_bytes.update(range(node.addr, node.addr + node.size))
    # contiguous stretches of ROM data: the port keeps each one whole, but not what lies between
    run_of = {}
    run = 0
    data_bytes.update(range(0xCFD9, 0xCFE1))   # COIN65's bonus-adder table, amid its code (MOOLAH)
    starts = {r for r, ln in split} | {r + ln for r, ln in split}
    for a_ in range(0x9000, 0xE000):
        if a_ in data_bytes:
            if a_ - 1 not in data_bytes or a_ in starts:
                run += 1
            run_of[a_] = run

    def base_run(base):
        for r, ln in split:                 # WTABLE-3 .. WTABLE-1 are CONTOUR's bases (ALWELG:427)
            if r - 3 <= base < r:
                return run_of.get(r)
        return run_of.get(base)

    def rom_read(a):
        if cur.get("mode") in ("izy", "izx") and not (rom_ptrs_ok and a in data_bytes):
            strayed.append(a)               # a pointer into ROM: only src/ relocates them (reloc.a)
        elif a not in data_bytes:
            strayed.append(a)               # code read as data
        elif cur.get("base") is not None and base_run(cur["base"]) != run_of.get(a):
            strayed.append(a)               # an index carried the read out of its table's stretch
        return ref.mem[a]
    ref.map_io(0x9000, 0xDFFF, rom_read, None)

    def mirror_read(a):
        strayed.append(a)                   # the top ROM's mirror ($F000-$FFFF): the game reads
        return ref.mem[a]                   # no data there (only the CPU's vectors)
    ref.io.insert(0, (0xF000, 0xFFFF, mirror_read, None))

    def vrom_read(a):
        if cur.get("mode") in ("izy", "izx"):
            strayed.append(a)               # likewise a pointer into vector ROM
        return ref.mem[a]
    ref.io.insert(0, (0x3000, 0x3FFF, vrom_read, None))

    def elsewhere(a, v=None):
        if cur.get("mode") in ("izy", "izx"):
            strayed.append(a)               # a pointer outside RAM and vector RAM
        elif cur.get("base") is not None and cur["base"] < 0x800:
            strayed.append(a)               # an index carried a RAM table's access past RAM
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
        # The translator folds INYs into the next (zp),Y access's offset (sta 1,x), which a wrap
        # of Y ($FF to 0) would part from the 6502's.  Y does wrap in the game, but in all 2,417
        # recorded frames no (zp),Y access follows the wrap before Y is loaded again
        # (docs/status.md, "D6 hand work"): one that does is outside the domain.
        if mn == "INY" and cpu.y == 0xFF:
            cur["ywrap"] = True
        elif mn in ("LDY", "TAY") or (mn == "DEY" and cpu.y == 0):
            cur["ywrap"] = False
        elif mode == "izy" and cur.get("ywrap"):
            strayed.append(pc)
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

    # The Math Box is replaced by hand (WORSCR and CASCAL on the coprocessor, src/ only): in the
    # draft a case that reads a Math Box result is outside what the mechanical translation does.
    def mathbox_read(a):
        strayed.append(a)
        return 0
    if mb is None:
        for a_ in (0x6040, 0x6060, 0x6070):
            ref.io.insert(0, (a_, a_, mathbox_read, None))
    return strayed


def fuzz(ref, pokey, al, code, labels, n, seed, only=None, trace=False, mb=None):
    """Every routine a JSR reaches, on random RAM with the pointers aimed at vector RAM."""
    import m65to09
    from cpu6502 import Halt as Halt65
    from cpu6809 import Halt as Halt09
    t = m65to09.Translator()
    SYMS.update(al.parsers["ALWELG"].syms)
    # pointers: swapped (the layouts put RAM and vector RAM at the arcade's places) and compared
    # as equal or equal once mapped back (a pointer left on a reloc.a copy or in the module)
    rig = XRig(ref, "B", code, labels, LST, swapped=list(t.pointers), soft=list(t.pointers),
               al=al if "RELINI" in labels else None)
    rig.pokey = pokey
    strayed = domain_checks(ref, t, pokey, mb, split=reloc_split(al, labels))
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
            if mb is not None:
                d6pilot.inimat(mb)                          # as INIMAT leaves it for the game
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


def load_states(path):
    """tools/avgcap.lua's AVGCAP_RAM records: (game frame, 2K of RAM, 4K of vector RAM)."""
    d = open(path, "rb").read()
    rec = 8 + 0x800 + 0x1000 + 8
    out = []
    for k in range(len(d) // rec):
        r = d[k * rec:(k + 1) * rec]
        assert r[:4] == b"RAMG", "not an AVGCAP_RAM file (or one from before the switches)"
        sw = dict(zip(SWITCHES, r[0x1808:0x180D]))
        out.append((int.from_bytes(r[4:8], "big"), bytes(r[8:0x808]), bytes(r[0x808:0x1808]), sw))
    return out


SWITCHES = (0x0C00, 0x0D00, 0x0E00, 0x60C8, 0x60D8)     # as avgcap.lua records them


FRAME = ("EXSTAT", "NONSTA", "DISPLA")      # MAINLN's game frame (ALEXEC:52-54)


def states_test(paths, every, limit, ref, mb, pokey, al, code, labels, trace=False):
    """Whole game frames from MAME's own states: for each recorded frame start, MAINLN's three
    calls in turn on both CPUs, each from the 6502's result of the last, everything compared after
    each.  The data area and window A sit at the arcade's places (the named tests move them); the
    module runs at two addresses, and the pointers into ROM (LITRAL, TEMP3, ...) are mapped."""
    import m65to09
    t = m65to09.Translator()
    litral = SYMS["LITRAL"]
    others = [p for p in t.pointers if p != litral]
    rig = XRig(ref, "B", code, labels, LST, pointers=[litral], swapped=others, soft=others,
               layouts=XRig.LAYOUTS, al=al)
    rig.pokey = pokey
    frames = cyc65 = cyc09 = selftest = 0
    qs, qd = SYMS["QSTATE"], SYMS["QDSTAT"]

    def dropped(ram):               # the self-test the port drops: CSYSTM, CDSYST (ALCOMN:63, 68)
        return ram[qs] == 0x22 or ram[qd] == 0x02
    for path in paths:
        states = load_states(path)[::every][:limit]
        print("%s: %d states" % (os.path.basename(path), len(states)), flush=True)
        for gframe, ram, vram, sw in states:
            rig.hw = sw
            arc, vr, regs = ram, vram, (0, 0, 0)
            if dropped(arc):
                selftest += 1
                continue
            for entry in FRAME:
                d6pilot.inimat(mb)
                ref.mem[0x0800:0x2000] = bytes(0x1800)      # the other hardware reads as 0 on both
                ref.mem[0x4000:0x9000] = bytes(0x5000)
                for a_, v_ in sw.items():                   # the switches as MAME read them
                    ref.mem[a_] = v_
                c65, c09, diffs, cfg = rig.case(al.labels[entry], entry, arc, vr, *regs, pokey)
                if diffs:
                    print("  game frame %d (QSTATE %02X, QDSTATE %02X), %s: FAIL %s" % (
                        gframe, arc[SYMS["QSTATE"]], arc[SYMS["QDSTAT"]], entry, diffs[:6]))
                    if trace:
                        trace_case(rig, t, al, entry, al.labels[entry], arc, vr, list(regs), pokey,
                                   lines_only=True)
                    return False
                cyc65 += c65
                cyc09 += c09
                arc, vr = bytes(ref.mem[0:0x800]), bytes(ref.mem[0x2000:0x3000])
                regs = (ref.a, ref.x, ref.y)
                if dropped(arc):
                    break
            else:
                frames += 1
                continue
            selftest += 1
    print("%d game frames byte-exact after each of %s; 6502 cycles a frame %.0f, 6809 %.0f "
          "(ratio %.2f); %d in the dropped self-test, not run" % (
              frames, ", ".join(FRAME), cyc65 / max(frames, 1), cyc09 / max(frames, 1),
              cyc09 / max(cyc65, 1), selftest))
    return True


def trace_case(rig, t, al, name, entry65, arc, vram, regs, pokey, lines_only=False):
    """Run one case on both CPUs and print where their source-line paths first part."""
    import re as _re
    ref = rig.ref
    by_addr = {}
    for (f, no), (addr, size) in al.addr_of_line.items():
        if size:
            by_addr[addr] = "%s:%d" % (f, no)
    lst_src = {}
    for line in open(LST):
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
        if a[0] != b[0] or (a[1:4] != b[1:4] and not lines_only):
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
    ap.add_argument("--src", action="store_true", help="test src/ (hand-finished) instead of xlat/")
    ap.add_argument("--states", nargs="+", metavar="FILE",
                    help="whole game frames from avgcap.lua AVGCAP_RAM captures (with --src)")
    ap.add_argument("--every", type=int, default=1, help="with --states: every n-th state")
    ap.add_argument("--limit", type=int, default=1 << 30, help="with --states: at most n a file")
    a = ap.parse_args()
    global LST
    if a.src:
        LST = build_src()
    if a.states:
        ref, mb, pokey = d6pilot.make_ref()
        al = romalign.Aligner().run()
        for f in ("ALDIS2", "ALSCO2", "ALWELG", "ALLANG", "ALEXEC"):
            SYMS.update(al.parsers[f].syms)
        code, labels = load_module()
        ok = states_test(a.states, a.every, a.limit, ref, mb, pokey, al, code, labels, a.trace)
        sys.exit(0 if ok else 1)
    if a.fuzz:
        ref, mb, pokey = d6pilot.make_ref()
        al = romalign.Aligner().run()
        code, labels = load_module()
        results, rig = fuzz(ref, pokey, al, code, labels, a.n, a.seed, set(a.names) or None,
                            trace=a.trace, mb=mb if a.src else None)
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
    table = routines(mb)
    names = a.names or [k for k in table if a.src or k not in HAND_ONLY]
    for f in ("ALDIS2", "ALSCO2", "ALWELG", "ALLANG"):
        SYMS.update(al.parsers[f].syms)
    failed = False
    checked = set()
    strayed = None
    if a.src:
        import m65to09
        tr = m65to09.Translator()
        allptrs = list(tr.pointers)
        strayed = domain_checks(ref, tr, pokey, mb, rom_ptrs_ok=True, split=reloc_split(al, labels))
    for name in names:
        gen, before, be, le = table[name]
        if a.src:
            rig = XRig(ref, "B", code, labels, LST, pointers=[SYMS[p] for p in be],
                       le_pointers=[SYMS[p] for p in le], swapped=allptrs,
                       layouts=XRig.REL_LAYOUTS, al=al, addr_regs=ADDR_REGS.get(name, ""))
        else:
            rig = d6pilot.Rig(ref, "B", code, labels, LST)
        rig.pokey = pokey
        rng = random.Random(a.seed)
        random.seed(a.seed)
        c65, c09 = [], []
        fail = None
        skipped = 0
        for arc, vr, ra, rx, ry in gen(rng, a.n):
            if before:
                before()
            ref.badbcd.clear()
            if strayed is not None:
                strayed.clear()
            x, y, diffs, cfg = rig.case(ENTRY65.get(name) or al.labels[name], name, arc, vr, ra, rx, ry,
                                        pokey)
            if ref.badbcd or strayed:       # as in the fuzz: outside what the game produces
                skipped += 1
                continue
            if diffs:
                fail = diffs[:6]
                break
            c65.append(x)
            c09.append(y)
        if name == "MOOLAH" and not fail:
            fail = coin_sequence(rig, MOOLAH65, rng, 20000)
            if not fail:
                print("MOOLAH   20000 interrupts of coins dropped, byte-exact at every one")
        if name == "MODSND" and not fail:
            p65, p09, pf = d6pilot.sound_sequence(rig, al.labels["FSNDON"], al.labels["MODSND"], rng, 5000)
            if pf:
                fail = pf
        checked |= rig.checked
        if fail:
            failed = True
            print("%-8s FAIL after %d cases: %s" % (name, len(c65), fail))
        elif not c65:
            failed = True
            print("%-8s no case in the domain (%d skipped)" % (name, skipped))
        else:
            print("%-8s %d cases byte-exact%s; cycles 6502 mean %.0f, 6809 mean %.0f (ratio %.2f)" % (
                name, len(c65), " (%d out of domain, skipped)" % skipped if skipped else "",
                statistics.mean(c65), statistics.mean(c09), statistics.mean(c09) / statistics.mean(c65)))
    print("%d instruction cycle counts checked against the listing" % len(checked))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
