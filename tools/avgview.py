#!/usr/bin/env python3
"""avgview.py - the host AVG interpreter for the Tempest port (plan stage 0).

Reads an avgcap.lua capture (vector ROM, then per-frame vector RAM + colour RAM), runs Atari's
display list through a LITERAL PORT of MAME's Tempest AVG (devices/video/avgdvg.cpp: the
state-PROM-driven machine, avg_device handlers 0-5 and avg_tempest_device handlers 6-7), maps the
beam onto the F256's 320x240 bitmap exactly as the 6809 interpreter will, and reports:

  - per frame: vectors the AVG drew, visible ones (intensity > 0), the line records the port would
    send after clipping, and the pixels the line engine would enqueue;
  - optionally a PNG of chosen frames, drawn with the same Bresenham and CLUT rule
    (index = colour*16 + intensity) the port uses.

This is the executable specification of the 6809 interpreter (plan section 1, seam 1): when the
two disagree, this one is checked against MAME, and the 6809 one against this.

Usage:
  avgview.py CAPTURE [--prom 136002-125.d7] [--stats] [--png DIR --frames 60,600,...]
"""

import argparse
import os
import struct
import sys

ROMS = os.path.join(os.path.dirname(__file__), "..", "tempest_orig", "notebooks", "roms", "tempest")

# MAME's Tempest screen (tempest.cpp): visible area 0..580 x 0..570, ROT270.
VIS_W, VIS_H = 580, 570
XCENTER = (VIS_W // 2) << 16
YCENTER = (VIS_H // 2) << 16

# The F256 bitmap.
BM_W, BM_H = 320, 240


def read_capture(path):
    """Yield ('rom', bytes) once, then ('frame', number, vram, cram) per record."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"AVGR":
        sys.exit("not an avgcap file")
    rom = data[4:4 + 4096]
    yield ("rom", rom)
    i = 4 + 4096
    rec = 4 + 4 + 4096 + 16
    while i + rec <= len(data):
        if data[i:i + 4] != b"AVGF":
            sys.exit("bad record at %d" % i)
        n = struct.unpack(">I", data[i + 4:i + 8])[0]
        vram = data[i + 8:i + 8 + 4096]
        cram = data[i + 8 + 4096:i + rec]
        yield ("frame", n, vram, cram)
        i += rec


class TempestAVG:
    """MAME's avg_tempest_device, one frame at a time.  Field names follow MAME's (m_ dropped)."""

    MAXSTEPS = 200000

    def __init__(self, prom):
        self.prom = prom

    def run(self, vram, rom, cram):
        """Execute from PC 0 until the list jumps back to 0 (the frame boundary MAME uses for
        Tempest) or halts.  Returns the beam points: (x, y, colour_index, intensity 0-15)."""
        mem = vram + rom                      # VG space: $0000 vector RAM, $1000 vector ROM
        self.pc = 0
        self.sp = 0
        self.stack = [0, 0, 0, 0]
        self.state_latch = 0
        self.op = 0
        self.data = 0
        self.dvy = self.dvx = self.dvy12 = 0
        self.int_latch = 0
        self.timer = 0
        self.scale = 0
        self.bin_scale = 0
        self.color = 0
        self.intensity = 0
        self.xpos, self.ypos = XCENTER, YCENTER
        self.halt = 0
        self.points = []
        self.done = False
        self.cram = cram
        steps = 0
        while not self.done and steps < self.MAXSTEPS:
            steps += 1
            addr = (((self.state_latch >> 4) ^ 1) << 7) | (self.op << 4) | (self.state_latch & 0xF)
            self.state_latch = (self.state_latch & 0x10) | (self.prom[addr] & 0xF)
            if self.state_latch & 0x08:
                self.data = mem[(self.pc ^ 1) & 0x1FFF]
                getattr(self, "h%d" % (self.state_latch & 7))()
            self.state_latch = (self.halt << 4) | (self.state_latch & 0xF)
            if self.halt:
                break
        return self.points

    def OP(self, b):
        return (self.op >> b) & 1

    def h0(self):
        self.dvy = (self.dvy & 0x1F00) | self.data
        self.pc += 1

    def h1(self):
        self.dvy12 = (self.data >> 4) & 1
        self.op = self.data >> 5
        self.int_latch = 0
        self.dvy = (self.dvy12 << 12) | ((self.data & 0xF) << 8)
        self.dvx = 0
        self.pc += 1

    def h2(self):
        self.dvx = (self.dvx & 0x1F00) | self.data
        self.pc += 1

    def h3(self):
        self.int_latch = self.data >> 4
        self.dvx = ((self.int_latch & 1) << 12) | ((self.data & 0xF) << 8) | (self.dvx & 0xFF)
        self.pc += 1

    def h4(self):
        if self.OP(0):
            self.stack[self.sp & 3] = self.pc
        else:
            i = 0
            while (((self.dvy ^ (self.dvy << 1)) & 0x1000) == 0
                   and ((self.dvx ^ (self.dvx << 1)) & 0x1000) == 0):
                if i >= 16:
                    break
                i += 1
                self.dvy = (self.dvy & 0x1000) | ((self.dvy << 1) & 0x1FFF)
                self.dvx = (self.dvx & 0x1000) | ((self.dvx << 1) & 0x1FFF)
                self.timer >>= 1
                self.timer |= 0x4000 | (self.OP(1) << 7)
            if self.OP(1):
                self.timer &= 0xFF

    def h5(self):
        if not self.OP(2):
            for _ in range(self.bin_scale):
                self.timer >>= 1
                self.timer |= 0x4000 | (self.OP(1) << 7)
            if self.OP(1):
                self.timer &= 0xFF
        if self.OP(2):
            self.sp = (self.sp - 1) & 0xF if self.OP(1) else (self.sp + 1) & 0xF

    def h6(self):
        # avg_tempest_device::handler_6
        if not self.OP(2) and not self.dvy12:
            if self.dvy & 0x800:
                self.color = self.dvy & 0xF
            else:
                self.intensity = (self.dvy >> 4) & 0xF
        # avg_common_strobe2
        if self.OP(2):
            if self.OP(0):
                self.pc = self.dvy << 1
                if self.dvy == 0:
                    self.done = True          # jump to 0: the end of one pass
            else:
                self.pc = self.stack[self.sp & 3]
        else:
            if self.dvy12:
                self.scale = self.dvy & 0xFF
                self.bin_scale = (self.dvy >> 8) & 7

    def h7(self):
        # avg_common_strobe3
        self.halt = self.OP(0)
        if not self.OP(0) and not self.OP(2):
            if self.OP(1):
                cycles = 0x100 - (self.timer & 0xFF)
            else:
                cycles = 0x8000 - self.timer
            self.timer = 0
            self.xpos += ((((self.dvx >> 3) ^ 0x200) - 0x200) * cycles * (self.scale ^ 0xFF)) >> 4
            self.ypos -= ((((self.dvy >> 3) ^ 0x200) - 0x200) * cycles * (self.scale ^ 0xFF)) >> 4
        if self.OP(2):
            self.timer = 0
            self.xpos, self.ypos = XCENTER, YCENTER
            self.points.append((self.xpos, self.ypos, 0, 0))
        # avg_tempest_device::handler_7: the point, axes swapped as MAME does
        if not self.OP(0) and not self.OP(2):
            inten = self.intensity if (self.int_latch >> 1) == 1 else (self.int_latch & 0xE)
            x = self.ypos - YCENTER + XCENTER
            y = self.xpos - XCENTER + YCENTER
            self.points.append((x, y, self.color, inten))


def sext(v, bits):
    return v - (1 << bits) if v & (1 << (bits - 1)) else v


def vg_word(mem, p):
    """The AVG word at word address p of VG space (vector RAM, then vector ROM), little-endian."""
    return mem[(2 * p) & 0x1FFF] | mem[(2 * p + 1) & 0x1FFF] << 8


def normalise(dvy, dvx):
    """handler_4's loop: shifts until bit 12 and bit 11 differ in either component (at most 16)."""
    n = 0
    while n < 16 and ((dvy ^ (dvy << 1)) & 0x1000) == 0 and ((dvx ^ (dvx << 1)) & 0x1000) == 0:
        n += 1
        dvy = (dvy & 0x1000) | ((dvy << 1) & 0x1FFF)
        dvx = (dvx & 0x1000) | ((dvx << 1) & 0x1FFF)
    return n, dvy, dvx


class InstrAVG:
    """The same machine one instruction at a time, as the state PROM sequences it (2026-09-23:
    VCTR runs handlers 1,0,3,2,4,5,7; SVEC 1,3,4,5,7; STAT/SCAL 1,0,6; CNTR 1,0,4,7; JSRL
    1,0,4,5,6; RTSL 1,0,5,6; JMPL 1,0,6; the timer is 0 whenever a vector starts).  Gives exactly
    TempestAVG's points on every captured frame that ends (--verify), far faster.  `on_vector`,
    if set, is called with each vector's (op, dvy, dvx, bin_scale, scale, dx, dy) for checks."""

    MAXSTEPS = 100000
    on_vector = None

    def run(self, vram, rom, cram=None):
        mem = vram + rom
        pc = sp = 0
        stack = [0, 0, 0, 0]
        scale = bs = color = intensity = 0
        x, y = XCENTER, YCENTER
        pts = []
        for _ in range(self.MAXSTEPS):
            w = vg_word(mem, pc)
            pc += 1
            op = w >> 13
            if op in (0, 2):
                if op == 0:
                    dvy = w & 0x1FFF
                    w2 = vg_word(mem, pc)
                    pc += 1
                    z, dvx = w2 >> 13, w2 & 0x1FFF
                else:
                    dvy, z, dvx = ((w >> 8) & 0x1F) << 8, (w >> 5) & 7, (w & 0x1F) << 8
                n, ny, nx = normalise(dvy, dvx)
                k = n + bs
                cyc = (0x8000 >> min(k, 15)) if op == 0 else (0x100 >> min(k, 8))
                dx = ((((nx >> 3) ^ 0x200) - 0x200) * cyc * (scale ^ 0xFF)) >> 4
                dy = ((((ny >> 3) ^ 0x200) - 0x200) * cyc * (scale ^ 0xFF)) >> 4
                if self.on_vector:
                    self.on_vector(op, dvy, dvx, bs, scale, dx, dy)
                x += dx
                y -= dy
                pts.append((y - YCENTER + XCENTER, x - XCENTER + YCENTER, color,
                            intensity if z == 1 else z << 1))
            elif op == 1:
                break
            elif op == 3:
                if w & 0x1000:
                    scale, bs = w & 0xFF, (w >> 8) & 7
                elif w & 0x800:
                    color = w & 0xF
                else:
                    intensity = (w >> 4) & 0xF
            elif op == 4:
                x, y = XCENTER, YCENTER
                pts.append((x, y, 0, 0))
            elif op == 5:
                stack[sp & 3] = pc
                sp = (sp + 1) & 0xF
                pc = w & 0x1FFF
            elif op == 6:
                sp = (sp - 1) & 0xF
                pc = stack[sp & 3]
            else:
                pc = w & 0x1FFF
                if pc == 0:
                    break
        self.bin_scale, self.scale = bs, scale
        return pts


# ---------------------------------------------------------------------------------------------
# The port's pipeline: the 6809 interpreter's exact specification (plan stage 2).
#
# Integer only, and cheap on a 6809.  The beam is kept in bitmap pixels, 16.8 fixed point, 24 bits
# an axis (col, row).  MAME moves the beam by  d = ((v_n >> 3) * cycles * L) >> 4  (L = scale^$FF,
# v_n the normalised component, cycles from the normalisation count n and the binary scale bs).
# That is exactly  d = v_eff * L * 2^(8-bs)  for an integer v_eff (veff_vctr, veff_svec; checked
# against every captured vector by --verify), and in bitmap pixels  d * 12/29 / 65536.  So a vector
# moves the beam by  v_eff * Q / 256  in 16.8, with  Q = round(L * 12/29 * 256 / 2^bs)  set once per
# SCAL, and the product truncated toward zero.  Endpoints are rounded to whole pixels, clipped in
# integers (Cohen-Sutherland, rounded intersections), and become 8-byte SS.BmLine records.
#
# Characters (plan D3): a JSRL to a VGMSGA character at one of the two text scales is not run; it
# appends a text entry (glyph, size, colour, beam position) and moves the beam by the glyph's
# advance, which glyph_table() gets by running the character through this same arithmetic, so the
# beam ends exactly where running it would have left it.

QK = 27118                          # round(12/29 * 256 * 256): L * QK >> 8 = L * 12/29 * 256
GLYPH_SCALES = ((1, 0), (0, 0))     # (binary, linear) scales of Tempest's text: normal, big
VGMSGA_W = 0x8F2                    # word address of VGMSGA ($31E4), the 41 character JSRLs
NGLYPHS = 41
COORD_LIM = 8192                    # an endpoint beyond +-8192 px drops the line (keeps clip in 16 bits)


def q_for(scale, bs):
    q0 = ((scale ^ 0xFF) * QK + 128) >> 8
    return (q0 + ((1 << bs) >> 1)) >> bs


def veff_vctr(vx, vy, bs):
    """VCTR components (13-bit, signed) -> v_eff, so that MAME's move is v_eff * L * 2^(8-bs).
    n (normalisation) is 12 - bit_length of T, T the OR of the components' magnitudes-less-one;
    n < 3 drops the low 3-n bits (>> 3 after the shifts); n + bs >= 16 clamps the timer at 1."""
    if vx == 0 and vy == 0:
        return 0, 0
    t = (vx if vx >= 0 else ~vx) | (vy if vy >= 0 else ~vy)
    n = 12 - t.bit_length()
    if n + bs >= 16:
        s = n + bs - 15
        return vx << s, vy << s
    if n < 3:
        m = ~((1 << (3 - n)) - 1)
        return vx & m, vy & m
    return vx, vy


def veff_svec(vx5, vy5, bs):
    """SVEC components (5-bit, signed): the same, where a short vector is 2*v5 unless
    n + bs > 8 clamps its 8-bit timer."""
    if vx5 == 0 and vy5 == 0:
        return 0, 0
    t = (vx5 if vx5 >= 0 else ~vx5) | (vy5 if vy5 >= 0 else ~vy5)
    k = 4 - t.bit_length() + bs
    s = k - 8 if k > 8 else 0
    return (2 * vx5) << s, (2 * vy5) << s


def wrap(v, bits):
    m = 1 << bits
    return ((v + (m >> 1)) & (m - 1)) - (m >> 1)


def pix(p):
    """16.8 beam -> whole pixel, rounded half up, as a signed 16-bit value."""
    return wrap((p + 0x80) >> 8, 16)


LEFT, RIGHT, TOP, BOTTOM = 1, 2, 4, 8


def outcode(x, y):
    return ((x < 0) * LEFT) | ((x > BM_W - 1) * RIGHT) | ((y < 0) * TOP) | ((y > BM_H - 1) * BOTTOM)


def muldiv(a, b, c):
    """round(a * b / c), halves away from zero, as the 6809 does it: magnitudes, then the sign."""
    q = (2 * abs(a) * abs(b) + abs(c)) // (2 * abs(c))
    return -q if (a < 0) ^ (b < 0) ^ (c < 0) else q


def clip_int(x0, y0, x1, y1):
    """Cohen-Sutherland on whole pixels.  Each step moves the first outside endpoint (p0 before
    p1) to the first boundary it is outside of (left, right, top, bottom), the other coordinate
    by a rounded proportion.  At most four steps; a line still outside after them is dropped."""
    for x in (x0, y0, x1, y1):
        if not -COORD_LIM <= x < COORD_LIM:
            return None
    for step in range(5):
        c0, c1 = outcode(x0, y0), outcode(x1, y1)
        if not (c0 | c1):
            return (x0, y0, x1, y1)
        if c0 & c1 or step == 4:
            return None
        first = c0 != 0
        px, py, ox, oy = (x0, y0, x1, y1) if first else (x1, y1, x0, y0)
        c = c0 if first else c1
        if c & (LEFT | RIGHT):
            b = 0 if c & LEFT else BM_W - 1
            py, px = py + muldiv(oy - py, b - px, ox - px), b
        else:
            b = 0 if c & TOP else BM_H - 1
            px, py = px + muldiv(ox - px, b - py, oy - py), b
        if first:
            x0, y0 = px, py
        else:
            x1, y1 = px, py
    return None


class PortAVG:
    """The 6809 interpreter's specification.  run() returns (records, texts): records are
    (x0, y0, x1, y1, clut) with clut = colour*16 + intensity, any number (the 6809 hands them over
    in batches of up to 255, SS.BmLine's limit); texts are (glyph | $80 if big, clut, col, row),
    clut = colour*16 + the glyph's own intensity, at most MAXTXT.  A list ends at HALT or JMPL 0
    (stats "ended" = 1) or after MAXJUMPS control transfers (JSRL run, RTSL, JMPL; a runaway list).
    Counters are left in self.stats.  Not specified: a list that runs off the end of vector RAM or
    ROM without a jump (the 6809 walks on into whatever follows)."""

    MAXJUMPS = 1024
    MAXTXT = 256

    def __init__(self, rom, glyphs=True):
        self.rom = rom
        self.gmap = {}             # target word -> glyph index (first VGMSGA entry using it)
        self.gtab = {}             # (index, big) -> (dcol, drow, scale_after, intensity or 0)
        if glyphs:
            self.gtab = glyph_table(rom)
            for i in range(NGLYPHS):
                t = vg_word(bytes(4096) + rom, VGMSGA_W + i) & 0x1FFF
                self.gmap.setdefault(t, i)

    def run(self, vram, rom=None):
        mem = vram + (rom or self.rom)
        pc = sp = 0
        stack = [0, 0, 0, 0]
        scale = bs = color = intensity = 0
        q = q_for(0, 0)
        col, row = 160 << 8, 120 << 8
        recs, texts = [], []
        st = {"instructions": 0, "vectors": 0, "glyphs": 0, "clipped": 0, "dropped": 0, "full": 0,
              "ended": 0, "centred": 0, "statint": 0}
        self.trace = []
        jumps = self.MAXJUMPS
        while jumps:
            st["instructions"] += 1
            w = vg_word(mem, pc)
            pc += 1
            op = w >> 13
            if op in (0, 2):
                st["vectors"] += 1
                if op == 0:
                    w2 = vg_word(mem, pc)
                    pc += 1
                    z = w2 >> 13
                    ex, ey = veff_vctr(sext(w2 & 0x1FFF, 13), sext(w & 0x1FFF, 13), bs)
                else:
                    z = (w >> 5) & 7
                    ex, ey = veff_svec(sext(w & 0x1F, 5), sext((w >> 8) & 0x1F, 5), bs)
                c0, r0 = pix(col), pix(row)
                dx = (abs(ex) * q) >> 8
                dy = (abs(ey) * q) >> 8
                col = wrap(col + (-dx if ex < 0 else dx), 24)
                row = wrap(row - (-dy if ey < 0 else dy), 24)
                inten = intensity if z == 1 else z << 1
                st["statint"] += z == 1
                if inten:
                    c = clip_int(c0, r0, pix(col), pix(row))
                    if c is None:
                        st["dropped"] += 1
                    else:
                        if c != (c0, r0, pix(col), pix(row)):
                            st["clipped"] += 1
                        recs.append(c + (((color & 0xF) << 4) | inten,))
            elif op == 1:
                st["ended"] = 1
                break
            elif op == 3:
                if w & 0x1000:
                    scale, bs = w & 0xFF, (w >> 8) & 7
                    q = q_for(scale, bs)
                elif w & 0x800:
                    color = w & 0xF
                else:
                    intensity = (w >> 4) & 0xF
            elif op == 4:
                st["centred"] += 1
                col, row = 160 << 8, 120 << 8
            elif op == 5:
                t = w & 0x1FFF
                g = self.gmap.get(t)
                if g is not None and scale == 0 and bs in (0, 1):
                    dcol, drow, after, gint = self.gtab[(g, bs == 0)]
                    st["glyphs"] += 1
                    if gint:
                        if len(texts) < self.MAXTXT:
                            texts.append((g | (0x80 if bs == 0 else 0), ((color & 0xF) << 4) | gint,
                                          pix(col), pix(row)))
                        else:
                            st["full"] += 1
                    col, row = wrap(col + dcol, 24), wrap(row + drow, 24)
                    if after:
                        bs, scale = after
                        q = q_for(scale, bs)
                    continue
                jumps -= 1
                stack[sp & 3] = pc
                sp = (sp + 1) & 0xF
                pc = t
            elif op == 6:
                jumps -= 1
                sp = (sp - 1) & 0xF
                pc = stack[sp & 3]
            else:
                jumps -= 1
                pc = w & 0x1FFF
                if pc == 0:
                    st["ended"] = 1
                    break
        self.stats = st
        self.state = (col, row, bs, scale, color, intensity, sp)
        return recs, texts


def glyph_table(rom):
    """Each VGMSGA character at each text scale, run through PortAVG's arithmetic from the centre:
    its advance (16.8), the scale it leaves (HALF), its intensity (the highest of its strokes; 0 if
    it draws nothing).  Characters must not set colour or intensity, or centre the beam."""
    out = {}
    pa = PortAVG(rom, glyphs=False)
    for i in range(NGLYPHS):
        t = vg_word(bytes(4096) + rom, VGMSGA_W + i)
        if t >> 13 != 5:
            sys.exit("VGMSGA entry %d is not a JSRL: %04x" % (i, t))
        for bsc, lin in GLYPH_SCALES:
            prog = b"".join(bytes((v & 0xFF, v >> 8)) for v in
                            (0x6000 | 0xF0, 0x6800 | 1, 0x7000 | (bsc << 8) | lin, t, 0xE000))
            recs, _ = pa.run(prog.ljust(4096, b"\0"), rom)
            col, row, bs, scale, color, inten, sp = pa.state
            if (color != 1 or inten != 15 or sp != 0 or not pa.stats["ended"] or pa.stats["centred"]
                    or pa.stats["statint"]):
                sys.exit("character %d changes more than the beam and the scale" % i)
            after = (bs, scale) if (bs, scale) != (bsc, lin) else None
            out[(i, bsc == 0)] = (col - (160 << 8), row - (120 << 8), after,
                                  max((r[4] & 0xF for r in recs), default=0))
    return out


def to_bitmap(x, y):
    """MAME screen coordinates (<<16, 580x570, before ROT270) -> F256 pixel, as floats.
    Displayed column = y, displayed row = x (the first render, with row = 579 - x, drew the text
    upside down).  The 570x580 portrait picture is scaled to 240 rows and centred in 320 columns."""
    u = y / 65536.0
    v = x / 65536.0
    k = BM_H / float(VIS_W)
    return (BM_W / 2.0 + (u - VIS_H / 2.0) * k, v * k)


def clip(x0, y0, x1, y1, w=BM_W - 1, h=BM_H - 1):
    """Liang-Barsky to [0,w]x[0,h]; None if nothing is left."""
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0), (dx, w - x0), (-dy, y0), (dy, h - y0)):
        if p == 0:
            if q < 0:
                return None
        else:
            r = q / p
            if p < 0:
                t0 = max(t0, r)
            else:
                t1 = min(t1, r)
            if t0 > t1:
                return None
    return (x0 + t0 * dx, y0 + t0 * dy, x0 + t1 * dx, y0 + t1 * dy)


def records(points):
    """Beam points -> the line records the port would send: (x0, y0, x1, y1, clut index)."""
    out = []
    drawn = visible = 0
    if not points:
        return out, 0, 0
    px, py = points[0][0], points[0][1]
    for (x, y, colour, inten) in points[1:]:
        drawn += 1
        if inten:
            visible += 1
            a = to_bitmap(px, py)
            b = to_bitmap(x, y)
            c = clip(a[0], a[1], b[0], b[1])
            if c:
                r = tuple(int(round(v)) for v in c)
                out.append(r + ((colour & 0xF) * 16 + (inten & 0xF),))
        px, py = x, y
    return out, drawn, visible


def pixels(rec):
    x0, y0, x1, y1, _ = rec
    return max(abs(x1 - x0), abs(y1 - y0)) + 1


def clut_rgb(cram, index):
    """CLUT entry for index = colour*16 + intensity, from MAME's colour decode
    (avg_tempest_device::handler_7), scaled linearly by intensity/15."""
    colour, inten = index >> 4, index & 0xF
    d = cram[colour] if colour < len(cram) else 0
    b3, b2, b1, b0 = (~d >> 3) & 1, (~d >> 2) & 1, (~d >> 1) & 1, ~d & 1
    r = b1 * 0xF3 + b0 * 0x0C
    g = b3 * 0xF3
    b = b2 * 0xF3
    k = inten / 15.0
    return (int(r * k), int(g * k), int(b * k))


def bresenham(x0, y0, x1, y1):
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx + dy
    while True:
        yield x0, y0
        if x0 == x1 and y0 == y1:
            return
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def write_png(path, recs, cram):
    import zlib
    img = [[(0, 0, 0)] * BM_W for _ in range(BM_H)]
    for r in recs:
        rgb = clut_rgb(cram, r[4])
        for x, y in bresenham(*r[:4]):
            img[y][x] = rgb
    raw = b"".join(b"\0" + bytes(c for px in row for c in px) for row in img)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", BM_W, BM_H, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def write_tables(path, rom):
    """src/avgtab.a: AvGMap (character routine -> glyph) and AvGTab (each glyph's advance, the scale
    it leaves, its intensity), both sizes, from glyph_table()."""
    gt = glyph_table(rom)
    targets = [vg_word(bytes(4096) + rom, VGMSGA_W + i) & 0x1FFF for i in range(NGLYPHS)]
    if min(targets) < 0x800:
        sys.exit("a character routine below $800")
    gmap = [0xFF] * (max(targets) + 1 - 0x800)
    for i, t in enumerate(targets):
        if gmap[t - 0x800] == 0xFF:
            gmap[t - 0x800] = i
    out = ["* avgtab.a - GENERATED by tools/avgview.py --tables src/avgtab.a (from the vector ROM):",
           "* do not edit.  The AVG interpreter's glyph tables (avg.a, AvJsrl and AvGlyph).",
           "*",
           "* AvGMap: one byte per word address from $800 (the character routines; DASH, HALF and",
           "* COPYR follow VGMSGA), the glyph whose routine starts there, or $FF.",
           "AvGMLen\tequ\t%d" % len(gmap),
           "AvGMap"]
    for k in range(0, len(gmap), 16):
        out.append("\tfcb\t" + ",".join("$%02X" % v for v in gmap[k:k + 16]))
    out += ["* AvGTab: per glyph, the normal size (binary scale 1) then the big (0), 9 bytes each:",
            "* the advance in 16.8 pixels (column, then row: 3 bytes each, signed), the scale it",
            "* leaves (binary, linear; $FF, 0: unchanged), its intensity (0: it draws nothing).",
            "AvGTab"]
    for i in range(NGLYPHS):
        for big in (False, True):
            dc, dr, after, gint = gt[(i, big)]
            for v in (dc, dr):
                if not -(1 << 23) <= v < (1 << 23):
                    sys.exit("glyph %d's advance does not fit 24 bits" % i)
            b = [(dc >> 16) & 0xFF, (dc >> 8) & 0xFF, dc & 0xFF, (dr >> 16) & 0xFF, (dr >> 8) & 0xFF,
                 dr & 0xFF]
            b += list(after) if after else [0xFF, 0]
            b.append(gint)
            out.append("\tfcb\t" + ",".join("$%02X" % v for v in b) + "\t\t%d %s" %
                       (i, "big" if big else "normal"))
    open(path, "w").write("\n".join(out) + "\n")
    print("wrote %s" % path)


def verify(captures, prom, first):
    """InstrAVG against TempestAVG (the same points), and v_eff against MAME's arithmetic (every
    vector's move is v_eff * L * 2^(8-bs)).  Frames before `first` are skipped: at power-up vector
    RAM holds no list, and both machines run away to their step limits."""
    ref = TempestAVG(prom)
    ins = InstrAVG()
    bad = {"points": 0, "veff": 0}
    counts = {"frames": 0, "vectors": 0}

    def check(op, dvy, dvx, bs, scale, dx, dy):
        counts["vectors"] += 1
        if op == 0:
            ex, ey = veff_vctr(sext(dvx, 13), sext(dvy, 13), bs)
        else:
            ex, ey = veff_svec(sext(dvx >> 8, 5), sext(dvy >> 8, 5), bs)
        m = (scale ^ 0xFF) << (8 - bs)
        if (ex * m, ey * m) != (dx, dy):
            bad["veff"] += 1
            if bad["veff"] <= 5:
                print("  v_eff wrong: op %d dvy %04x dvx %04x bs %d scale %d: MAME %d,%d" %
                      (op, dvy, dvx, bs, scale, dx, dy))
    ins.on_vector = check
    for cap in captures:
        rom = None
        for item in read_capture(cap):
            if item[0] == "rom":
                rom = item[1]
                continue
            _, n, vram, cram = item
            if n < first:
                continue
            counts["frames"] += 1
            if ins.run(vram, rom) != ref.run(vram, rom, cram):
                bad["points"] += 1
                print("  frame %d: InstrAVG differs from TempestAVG" % n)
    print("verify: %d frames, %d vectors; frames differing %d, v_eff wrong %d" %
          (counts["frames"], counts["vectors"], bad["points"], bad["veff"]))
    return not (bad["points"] or bad["veff"])


def compare(captures, first):
    """PortAVG (glyphs off) against the float pipeline, record for record."""
    ins = InstrAVG()
    fr = same_len = exact = 0
    ncoord = off1 = offmore = 0
    for cap in captures:
        rom = None
        port = None
        for item in read_capture(cap):
            if item[0] == "rom":
                rom = item[1]
                port = PortAVG(rom, glyphs=False)
                continue
            _, n, vram, cram = item
            if n < first:
                continue
            fr += 1
            fl, _, _ = records(ins.run(vram, rom))
            pr, _ = port.run(vram)
            if len(fl) != len(pr):
                continue
            same_len += 1
            exact += fl == pr
            for a, b in zip(fl, pr):
                for u, v in zip(a[:4], b[:4]):
                    ncoord += 1
                    d = abs(u - v)
                    off1 += d == 1
                    offmore += d > 1
    print("compare: %d frames, %d with as many records, %d identical; of %d coordinates %d differ "
          "by 1 px (%.3f%%), %d by more" % (fr, same_len, exact, ncoord, off1,
                                           100.0 * off1 / max(ncoord, 1), offmore))


def port_stats(captures, first, per_frame):
    rows = []
    for cap in captures:
        rom = None
        port = None
        for item in read_capture(cap):
            if item[0] == "rom":
                rom = item[1]
                port = PortAVG(rom)
                continue
            _, n, vram, cram = item
            if n < first:
                continue
            recs, texts = port.run(vram)
            st = port.stats
            rows.append((n, st["instructions"], st["vectors"], len(recs), len(texts), st["glyphs"],
                         st["clipped"], st["dropped"], st["full"], sum(pixels(r) for r in recs)))
            if per_frame:
                print("%6d  instr %4d  vectors %4d  records %4d  texts %3d  glyphs %3d  clipped %2d  "
                      "dropped %2d  full %d  pixels %5d" % rows[-1])
    names = ("instructions", "vectors", "records", "texts", "glyph calls", "clipped", "dropped",
             "over the buffer", "pixels")
    print("frames %d" % len(rows))
    for i, name in enumerate(names, 1):
        v = sorted(r[i] for r in rows)
        print("%-16s min %6d  median %6d  95%% %6d  max %6d" %
              (name, v[0], v[len(v) // 2], v[int(len(v) * 0.95)], v[-1]))


def write_png_port(path, recs, texts, cram, glyphs):
    """The port's picture: records by Bresenham, texts as glyph masks (captures/glyphs)."""
    img_recs = list(recs)
    for (g, clut, col, row) in texts:
        gl = glyphs[str(GLYPH_SCALES[1] if g & 0x80 else GLYPH_SCALES[0])][g & 0x7F]
        for r, bits in enumerate(gl["rows"]):
            for c in range(gl["w"]):
                if bits >> (gl["w"] - 1 - c) & 1:
                    x, y = col + gl["x"] + c, row + gl["y"] + r
                    if 0 <= x < BM_W and 0 <= y < BM_H:
                        img_recs.append((x, y, x, y, clut))
    write_png(path, img_recs, cram)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("capture")
    ap.add_argument("--prom", default=os.path.join(ROMS, "136002-125.d7"))
    ap.add_argument("--stats", action="store_true", help="per-frame numbers, then a summary")
    ap.add_argument("--png", help="directory for PNGs of --frames")
    ap.add_argument("--frames", default="", help="comma-separated MAME frame numbers to render")
    ap.add_argument("--verify", action="store_true",
                    help="InstrAVG against the PROM machine, and v_eff against MAME's arithmetic")
    ap.add_argument("--compare", action="store_true", help="the port's records against the float ones")
    ap.add_argument("--port", action="store_true",
                    help="the port's pipeline (PortAVG): numbers, and with --png its picture")
    ap.add_argument("--first", type=int, default=600,
                    help="with --verify/--compare/--port, skip MAME frames before this (power-up)")
    ap.add_argument("--tables", help="write the 6809's glyph tables (src/avgtab.a) and stop")
    ap.add_argument("more", nargs="*", help="more captures, for --verify/--compare/--port")
    a = ap.parse_args()

    caps = [a.capture] + a.more
    prom = open(a.prom, "rb").read()
    if a.tables:
        write_tables(a.tables, next(read_capture(a.capture))[1])
        return
    if a.verify:
        sys.exit(0 if verify(caps, prom, a.first) else 1)
    if a.compare:
        compare(caps, a.first)
        return
    if a.port and not a.png:
        port_stats(caps, a.first, a.stats)
        return
    if a.port:
        import json
        gl = json.load(open(os.path.join(os.path.dirname(__file__), "..", "captures", "glyphs",
                                         "glyphs.json")))
        want = {int(n) for n in a.frames.split(",") if n}
        port = None
        for item in read_capture(a.capture):
            if item[0] == "rom":
                port = PortAVG(item[1])
                continue
            _, n, vram, cram = item
            if n in want:
                os.makedirs(a.png, exist_ok=True)
                recs, texts = port.run(vram)
                write_png_port(os.path.join(a.png, "p%06d.png" % n), recs, texts, cram, gl)
        return

    want = {int(n) for n in a.frames.split(",") if n}
    avg = TempestAVG(prom)
    rows = []
    rom = None
    for item in read_capture(a.capture):
        if item[0] == "rom":
            rom = item[1]
            continue
        _, n, vram, cram = item
        pts = avg.run(vram, rom, cram)
        recs, drawn, visible = records(pts)
        pix = sum(pixels(r) for r in recs)
        rows.append((n, drawn, visible, len(recs), pix, max((pixels(r) for r in recs), default=0)))
        if a.stats:
            print("%6d  vectors %4d  visible %4d  records %4d  pixels %6d  longest %3d" % rows[-1])
        if a.png and n in want:
            os.makedirs(a.png, exist_ok=True)
            write_png(os.path.join(a.png, "f%06d.png" % n), recs, cram)

    if rows:
        def summ(i, name):
            v = sorted(r[i] for r in rows)
            print("%-8s min %6d  median %6d  95%% %6d  max %6d" %
                  (name, v[0], v[len(v) // 2], v[int(len(v) * 0.95)], v[-1]))
        print("frames %d" % len(rows))
        summ(2, "visible")
        summ(3, "records")
        summ(4, "pixels")
        worst = max(rows, key=lambda r: r[4])
        print("worst frame %d: %d records, %d pixels" % (worst[0], worst[3], worst[4]))


if __name__ == "__main__":
    main()
