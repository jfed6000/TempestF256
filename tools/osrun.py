#!/usr/bin/env python3
"""osrun.py - the tempest module on the host 6809, with the OS-9 calls it makes played by this
script: the platform layer's host test (docs/status.md, "The platform layer").

The module (src/tempest, built by make) is loaded as OS-9 would load it and started at its entry
with U = DP = the data area.  Each `os9` call (SWI2) is answered here: F$Sleep, F$Time, F$Icpt,
F$AllRAM, F$MapBlk, F$ClrBlk, F$DelRAM, F$Exit, I$Write, and the GetStat/SetStat codes the
platform uses, the driver's side modelled from grfdrv256's register contracts: bitmaps in
"physical" 8K blocks, SS.BmClear, SS.BmLine drawing its records with avgview's Bresenham, the
CLUT, the layers, SS.LiveKeys from a script, SS.Tick from the cycle count.

Time: the 6809 at 8 MHz, a tick every 133,333 cycles; F$Sleep X=2 runs the clock to the next
tick.  An os9 call costs a fixed guess (grfdrv calls 400 us, SS.BmLine 474 us + 27.5 us a record,
others 150 us), so the frame times printed are estimates on the driver's side.  It proves the
program's logic, never the hardware's timing.

Checked as it runs, after every game frame (at the flip):
  - the text bitmap against the text list drawn from scratch (text.a's incremental redraw);
  - the CLUT against colour RAM (gfx.a ClutCommit);
  - that the bitmap shown holds exactly the frame's line records.

  python3 tools/osrun.py --seconds 60 --png DIR --every 100
"""

import argparse
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(__file__))
from cpu6809 import CPU6809, C  # noqa: E402
import avgview as av  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "src")
HZ = 8_000_000
TICK = HZ // 60
MODBASE = 0x6000
DATA = 0x0000
WINDOWS = [0x2000, 0x4000]          # logical slots F$MapBlk hands out
W, H = 320, 240

# OS-9 function codes (defs/os9.d)
F_EXIT, F_ICPT, F_SLEEP, F_TIME = 0x06, 0x09, 0x0A, 0x15
F_ALLRAM, F_MAPBLK, F_CLRBLK, F_DELRAM = 0x39, 0x4F, 0x50, 0x51
I_WRITE, I_GETSTT, I_SETSTT = 0x8A, 0x8D, 0x8E
SS_OPT, SS_JOY, SS_ASCRN, SS_DSCRN, SS_FSCRN, SS_PSCRN = 0x00, 0x13, 0x8B, 0x8C, 0x8D, 0x8E
SS_LIVEKEYS, SS_TICK, SS_CLUTWRITE, SS_MSDELTA = 0xC6, 0xC7, 0xCF, 0xD0
SS_WSIG, SS_BMBLK, SS_BMCLEAR, SS_BMLINE = 0xE1, 0xE4, 0xE5, 0xE7
E_UNKSVC, E_ILLARG = 208, 187


def symbols():
    out = {}
    for line in open(os.path.join(SRC, "tempest.map")):
        p = line.split()
        if len(p) >= 5 and p[0] == "Symbol:":
            out[p[1]] = int(p[4], 16)
    return out


class Exit(Exception):
    pass


class Host(CPU6809):
    def __init__(self, module, sym, script):
        super().__init__()
        self.sym = sym
        self.mem[MODBASE:MODBASE + len(module)] = module
        self.blocks = {}                        # physical block -> bytearray(8192)
        self.mapped = {}                        # logical base -> block
        self.next_ram = 0x40
        self.bm = {}                            # bitmap # -> first block
        self.layers = [None, None, None]
        self.clut = [(0, 0, 0, 0)] * 256
        self.script = script
        self.oscycles = 0
        self.calls = {}
        self.records = 0
        self.frame_records = []                 # this game frame's records, for the checks
        self.errors = []
        self.mode = None
        self.ms_delta = False
        self.has_tick = True
        self.cp = bytearray(32)             # the integer coprocessor (D8), as JR_Math_Block.v
        self.map_io(0xFEE0, 0xFEFF, self.cp_read, self.cp_write)

    def cp_read(self, a):
        if not self.cc & 0x10:
            self.errors.append("coprocessor $%04X read with IRQ unmasked" % a)
        return self.cp[a - 0xFEE0]

    def cp_write(self, a, v):
        if not self.cc & 0x10:
            self.errors.append("coprocessor $%04X written with IRQ unmasked" % a)
        r = self.cp
        r[a - 0xFEE0] = v
        r[0x10:0x14] = ((r[0] << 8 | r[1]) * (r[2] << 8 | r[3])).to_bytes(4, "big")
        den, num = r[4] << 8 | r[5], r[6] << 8 | r[7]
        q, m = (num // den, num % den) if den else (0xDEAD, 0xDEAD)     # undefined: loud
        r[0x14:0x18] = bytes((q >> 8, q & 0xFF, m >> 8, m & 0xFF))

    # --- time -------------------------------------------------------------------------------
    @property
    def tick(self):
        return self.cycles // TICK

    def cost(self, us):
        self.cycles += int(us * 8)

    # --- memory blocks ----------------------------------------------------------------------
    def block(self, b):
        return self.blocks.setdefault(b, bytearray(8192))

    def sync_out(self):
        """mapped windows -> their blocks (before the "driver" reads a block)"""
        for base, b in self.mapped.items():
            self.block(b)[:] = self.mem[base:base + 8192]

    def sync_in(self, b):
        """a block the driver wrote -> any window mapping it"""
        for base, bb in self.mapped.items():
            if bb == b:
                self.mem[base:base + 8192] = self.block(b)

    def bm_write(self, n, off, v):
        b = self.bm[n] + off // 8192
        self.block(b)[off % 8192] = v

    def bm_bytes(self, n):
        self.sync_out()
        return b"".join(bytes(self.block(self.bm[n] + i)) for i in range(10))[:W * H]

    # --- the os9 trap -------------------------------------------------------------------------
    def step(self):
        pc = self.pc
        if self.mem[pc] == 0x10 and self.mem[pc + 1] == 0x3F:
            fn = self.mem[pc + 2]
            self.pc = (pc + 3) & 0xFFFF
            self.calls[fn] = self.calls.get(fn, 0) + 1
            c0 = self.cycles
            err = self.os9(fn)
            self.oscycles += self.cycles - c0
            if err:
                self.b = err
                self.cc |= C
            else:
                self.cc &= ~C
            return
        super().step()

    def os9(self, fn):
        if fn == F_EXIT:
            raise Exit(self.b)
        if fn == F_ICPT:
            return 0
        if fn == F_SLEEP:
            n = self.x
            if n == 0:
                raise Exit("F$Sleep 0: asleep for ever")
            if n > 1:                       # n - 1 tick interrupts: X = 2 wakes at the next tick
                self.cycles = (self.tick + n - 1) * TICK
            return 0
        if fn == F_TIME:
            self.mem[self.x:self.x + 6] = bytes([126, 9, 23, 12, 34, 56])
            return 0
        if fn == F_ALLRAM:
            b = self.next_ram
            self.next_ram += self.b
            self.a, self.b = b >> 8, b & 0xFF
            return 0
        if fn == F_MAPBLK:
            if self.b != 1:
                return E_ILLARG
            free = [w for w in WINDOWS if w not in self.mapped]
            if not free:
                self.errors.append("F$MapBlk: no logical space (E$MemFul)")
                return 207
            base = free[0]
            self.mapped[base] = self.x
            self.mem[base:base + 8192] = self.block(self.x)
            self.u = base
            self.cost(220)
            return 0
        if fn == F_CLRBLK:
            base = self.u
            if base in self.mapped:
                self.block(self.mapped[base])[:] = self.mem[base:base + 8192]
                del self.mapped[base]
                self.mem[base:base + 8192] = bytes(8192)
            self.cost(220)
            return 0
        if fn == F_DELRAM:
            return 0
        if fn == I_WRITE:
            self.written = bytes(self.mem[self.x:self.x + self.y])
            return 0
        if fn in (I_GETSTT, I_SETSTT):
            return self.stat(fn == I_GETSTT, self.b)
        self.errors.append("unexpected os9 call $%02X" % fn)
        return E_UNKSVC

    def stat(self, get, code):
        self.cost(150)
        if code == SS_OPT:
            return 0
        if code == SS_DSCRN:
            if get:
                self.x, self.y = 0x0001, 0x00FF
            else:
                self.mode = (self.x, self.y)
            return 0
        if code == SS_WSIG and not get:
            return 0
        if code == SS_TICK and get:
            if not self.has_tick:
                return E_UNKSVC             # the driver as it is today
            self.x = self.tick & 0xFFFF
            return 0
        if code == SS_LIVEKEYS and get:
            sense, keys = self.script(self.tick)
            k = (list(keys) + [0] * 6)[:6]
            self.a = sense
            self.x, self.y, self.u = k[0] << 8 | k[1], k[2] << 8 | k[3], k[4] << 8 | k[5]
            return 0
        if code == SS_JOY and get:
            self.x = self.y = 0
            return 0
        if code == SS_MSDELTA:
            return E_UNKSVC                 # the driver does not have it yet
        self.cost(250)                      # the rest are grfdrv's
        n = self.y & 0xFF
        if code == SS_ASCRN and not get:
            if n > 2:
                return E_ILLARG
            self.bm[n] = 0x80 + 10 * n
            return 0
        if code == SS_BMBLK and get:
            self.x = self.bm[n]
            return 0
        if code == SS_BMCLEAR and not get:
            for i in range(10):
                self.block(self.bm[n] + i)[:] = bytes(8192)
                self.sync_in(self.bm[n] + i)
            self.cost(400)
            return 0
        if code == SS_PSCRN and not get:
            self.layers[self.x] = self.y
            if self.x == 1:
                self.flipped()
            return 0
        if code == SS_FSCRN and not get:
            return 0
        if code == SS_CLUTWRITE and not get:
            first, cnt = self.y & 0xFF, self.u
            for i in range(cnt):
                p = self.x + 4 * i
                self.clut[first + i] = tuple(self.mem[p:p + 4])
            return 0
        if code == SS_BMLINE and not get:
            cnt = self.u
            if not 1 <= cnt <= 255 or n > 2:
                return E_ILLARG
            for i in range(cnt):
                p = self.x + 8 * i
                x0, x1 = self.rd16(p), self.rd16(p + 2)
                y0, y1, col = self.mem[p + 4], self.mem[p + 5], self.mem[p + 6]
                if x0 > 319 or x1 > 319 or y0 > 239 or y1 > 239:
                    self.errors.append("SS.BmLine: a record off the bitmap (%d,%d)-(%d,%d)"
                                       % (x0, y0, x1, y1))
                    self.u = i
                    return E_ILLARG
                for (x, y) in av.bresenham(x0, y0, x1, y1):
                    self.bm_write(n, y * W + x, col)
                self.frame_records.append((x0, y0, x1, y1, col, n))
            for i in range(10):
                self.sync_in(self.bm[n] + i)
            self.records += cnt
            self.cost(474 + 27.5 * cnt - 250 - 150)
            self.u = cnt
            return 0
        self.errors.append("unexpected %s $%02X" % ("GetStat" if get else "SetStat", code))
        return E_UNKSVC

    # --- the checks, at every flip --------------------------------------------------------------
    def flipped(self):
        self.flips = getattr(self, "flips", 0) + 1
        self.pending_check = True

    def check(self):
        """At the end of a game frame (TxCommit done): the text bitmap, the CLUT, the lines."""
        sym, d = self.sym, DATA
        vwin = self.rd16(d + sym["VWIN"])
        ntxt = self.rd16(d + sym["AVGPG"] + sym["AV.TCNT"])
        texts = [bytes(self.mem[vwin + 0x1800 + 6 * i:vwin + 0x1806 + 6 * i]) for i in range(ntxt)]
        want = bytearray(W * H)
        for t in texts:
            g, clut = t[0], t[1]
            col, row = struct.unpack(">hh", t[2:6])
            gl = GLYPHS[(g & 0x7F) * 2 + (1 if g & 0x80 else 0)]
            gx, gy, gw, gh = gl[0], gl[1], gl[2], gl[3]
            for r in range(gh):
                bits = gl[4 + r]
                for c in range(gw):
                    if bits << c & 0x80:
                        x, y = col + gx + c, row + gy + r
                        if 0 <= x < W and 0 <= y < H:
                            want[y * W + x] = clut
        have = self.bm_bytes(2)
        bad = sum(1 for i in range(W * H) if have[i] != want[i])
        if bad:
            self.errors.append("frame %d: the text bitmap differs from its list in %d pixels"
                               % (self.flips, bad))
        cram = self.mem[d + sym["CLRSHD"]:d + sym["CLRSHD"] + 16]
        for i in range(256):
            r, g, b = clut_int(cram, i)
            if self.clut[i][:3] != (b, g, r):
                self.errors.append("frame %d: CLUT entry %d is %s, colour RAM says %s"
                                   % (self.flips, i, self.clut[i][:3], (b, g, r)))
                break
        shown = self.layers[1]
        lines = bytearray(W * H)
        for (x0, y0, x1, y1, col, n) in self.frame_records:
            if n == shown:
                for (x, y) in av.bresenham(x0, y0, x1, y1):
                    lines[y * W + x] = col
        if bytes(lines) != self.bm_bytes(shown):
            self.errors.append("frame %d: the bitmap shown is not exactly this frame's records"
                               % self.flips)
        self.frame_records = []
        prev = getattr(self, "prev_texts", [])
        changed = sum(1 for i in range(max(len(prev), len(texts)))
                      if i >= len(prev) or i >= len(texts) or prev[i] != texts[i])
        self.text_stats = getattr(self, "text_stats", []) + [(len(texts), changed)]
        self.prev_texts = texts

    def picture(self, path):
        lines, text = self.bm_bytes(self.layers[1]), self.bm_bytes(2)
        rows = []
        for y in range(H):
            row = bytearray([0])
            for x in range(W):
                i = text[y * W + x] or lines[y * W + x]
                b, g, r, _ = self.clut[i] if i else (0, 0, 0, 0)
                row += bytes((r, g, b))
            rows.append(bytes(row))

        def chunk(t, dd):
            c = struct.pack(">I", len(dd)) + t + dd
            return c + struct.pack(">I", zlib.crc32(t + dd) & 0xFFFFFFFF)
        png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))
        with open(path, "wb") as f:
            f.write(png)


def clut_int(cram, index):
    """gfx.a's CLUT entry: avgview's clut_rgb in integers (truncated)."""
    colour, inten = index >> 4, index & 0xF
    d = cram[colour]
    b3, b2, b1, b0 = (~d >> 3) & 1, (~d >> 2) & 1, (~d >> 1) & 1, ~d & 1
    r = b1 * 0xF3 + b0 * 0x0C
    g = b3 * 0xF3
    b = b2 * 0xF3
    return (r * inten // 15, g * inten // 15, b * inten // 15)


def load_glyphs():
    """GlyTab from src/glyphs.a, 15 bytes a record, as signed/unsigned values."""
    out = []
    for line in open(os.path.join(SRC, "glyphs.a")):
        if line.startswith("\tfcb\t"):
            v = [int(x.strip("$"), 16) for x in line.split("\t")[2].split(",")]
            v[0] = v[0] - 256 if v[0] > 127 else v[0]
            v[1] = v[1] - 256 if v[1] > 127 else v[1]
            out.append(v)
    return out


GLYPHS = load_glyphs()

KY_SHIFT, KY_LEFT, KY_RIGHT = 0x01, 0x20, 0x40


def script(tick):
    """Coin at 1 s, start at 3 s, then play: fire held on and off, the arrows by turns."""
    keys, sense = [], 0
    if 60 <= tick < 63:
        keys.append(ord("5"))
    if 180 <= tick < 190:
        keys.append(ord("1"))
    if tick >= 240:
        if (tick // 8) % 2:
            sense |= KY_SHIFT
        phase = (tick // 90) % 3
        sense |= (KY_LEFT, 0, KY_RIGHT)[phase]
        if tick % 1500 == 1000:
            keys.append(ord("z"))
    return sense, keys


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--png", help="write pictures here")
    ap.add_argument("--every", type=int, default=100, help="with --png, every n-th game frame")
    ap.add_argument("--no-tick", action="store_true", help="a driver without SS.Tick (the fallback)")
    a = ap.parse_args()
    module = open(os.path.join(SRC, "tempest"), "rb").read()
    sym = symbols()
    h = Host(module, sym, script)
    h.has_tick = not a.no_tick
    execoff = module[9] << 8 | module[10]
    h.u, h.dp, h.s = DATA, DATA >> 8, 0x2000
    h.x = h.y = 0x2000
    h.pc = MODBASE + execoff
    if a.png:
        os.makedirs(a.png, exist_ok=True)
    gamfrm = MODBASE + sym["GamFrm"]
    irq = MODBASE + sym["IRQ"]
    nirq = 0
    avgrun = MODBASE + sym["AvgRun"]
    txcommit = MODBASE + sym["TxCommit"]
    ret = None                      # GamFrm's return address and S there
    marks = {}
    frames = []                     # per game frame: (total, game, avg incl. its flushes, text)
    end = int(a.seconds * HZ)
    status = "ran %.1f s" % a.seconds
    try:
        while h.cycles < end:
            pc = h.pc
            if pc == irq:
                nirq += 1
            if pc == gamfrm:
                ret = (h.rd16(h.s), h.s + 2)
                marks = {"start": h.cycles}
            elif ret and pc == avgrun:
                marks["avg"] = h.cycles
            elif ret and pc == txcommit:
                marks["text"] = h.cycles
            elif ret and pc == ret[0] and h.s == ret[1]:
                t = h.cycles
                frames.append((t - marks["start"], marks["avg"] - marks["start"],
                               marks["text"] - marks["avg"], t - marks["text"]))
                h.check()
                n = len(frames)
                if a.png and n % a.every == 0:
                    h.picture(os.path.join(a.png, "frame%05d.png" % n))
                ret = None
            h.step()
    except Exit as e:
        status = "exit: %s" % (e,)
    print(status)
    print("virtual IRQs %d (%.1f a second; the arcade's 246.1)" % (nirq, nirq / max(h.cycles / HZ, 1e-9)))
    print("ticks %d, game frames %d (%.1f a second), os9 calls %s" % (
        h.tick, len(frames), len(frames) / max(h.cycles / HZ, 1e-9),
        ", ".join("$%02X x%d" % kv for kv in sorted(h.calls.items()))))
    if frames:
        def pct(v, q):
            v = sorted(v)
            return v[min(len(v) - 1, int(q * len(v)))]
        for name, k in (("frame", 0), ("game (clear, EXSTAT, NONSTA, DISPLA)", 1),
                        ("AvgRun with SS.BmLine, flip, CLUT", 2), ("text", 3)):
            v = [f[k] / 8000 for f in frames]
            print("  %-40s median %5.1f ms, 95%% %5.1f, max %5.1f" % (name, pct(v, .5), pct(v, .95), max(v)))
        print("  line records %d (%.0f a frame)" % (h.records, h.records / len(frames)))
        ts = h.text_stats
        print("  texts a frame: median %d; changed entries: median %d, mean %.1f, frames with none %d%%"
              % (pct([t[0] for t in ts], .5), pct([t[1] for t in ts], .5),
                 sum(t[1] for t in ts) / len(ts), 100 * sum(1 for t in ts if not t[1]) // len(ts)))
    if h.errors:
        print("%d problems:" % len(h.errors))
        for e in h.errors[:20]:
            print("  " + e)
        sys.exit(1)
    print("checks: text bitmap, CLUT and line bitmap right after every game frame")


if __name__ == "__main__":
    main()
