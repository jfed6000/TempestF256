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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("capture")
    ap.add_argument("--prom", default=os.path.join(ROMS, "136002-125.d7"))
    ap.add_argument("--stats", action="store_true", help="per-frame numbers, then a summary")
    ap.add_argument("--png", help="directory for PNGs of --frames")
    ap.add_argument("--frames", default="", help="comma-separated MAME frame numbers to render")
    a = ap.parse_args()

    prom = open(a.prom, "rb").read()
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
