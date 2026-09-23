#!/usr/bin/env python3
"""romalign.py - align every statement of the game's source with the Rev 3 program ROM.

The ROM rebuilds byte-identical from this source, so once each statement is matched to its place in
the ROM, the ROM supplies everything the source alone cannot: the address of every label (code and
data), the bytes that macros emit (the sound offsets, the cam bytecode, the messages, ALCOIN's code),
and the values of macro-made symbols.  The translator (m65to09.py) and the differential tests take
their addresses and data from here.

How: the files are linked in a fixed order (ALEXEC.MAP: ALWELG absolute at $9000, then ALSCO2,
ALDIS2, ALEXEC, ALSOUN, ALVROM's CPU part, ALCOIN, ALLANG, ALHAR2, ALTES2, ALEARO, ALVGUT, each
following the last).  Each file is cut into runs of statements whose bytes are known in shape - an
instruction's opcode and any operand that evaluates, HLL65 as HLL65.MAC assembles it, .BYTE/.WORD
with their values, .BLKB - separated by statements of unknown length (macro calls).  A run must
start exactly where the last one ended, or after a gap, within a bound, if a macro call came between.

    romalign.py              align all files, report coverage and each file's range
    romalign.py --dump F     print F's statements with their addresses and bytes
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
import m65parse                                   # noqa: E402
import romfind                                    # noqa: E402
from cpu6502 import CPU6502, load_rev3            # noqa: E402

LINK = ["ALWELG", "ALSCO2", "ALDIS2", "ALEXEC", "ALSOUN", "ALVROM", "ALCOIN", "ALLANG", "ALHAR2",
        "ALTES2", "ALEARO", "ALVGUT"]
ROM_LO, ROM_HI = 0x9000, 0xE000
GAP_PER_MACRO = 96
# Section sizes from ALEXEC.MAP for files that end in macro calls (ALVROM) or are nothing but an
# included macro package (ALCOIN = COIN65), so their ends cannot be found from their own bytes.
# Both files are the same in Rev 1 and Rev 3.
KNOWN_SIZE = {"ALVROM": 0x146, "ALCOIN": 0x10D}
# Macros whose size follows from their definition (ALCOMN, ALDIS2, ALEARO, ALSOUN): exact widths.
MACRO_SIZE = {"MINDX": 1, "ROML": 2, "LAH": 2, "LXL": 2, "LDAH": 2, "LDAL": 2, "OFFSET": 16,
              # ALVROM's CPU-side tables: a score-template offset byte, AVG words
              "SCOF": 1, "JMPL": 2, "PITAB": 2, "JSRL": 2,
              # AVG instructions (VGMC.MAC): one word each; VCTR's size is computed below
              "SCAL": 2, "CNTR": 2, "STAT": 2, "CSTAT": 2, "RTSL": 2, "HALT": 2}


def vctr_size(dx, dy):
    """VGMC.MAC VCTR: the short form (one word) when both deltas are even and within 30 and not
    both zero; otherwise the long form (two words)."""
    a, b = abs(dx), abs(dy)
    if a + b != 0 and ((a | b) & 0xFFE1) == 0:
        return 2
    return 4
ANY = romfind.ANY
DOT = r"(?<![A-Za-z0-9_$.])\.(?![A-Za-z0-9_$.])"      # the location counter, not a name's dot


def split_args(s):
    """Comma-separated operands, commas inside <...> kept."""
    out, depth, cur = [], 0, ""
    for c in s:
        if c == "<":
            depth += 1
        elif c == ">" and depth:
            depth -= 1
        if c == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += c
    if cur.strip() or out:
        out.append(cur)
    return [x.strip() for x in out]


class Item:
    """One statement's contribution to the ROM: a regex over its bytes, or None if unknown."""
    __slots__ = ("line", "pat", "gap", "labels", "addr", "size", "dotexpr")

    def __init__(self, line, pat=None, gap=0):
        self.line, self.pat, self.gap = line, pat, gap
        self.labels = []
        self.addr = self.size = None
        self.dotexpr = None


class Aligner:
    def __init__(self, cpu=None):
        self.cpu = cpu or load_rev3(CPU6502())
        self.rom = bytes(self.cpu.mem[0:0x10000])
        # Each file was a separate assembly with its own symbol table (ALCOMN included in each),
        # so each gets its own parser.
        self.parsers, self.lines, self.unstable = {}, {}, {}
        for f in LINK:
            p = m65parse.Parser()
            self.parsers[f] = p
            self.lines[f] = p.parse(os.path.join(p.srcdir, f + ".MAC"))
            # Symbols assigned more than once (macro counters like ...RPC) cannot be trusted at a
            # later line: their bytes come from the ROM.
            count = {}
            for ln in self.lines[f]:
                if ln.kind == "assign" and not ln.dead:
                    k = m65parse.sym6(ln.sym)
                    count[k] = count.get(k, 0) + 1
            self.unstable[f] = {k for k, n in count.items() if n > 1}
        self.p = None
        self.labels = {}                # name -> ROM address (code and data labels)
        self.addr_of_line = {}          # (file, lineno) -> (addr, size)
        self.ranges = {}

    def value(self, expr, radix):
        toks = re.findall(r"[A-Za-z_.$][A-Za-z0-9_.$]*", expr)
        if any(m65parse.sym6(t) in self.unstable[self.cur] for t in toks):
            return None
        ev = self.p.ev
        saved = ev.radix
        ev.radix = radix
        try:
            return ev.value(expr)
        finally:
            ev.radix = saved

    def items(self, f):
        """The file's live statements that occupy ROM, with the labels that precede each."""
        self.cur, self.p = f, self.parsers[f]
        out, pending, in_asect = [], [], False
        rept = []                               # stack of (count, start index in out)
        for ln in self.lines[f]:
            if ln.dead:
                continue
            if ln.kind == "directive" and (ln.op or "").upper() == ".REPT":
                rept.append((self.value(ln.operand or "", ln.radix), len(out)))
                continue
            if ln.kind == "directive" and (ln.op or "").upper() == ".ENDR" and rept:
                n, at = rept.pop()
                body = out[at:]
                if n is None:
                    for it in body:
                        it.pat, it.gap = None, GAP_PER_MACRO
                else:
                    del out[at:]
                    for k in range(n):
                        for it in body:
                            c = Item(it.line, it.pat, it.gap)
                            c.labels = it.labels if k == 0 else []
                            c.dotexpr = it.dotexpr
                            out.append(c)
                continue
            if ln.kind == "directive" and (ln.op or "").upper() in (".ASECT", ".CSECT", ".PSECT"):
                in_asect = (ln.op or "").upper() == ".ASECT"
                asect_rom = False
                continue
            if in_asect and ln.kind == "assign" and ln.sym == ".":
                v = self.value(ln.operand or "", ln.radix)
                asect_rom = v is not None and ROM_LO <= v < 0x10000
                continue
            if in_asect and not asect_rom:
                continue                        # RAM, or vector ROM at $3000: not the program ROM
            pending += [m65parse.sym6(x.split()[0]) for x in ln.labels]
            it = None
            if ln.kind == "insn":
                ln_ev = self.p.ev
                saved = ln_ev.radix
                ln_ev.radix = ln.radix
                try:
                    it = Item(ln, romfind.insn_pattern(ln, ln_ev))
                finally:
                    ln_ev.radix = saved
            elif ln.kind == "hll":
                h = ln.op
                if h in romfind.IFBR:
                    it = Item(ln, romfind.b(romfind.CODE[(romfind.IFBR[h], "rel")]) + ANY)
                elif h == "ELSE":
                    it = Item(ln, romfind.b(0xB8) + romfind.b(0x50) + ANY)
                elif h in romfind.ENDBR:
                    br = romfind.ENDBR[h]
                    it = Item(ln, b"(?:" + romfind.b(romfind.CODE[(br, "rel")]) + ANY + b"|" +
                              romfind.b(romfind.CODE[(romfind.INVERSE[br], "rel")]) + romfind.b(3) +
                              romfind.b(0x4C) + ANY + ANY + b")")
                else:
                    it = Item(ln, b"")          # BEGIN, ENDIF, THEN: no bytes
            elif ln.kind == "directive":
                op = (ln.op or "").upper()
                rest = ln.operand or ""
                if op.startswith(".BYTE") and op != ".BYTE":
                    rest, op = op[5:] + (rest and " " + rest), ".BYTE"
                if op == ".BYTE":
                    pat = b""
                    for a in split_args(rest):
                        v = self.value(a, ln.radix) if a else 0
                        pat += ANY if v is None else romfind.b(v)
                    it = Item(ln, pat)
                elif op == ".WORD":
                    pat = b""
                    for a in split_args(rest):
                        v = self.value(a, ln.radix)
                        pat += ANY + ANY if v is None else romfind.b(v) + romfind.b(v >> 8)
                    it = Item(ln, pat)
                elif op == ".":
                    it = Item(ln, ANY + ANY)    # an expression statement is a .WORD (ALDIS2:1033)
                elif op == ".BLKB":
                    n = self.value(rest, ln.radix)
                    it = Item(ln, ANY * n) if n is not None else Item(ln, None, GAP_PER_MACRO)
                elif op in (".ASCVG", ".VCTRS") or (op.startswith(".") and op[1:] in self.p.macros):
                    it = Item(ln, None, GAP_PER_MACRO)
            elif ln.kind == "macro" and ln.op in MACRO_SIZE:
                it = Item(ln, ANY * MACRO_SIZE[ln.op])
            elif ln.kind == "macro" and ln.op == "VCTR":
                args = split_args(ln.operand or "")
                dx = self.value(args[0], ln.radix) if len(args) > 1 else None
                dy = self.value(args[1], ln.radix) if len(args) > 1 else None
                it = Item(ln, ANY * vctr_size(dx, dy)) if dx is not None and dy is not None \
                    else Item(ln, None, GAP_PER_MACRO)
            elif ln.kind == "macro" and ln.op not in ("HLL65",):
                it = Item(ln, None, GAP_PER_MACRO)
            elif ln.kind == "assign" and ln.operand and re.search(DOT, ln.operand):
                # SOUND=.-6: a symbol defined from the location counter
                it = Item(ln, b"")
                it.dotexpr = (ln.sym, ln.operand)
            if it is not None:
                it.labels, pending = pending, []
                out.append(it)
        if pending:
            it = Item(None, b"")
            it.labels = pending
            out.append(it)
        return out

    @staticmethod
    def place_gap(gap_items, lo, hi):
        """Addresses for statements between two anchors: zero-length ones (labels, ENDIF) before the
        first macro call at lo, after the last at hi; the macro calls share lo..hi, the last one
        holding the whole span (their individual sizes are not known)."""
        macros = [n for n, it in enumerate(gap_items) if it.pat is None]
        for n, it in enumerate(gap_items):
            if it.pat is not None:
                if not macros or n < macros[0]:
                    it.addr = lo
                elif n > macros[-1]:
                    it.addr = hi
                else:
                    it.addr = lo                # between macro calls: position unknown
                it.size = 0
            else:
                it.addr, it.size = lo, 0
        if macros:
            gap_items[macros[-1]].size = hi - lo

    def align_file(self, f, start, gap_before=0):
        items = self.items(f)
        pos = start
        k = 0
        gap = gap_before
        gap_items = []
        while k < len(items):
            if items[k].pat is None:
                gap += items[k].gap
                gap_items.append(items[k])
                k += 1
                continue
            j = k
            while j < len(items) and items[j].pat is not None:
                j += 1
            run = items[k:j]
            if gap and all(re.fullmatch(rb"(?:\(\?s:\.\))*", it.pat) for it in run):
                # labels, or bytes of any value, cannot anchor a gap: they would match at its start
                for it in run:
                    if it.pat:
                        it.gap, it.pat = len(it.pat) // len(ANY), None
                gap_items += run
                gap += sum(it.gap for it in run if it.pat is None)
                k = j
                continue
            pat = b"".join(b"(?P<i%d>)" % n + it.pat for n, it in enumerate(run))
            rx = re.compile(pat)
            if gap:
                m = rx.search(self.rom, pos, min(ROM_HI, pos + gap + 4096))
                if m and m.start() - pos > gap:
                    m = None
            else:
                m = rx.match(self.rom, pos)
            if not m:
                good = 0
                for n in range(1, len(run) + 1):
                    sub = re.compile(b"".join(it.pat for it in run[:n]))
                    mm = sub.match(self.rom, pos) if not gap else sub.search(
                        self.rom, pos, min(ROM_HI, pos + gap + 4096))
                    if not mm:
                        break
                    good = n
                bad = run[good].line if good < len(run) else run[0].line
                raise LookupError("%s: run from line %s matches up to line %s: %r" % (
                    f, run[0].line.no if run[0].line else "?", bad.no if bad else "?",
                    bad.text.strip() if bad else ""))
            if gap_items:
                self.place_gap(gap_items, pos, m.start())
            for n, it in enumerate(run):
                it.addr = m.start("i%d" % n)
            for n, it in enumerate(run):
                end = run[n + 1].addr if n + 1 < len(run) else m.end()
                it.size = end - it.addr
            pos = m.end()
            gap, gap_items = 0, []
            k = j
        self.pending_tail = gap_items
        for it in gap_items:
            it.addr, it.size = pos, 0
        return items, pos

    def run(self):
        pos = 0x9000
        self.files = {}
        prev_tail = []
        for f in LINK:
            items, end = self.align_file(f, pos, GAP_PER_MACRO * 4 if prev_tail else 0)
            first = next((it for it in items if it.pat is not None and it.addr is not None), None)
            if prev_tail and first is not None:
                self.place_gap(prev_tail, prev_tail[0].addr, first.addr)
                self.ranges[prev_f] = (self.ranges[prev_f][0], first.addr)
            tail = self.pending_tail
            if f in KNOWN_SIZE:
                known = pos + KNOWN_SIZE[f]
                if tail:
                    self.place_gap(tail, end, known)
                elif end != known and any(it.pat for it in items):
                    raise LookupError("%s ends at $%04X, the map says $%04X" % (f, end, known))
                end, tail = known, []
            self.files[f] = items
            self.ranges[f] = (pos, end)
            prev_tail, prev_f = tail, f
            pos = end
        self.flabels = {}               # (file, name) -> address: labels are private to a file
        for f, items in self.files.items():
            for it in items:
                for lab in it.labels:
                    self.labels.setdefault(lab, it.addr)
                    self.flabels.setdefault((f, lab), it.addr)
                if it.line is not None:
                    self.addr_of_line[(f, it.line.no)] = (it.addr, it.size)
                if it.dotexpr:
                    sym, expr = it.dotexpr
                    p = self.parsers[f]
                    p.syms["."] = it.addr
                    v = p.ev.value(expr)
                    p.syms.pop(".", None)
                    if v is not None:
                        self.labels[m65parse.sym6(sym)] = v
        self.resolve_by_reference()
        self.ambiguous = set()
        for f, items in self.files.items():
            for n, it in enumerate(items):
                inside = (it.pat is None and n > 0 and items[n - 1].pat is None) or (
                    it.pat == b"" and n > 0 and items[n - 1].pat is None and n + 1 < len(items)
                    and items[n + 1].pat is None)
                for lab in it.labels:
                    if inside:
                        if lab in self.by_reference and lab not in self.clash:
                            self.labels[lab] = self.by_reference[lab]
                            self.flabels[(f, lab)] = self.by_reference[lab]
                        else:
                            self.ambiguous.add(lab)
        return self

    def resolve_by_reference(self):
        """Labels inside runs of macro calls have no address of their own; wherever an aligned
        absolute operand or .WORD names one (LABEL or LABEL+n), the ROM holds its address."""
        found, clash = {}, set()
        for f, items in self.files.items():
            p = self.parsers[f]
            for it in items:
                ln = it.line
                if ln is None or it.size is None or it.pat is None:
                    continue
                exprs = []
                if ln.kind == "insn" and it.size == 3 and ln.op not in ("JMP", "JSR") and ln.operand:
                    o = ln.operand
                    for pre, _ in m65parse.MODES:
                        if o.upper().startswith(pre):
                            o = o[len(pre):]
                            break
                    exprs.append((o, it.addr + 1))
                elif ln.kind == "directive" and (ln.op or "").upper() == ".WORD":
                    for n, a in enumerate(split_args(ln.operand or "")):
                        exprs.append((a, it.addr + 2 * n))
                for e, at in exprs:
                    m = re.fullmatch(r"\s*([A-Za-z_.$][A-Za-z0-9_.$]*)\s*(?:([+-])\s*([0-9A-Fa-f]+)(\.?))?\s*", e)
                    if not m:
                        continue
                    name = m65parse.sym6(m.group(1))
                    off = 0
                    if m.group(2):
                        off = int(m.group(3), 10 if m.group(4) else 16) * (1 if m.group(2) == "+" else -1)
                    v = (self.rom[at] | self.rom[at + 1] << 8) - off
                    if name in found and found[name] != v:
                        clash.add(name)
                    found[name] = v
        self.by_reference = found
        self.clash = clash
        return found

    def bytes_at(self, addr, n):
        return self.rom[addr:addr + n]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump")
    a = ap.parse_args()
    al = Aligner().run()
    if a.dump:
        for it in al.files[a.dump.upper()]:
            ln = it.line
            by = al.bytes_at(it.addr, it.size or 0).hex() if it.size else ""
            print("%04X %-24s %s%s" % (it.addr, by[:24], (" ".join(it.labels) + ": ") if it.labels else "",
                                       ln.text.strip()[:70] if ln else ""))
        return
    total = 0
    for f in LINK:
        lo, hi = al.ranges[f]
        gaps = sum(it.size or 0 for it in al.files[f] if it.pat is None)
        total += hi - lo
        print("%-7s $%04X-$%04X %5d bytes, %4d from macro calls" % (f, lo, hi - 1, hi - lo, gaps))
    print("aligned $9000-$%04X, %d bytes; %d labels" % (al.ranges[LINK[-1]][1] - 1, total, len(al.labels)))
    # every label an aligned reference names must agree with the alignment where both know it
    bad = [(k, al.labels[k], v) for k, v in al.by_reference.items()
           if k in al.labels and k not in al.ambiguous and al.labels[k] != v and ROM_LO <= v < ROM_HI]
    print("labels checked against references: %d agree, %d disagree %s" % (
        sum(1 for k, v in al.by_reference.items() if k in al.labels and al.labels[k] == v), len(bad), bad[:5]))
    print("labels inside macro data with no address: %d %s" % (len(al.ambiguous), sorted(al.ambiguous)[:12]))
    for k in ("WORSCR", "MODSND", "FSNDON", "DSPNYM", "VGSTAT", "VGYAB1", "MOVCUR", "SOUND", "PNTRS"):
        print("  %-7s $%04X" % (k, al.labels[k]))


if __name__ == "__main__":
    main()
