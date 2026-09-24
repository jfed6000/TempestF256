#!/usr/bin/env python3
"""sndtest.py - tsnd ("tempest s", src/sound.a) on the host 6809: the output stage's host test.

Runs the module as osrun.py does, with "s" as its parameters, presses r (the sequence: each of the
13 sounds alone, then two pairs) and taps every write into the SIDs' I/O block ($C4, mapped through
the service window).  After each pass (at its F$Sleep) it checks the SIDs against the POKEY image
(POKIMG) that ALSOUN's MODSND wrote, by sound.a's mapping:

  - every POKEY channel sounding (AUDC volume 1-15, bit 4 clear) has one voice, gated, with the
    waveform (pulse for AUDC $Ax/$Ex, noise otherwise), the frequency (59,319 / (AUDF+1), and 8
    times that, held to $FFFF, for a pulse) and the sustain level (the volume) it should;
  - no other voice is gated; no channel went without a voice (six are enough, docs/status.md);
  - each SID's master volume is $0F, and every pulse width 50%.

Also counts re-gates (a louder volume or a new waveform) and prints, per step of the sequence, the
channels that sounded.  It proves the mapping and the bookkeeping, not how it sounds.

With --game it runs the game instead ("tempest", played by osrun.py's script) and makes the same
checks every pass: the game's own sounds, through the main loop's SndOut.

tsnd is only in a module built with TSND: this script assembles one into src/build/ (the
makefile's command, -DTSND), leaving src/tempest alone; --game runs src/tempest.

  python3 tools/sndtest.py [--seconds 45] [--game]
"""

import argparse
import collections
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
import osrun  # noqa: E402
from osrun import Host, Exit, MODBASE, DATA, SRC, HZ, TICK  # noqa: E402

SS_READY, E_NOTRDY = 0x01, 246
I_READ = 0x89
SIDBLK = 0xC4
POKIMG = 0x0800


class SndHost(Host):
    def __init__(self, *a, keys=()):
        super().__init__(*a)
        self.keys = dict(keys)              # tick -> the key pressed then
        self.pending = []
        self.sid = bytearray(0x200)
        self.sidbase = None                 # the window the SIDs were last mapped into
        self.taps = set()
        self.writes = 0
        self.gates_off_on = 0
        self.gate_seen_low = [False] * 6
        self.remaps = 0

    def os9(self, fn):
        if fn == I_READ:
            if not self.pending:
                return E_NOTRDY
            self.mem[self.x] = ord(self.pending.pop(0))
            self.y = 1
            return 0
        if fn == osrun.F_SLEEP and self.x == 2:
            k = self.keys.pop(self.tick, None)
            if k:
                self.pending.append(k)
        return super().os9(fn)

    def on_map(self, base, block):
        """the MMU put a block in a window's slot (sound.a SidOn): tap the SIDs there"""
        if block != SIDBLK:
            return
        self.sidbase = base
        self.remaps += 1
        if base not in self.taps:
            self.taps.add(base)
            self.map_io(base, base + 0x1FF, lambda a, b=base: self.sid_r(a, b),
                        lambda a, v, b=base: self.sid_w(a, v, b))

    def stat(self, get, code):
        if get and code == SS_READY:
            return 0 if self.pending else E_NOTRDY
        return super().stat(get, code)

    def sid_here(self, base):
        return self.mapped.get(base) == SIDBLK

    def sid_r(self, a, base):
        return self.sid[a - base] if self.sid_here(base) else self.mem[a]

    def sid_w(self, a, v, base):
        if not self.sid_here(base):         # the window holds another block now (the text's)
            self.mem[a] = v
            return
        off = a - base
        self.writes += 1
        if off < 0x80 or 0x100 <= off < 0x180:
            chip, r = off >> 8, off & 0x7F
            if r < 21 and r % 7 == 4:
                v_ = chip * 3 + r // 7
                if not v & 1:
                    self.gate_seen_low[v_] = True
                elif self.sid[off] & 1 == 0 and self.gate_seen_low[v_]:
                    self.gates_off_on += 1
        self.sid[off] = v
        self.mem[a] = v

    def voice(self, v):
        base = (v // 3) * 0x100 + (v % 3) * 7
        r = self.sid[base:base + 7]
        return {"freq": r[0] | r[1] << 8, "pw": r[2] | (r[3] & 15) << 8, "ctl": r[4], "ad": r[5],
                "sr": r[6]}


NITROS9DIR = os.environ.get("NITROS9DIR", "/home/magnus/projects/wild/joust/nitros9_complete/nitros9")


def build_tsnd():
    """src/build/tempest.tsnd: the module with TSND, as the makefile assembles it"""
    out = os.path.join(SRC, "build")
    os.makedirs(out, exist_ok=True)
    mod, mp = os.path.join(out, "tempest.tsnd"), os.path.join(out, "tempest.tsnd.map")
    r = subprocess.run(["lwasm.orig", "--6809", "--format=os9",
                        "--pragma=nosymbolcase,condundefzero,dollarnotlocal",
                        "--includedir=%s/defs" % NITROS9DIR, "-I", "%s/level2/wildbits" % NITROS9DIR,
                        "-I", ".", "-Dwildbits=1", "-DTSND", "--map=" + mp, "-o", mod, "tempest.asm"],
                       cwd=SRC, capture_output=True, text=True)
    if r.returncode:
        sys.exit((r.stdout + r.stderr)[-3000:] + "\nthe TSND build failed")
    sym = {}
    for line in open(mp):
        p = line.split()
        if len(p) >= 5 and p[0] == "Symbol:":
            sym[p[1]] = int(p[4], 16)
    return open(mod, "rb").read(), sym


def want(audf, audc):
    """the voice sound.a should give a POKEY channel, or None if it is silent"""
    vol = audc & 15
    if audc & 0x10 or not vol:
        return None
    n = 59319 // (audf + 1)
    if audc >> 5 in (5, 7):
        return {"ctl": 0x41, "freq": 0xFFFF if n >= 0x2000 else n * 8, "sr": vol << 4}
    return {"ctl": 0x81, "freq": n, "sr": vol << 4}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=45)
    ap.add_argument("--game", action="store_true", help="the game, not tsnd")
    a = ap.parse_args()
    if a.game:
        module = open(os.path.join(SRC, "tempest"), "rb").read()
        sym = osrun.symbols()
    else:
        module, sym = build_tsnd()
    h = SndHost(module, sym, osrun.script, keys={} if a.game else {30: "r"})
    execoff = module[9] << 8 | module[10]
    h.u, h.dp, h.s = DATA, DATA >> 8, 0x2000
    h.mem[0x1F00:0x1F02] = b"\r\r" if a.game else b"s\r"      # the parameters
    h.x, h.y = 0x1F00, 0x2000
    h.pc = MODBASE + execoff
    checked = bad = deferred = 0
    maxvoices = 0
    steps = collections.OrderedDict()
    fails = []
    end = int(a.seconds * HZ)
    try:
        while h.cycles < end:
            pc = h.pc
            if h.mem[pc] == 0x10 and h.mem[pc + 1] == 0x3F and h.mem[pc + 2] == osrun.F_SLEEP \
                    and h.x in (0, 2) and h.sidbase is not None:     # a pass's end (0: the SOL clock)
                checked += 1
                img = h.mem[DATA + POKIMG:DATA + POKIMG + 16]
                seq = 0 if a.game else h.mem[DATA + sym["TSSEQ"]]
                gated = {v for v in range(6) if h.voice(v)["ctl"] & 1}
                wanted = {}
                for c in range(8):
                    w = want(img[2 * c], img[2 * c + 1])
                    if w:
                        wanted[c] = w
                        steps.setdefault(seq, set()).add(c)
                maxvoices = max(maxvoices, len(wanted))
                matched = set()
                errs = []
                for c, w in wanted.items():
                    hit = [v for v in gated - matched
                           if all(h.voice(v)[k] == w[k] for k in ("ctl", "freq", "sr"))]
                    if not hit:
                        errs.append("channel %d (AUDF %02X AUDC %02X): no voice with %s" %
                                    (c, img[2 * c], img[2 * c + 1], w))
                    else:
                        matched.add(hit[0])
                if gated - matched:
                    errs.append("voices gated with no channel: %s" % sorted(gated - matched))
                for chip in (0, 0x100):
                    if h.sid[chip + 0x18] != 0x0F:
                        errs.append("a SID's volume is %02X" % h.sid[chip + 0x18])
                if any(h.voice(v)["pw"] != 0x800 for v in range(6)):
                    errs.append("a pulse width is not 50%")
                if errs:
                    bad += 1
                    if len(fails) < 10:
                        fails.append("tick %d: %s" % (h.tick, "; ".join(errs)))
            h.step()
    except Exit as e:
        print("exit: %s" % (e,))
    print("ran %.1f s: %d passes checked, %d wrong; %d SID writes; %d re-gates; at most %d channels"
          " at once; SidOn %d times" % (h.cycles / HZ, checked, bad, h.writes, h.gates_off_on,
                                                 maxvoices, h.remaps))
    if deferred:
        print("passes that ended with the text in the window (not checked): %d" % deferred)
    for f in fails:
        print("  " + f)
    print("channels that sounded, per step of the sequence (TSSEQ offset: channels):")
    for s, cs in steps.items():
        print("  %3d: %s" % (s, sorted(cs)))
    if h.errors:
        print("errors:", h.errors[:5])
    sys.exit(1 if bad or h.errors else 0)


if __name__ == "__main__":
    main()
