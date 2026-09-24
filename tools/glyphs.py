#!/usr/bin/env python3
"""glyphs.py - Tempest's vector characters as bitmap glyph masks (plan D3).

Every character Tempest prints is an AVG subroutine in the vector ROM, reached through the VGMSGA
table of JSRLs at $31E4 (41 entries: blank, 0-9, A-Z, then specials).  This tool runs each one through
avgview's literal port of MAME's AVG, at each of the two scales Tempest's text uses, and records:

  - the mask: the pixels the line engine would have drawn, relative to the beam's position when the
    character was called (rounded to a pixel), as a bounding box plus 1-bit rows;
  - the advance: how far the character moves the beam, in MAME beam units (<<16), so the 6809
    interpreter can skip the subroutine and still put the next character in the right place;
  - whether the character changes the scale on the way out (HALF does);
  - the strokes' intensities: characters carry their own (12, and 10 in a few), not STAT's.

Outputs, into --out (default captures/glyphs):
  glyphs.json   everything above, for the other host tools
  glyphs.png    a preview sheet, both sizes, each glyph on a grid
  and, with --check CAPTURE, a comparison of glyph-drawn text against line-drawn text over a capture.

The binary format for the 6809 side is deliberately not fixed here; it follows the interpreter's
design (plan stage 2).
"""

import argparse
import json
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(__file__))
import avgview as av  # noqa: E402

VROM = os.path.join(av.ROMS, "136002-138.np3")
VGMSGA = 0x11E4                  # VG address of the table ($31E4 in CPU space)
NCHARS = 41
CHAR_LO, CHAR_HI = 0x1000, 0x11E4   # VG addresses of the character routines

# What each VGMSGA entry prints, from ASCVG.MAC's encoding (0 blank, 1-10 digits, 11-36 A-Z).  The
# three specials are ALVROM's DASH, HALF ("1/2 (USE QUOTES)") and COPYR ("CIRCLE C (USE #)"),
# identified from their rendered shapes (2026-09-22): a bar, a 1/2, and a circled C.  HALF is the one
# that changes the scale on exit (ALVROM ends it with SCAL 1).
NAMES = [" "] + [str(d) for d in range(10)] + [chr(c) for c in range(ord("A"), ord("Z") + 1)] + \
        [" ", "-", '"', "#"]

# The scales Tempest draws text at: (binary scale, linear scale).  docs/status.md.
SCALES = [(1, 0), (0, 0)]


def word(w):
    return bytes((w & 0xFF, w >> 8))


def program(target, bscale, lscale):
    """A tiny display list in vector RAM: centre, set intensity/colour and scale, call the
    character, then jump to 0 (the end-of-pass marker the interpreter stops on)."""
    p = b""
    p += word(0x8040)                                  # CNTR
    p += word(0x60F0)                                  # STAT: intensity 15
    p += word(0x6801)                                  # STAT: colour 1
    p += word(0x7000 | (bscale << 8) | lscale)         # SCAL
    p += word(0xA000 | ((target >> 1) & 0x1FFF))       # JSRL
    p += word(0xE000)                                  # JMPL 0
    return p.ljust(4096, b"\0")


XSCALE = 1                        # 2 with --hires: columns of a 640x240 plane, rows as before


def run_char(avg, rom, target, bscale, lscale):
    pts = avg.run(program(target, bscale, lscale), rom, bytes(16))
    # pts[0] is the CNTR point; the character starts there.
    sx, sy = pts[0][0], pts[0][1]
    ox, oy = av.to_bitmap(sx, sy)
    pix = set()
    px, py = sx, sy
    for (x, y, _c, inten) in pts[1:]:
        if inten:
            a = av.to_bitmap(px, py)
            b = av.to_bitmap(x, y)
            x0, y0 = round((a[0] - ox) * XSCALE), round(a[1] - oy)
            x1, y1 = round((b[0] - ox) * XSCALE), round(b[1] - oy)
            for q in av.bresenham(x0, y0, x1, y1):
                pix.add(q)
        px, py = x, y
    ex, ey = pts[-1][0], pts[-1][1]
    inten = sorted({p[3] for p in pts[1:] if p[3]})
    return pix, (ex - sx, ey - sy), (avg.bin_scale, avg.scale), inten


def pack(pix):
    if not pix:
        return {"x": 0, "y": 0, "w": 0, "h": 0, "rows": []}
    xs = [p[0] for p in pix]
    ys = [p[1] for p in pix]
    x0, y0 = min(xs), min(ys)
    w, h = max(xs) - x0 + 1, max(ys) - y0 + 1
    rows = []
    for y in range(y0, y0 + h):
        bits = 0
        for x in range(x0, x0 + w):
            bits = (bits << 1) | ((x, y) in pix)
        rows.append(bits)
    return {"x": x0, "y": y0, "w": w, "h": h, "rows": rows}


def write_sheet(path, glyphs):
    cell = 20
    cols = NCHARS
    W, H = cols * cell, len(SCALES) * cell
    img = [[(20, 20, 20)] * W for _ in range(H)]
    for si, sc in enumerate(SCALES):
        for ci in range(NCHARS):
            g = glyphs[str(sc)][ci]
            bx, by = ci * cell + 6, si * cell + 12
            img[by][bx] = (255, 0, 0)                      # the origin
            for r, bits in enumerate(g["rows"]):
                for c in range(g["w"]):
                    if bits >> (g["w"] - 1 - c) & 1:
                        x, y = bx + g["x"] + c, by + g["y"] + r
                        if 0 <= x < W and 0 <= y < H:
                            img[y][x] = (255, 255, 255)
    raw = b"".join(b"\0" + bytes(v for px in row for v in px) for row in img)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


class Tagging(av.TempestAVG):
    """The AVG, noting each character JSRL (target, beam position, scale) as it is taken."""

    def run(self, *a):
        self.charcalls = []
        self.depth_in_char = 0
        return super().run(*a)

    def h6(self):
        if self.OP(2) and self.OP(0) and not self.OP(1):          # JSRL
            t = self.dvy << 1
            if CHAR_LO <= t < CHAR_HI:
                self.charcalls.append((t, self.xpos, self.ypos, self.bin_scale, self.scale, self.color,
                                       self.intensity, len(self.points)))
        super().h6()


def check(capture, glyphs, prom, every):
    """Draw each captured frame's characters both ways and count the pixels that differ."""
    by_target = {}
    rom = open(VROM, "rb").read()
    for ci in range(NCHARS):
        w = rom[VGMSGA - 0x1000 + 2 * ci] | rom[VGMSGA - 0x1000 + 2 * ci + 1] << 8
        by_target[(w & 0x1FFF) << 1] = ci
    avg = Tagging(prom)
    crom = None
    frames = chars = diff = total = unknown = 0
    for item in av.read_capture(capture):
        if item[0] == "rom":
            crom = item[1]
            continue
        _, n, vram, cram = item
        if n % every:
            continue
        pts = avg.run(vram, crom, cram)
        frames += 1
        # line-drawn: rasterise every visible segment that lies inside a character call
        calls = avg.charcalls
        spans = []
        for (t, xp, yp, bs, ls, col, it, i0) in calls:
            ci = by_target.get(t)
            if ci is None:
                unknown += 1
                continue
            key = str((bs, ls))
            if key not in glyphs:
                unknown += 1
                continue
            chars += 1
            g = glyphs[key][ci]
            adv = g["advance"]
            # beam in MAME's rotated frame, as handler_7 records it
            bx = yp - av.YCENTER + av.XCENTER
            by = xp - av.XCENTER + av.YCENTER
            o = av.to_bitmap(bx, by)
            ox, oy = round(o[0]), round(o[1])
            gp = set()
            for r, bits in enumerate(g["rows"]):
                for c in range(g["w"]):
                    if bits >> (g["w"] - 1 - c) & 1:
                        gp.add((ox + g["x"] + c, oy + g["y"] + r))
            # the same character, line-drawn at its true sub-pixel position
            npts = len(g["_npts"])
            seg = pts[i0 - 1:i0 + npts] if i0 > 0 else []
            lp = set()
            for k in range(1, len(seg)):
                if seg[k][3]:
                    a = av.to_bitmap(seg[k - 1][0], seg[k - 1][1])
                    b = av.to_bitmap(seg[k][0], seg[k][1])
                    for q in av.bresenham(round(a[0]), round(a[1]), round(b[0]), round(b[1])):
                        lp.add(q)
            diff += len(gp ^ lp)
            total += len(lp)
    print("frames %d, characters %d, not in the glyph set %d" % (frames, chars, unknown))
    if total:
        print("pixels line-drawn %d, differing %d (%.1f%%)" % (total, diff, 100.0 * diff / total))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "captures", "glyphs"))
    ap.add_argument("--prom", default=os.path.join(av.ROMS, "136002-125.d7"))
    ap.add_argument("--check", help="an avgcap capture to compare glyph text against line text")
    ap.add_argument("--every", type=int, default=10, help="with --check, every n-th frame")
    ap.add_argument("--asm", help="also write the 6809 mask table (src/glyphs.a) here")
    ap.add_argument("--hires", action="store_true",
                    help="render for a 640x240 plane: columns doubled, 1-dot strokes, 2-byte rows")
    a = ap.parse_args()
    global XSCALE
    XSCALE = 2 if a.hires else 1

    rom = open(VROM, "rb").read()
    prom = open(a.prom, "rb").read()
    avg = av.TempestAVG(prom)
    out = {}
    for sc in SCALES:
        lst = []
        for ci in range(NCHARS):
            w = rom[VGMSGA - 0x1000 + 2 * ci] | rom[VGMSGA - 0x1000 + 2 * ci + 1] << 8
            if w >> 13 != 5:
                sys.exit("VGMSGA entry %d is not a JSRL: %04x" % (ci, w))
            target = (w & 0x1FFF) << 1
            pix, adv, after, inten = run_char(avg, rom, target, *sc)
            g = pack(pix)
            g.update({"index": ci, "name": NAMES[ci], "target": 0x2000 + target, "advance": list(adv),
                      "scale_after": list(after) if tuple(after) != sc else None,
                      # The strokes' own intensities (VCTR intensity, not STAT): the glyph is drawn
                      # in colour*16 + the highest of these.  A few glyphs mix 10 and 12.
                      "intensity": inten})
            g["_npts"] = [0] * (len(avg.points) - 1)
            lst.append(g)
        out[str(sc)] = lst

    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "glyphs.json"), "w") as f:
        json.dump({k: [{kk: vv for kk, vv in g.items() if not kk.startswith("_")} for g in v]
                   for k, v in out.items()}, f, indent=1)
    write_sheet(os.path.join(a.out, "glyphs.png"), out)

    for sc in SCALES:
        gl = out[str(sc)]
        hs = [g["h"] for g in gl if g["h"]]
        ws = [g["w"] for g in gl if g["w"]]
        adv = gl[NAMES.index("A")]["advance"]
        print("scale %s: glyph height %d-%d, width %d-%d px; advance of A = %s beam units"
              % (sc, min(hs), max(hs), min(ws), max(ws), adv))
        changed = [g["name"] for g in gl if g["scale_after"]]
        if changed:
            print("  changes the scale on exit: %s" % changed)
    print("wrote %s" % os.path.abspath(a.out))

    if a.asm:
        write_asm(a.asm, out)
        print("wrote %s" % os.path.abspath(a.asm))

    if a.check:
        check(a.check, out, prom, a.every)


def write_asm(path, out):
    if XSCALE == 2:
        return write_asm_hires(path, out)
    """src/glyphs.a: GlyTab, for text.a.  Per glyph (VGMSGA's order) the normal size then the big,
    15 bytes each: the mask's offset from the beam (column, row: signed), its width and height, then
    up to 11 rows, a byte each, the leftmost pixel in bit 7."""
    lines = ["* glyphs.a - GENERATED by tools/glyphs.py --asm (from the vector ROM): do not edit.",
             "* The text bitmap's glyph masks (text.a, plan D3): per glyph the normal size (binary scale 1)",
             "* then the big (0), 15 bytes each: column and row offset from the beam (signed), width,",
             "* height, then the rows, a byte each, the leftmost pixel in bit 7.",
             "GlyTab"]
    for ci in range(NCHARS):
        for sc in SCALES:
            g = out[str(sc)][ci]
            w, h = g["w"], g["h"]
            if w > 8 or h > 11:
                sys.exit("glyph %d at %s is %dx%d: more than the record holds" % (ci, sc, w, h))
            rows = [(r << (8 - w)) & 0xFF for r in g["rows"]] if w else []
            rec = [g["x"] & 0xFF, g["y"] & 0xFF, w, h] + rows + [0] * (11 - len(rows))
            lines.append("\tfcb\t%s\t\t%s, %s" % (",".join("$%02X" % b for b in rec), repr(g["name"]),
                                                      "big" if sc == SCALES[1] else "normal"))
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def write_asm_hires(path, out):
    """The same for a 640x240 plane (--hires): column offsets in 640 columns, rows 2 bytes each,
    the leftmost dot in bit 15 (the first byte's bit 7): 26 bytes a record."""
    lines = ["* glyphs.a - GENERATED by tools/glyphs.py --hires --asm (from the vector ROM): do not edit.",
             "* The text bitmap's glyph masks for a 640x240 plane (text.a, plan D3): per glyph the normal",
             "* size (binary scale 1) then the big (0), 26 bytes each: column (640ths) and row offset from",
             "* the beam (signed), width, height, then the rows, 2 bytes each, the leftmost dot in bit 15.",
             "GlyTab"]
    for ci in range(NCHARS):
        for sc in SCALES:
            g = out[str(sc)][ci]
            w, h = g["w"], g["h"]
            if w > 16 or h > 11:
                sys.exit("glyph %d at %s is %dx%d: more than the record holds" % (ci, sc, w, h))
            rows = []
            for r in g["rows"]:
                v = (r << (16 - w)) & 0xFFFF if w else 0
                rows += [v >> 8, v & 0xFF]
            rec = [g["x"] & 0xFF, g["y"] & 0xFF, w, h] + rows + [0] * (22 - len(rows))
            lines.append("\tfcb\t%s\t\t%s, %s" % (",".join("$%02X" % b for b in rec), repr(g["name"]),
                                                      "big" if sc == SCALES[1] else "normal"))
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
