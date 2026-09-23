#!/usr/bin/env python3
"""romfind.py - find a routine of the MAC65 source in the Rev 3 program ROM (D6 pilot).

ALEXEC.MAP was linked from the Rev 1 names, so it does not give Rev 3 addresses, and most labels are
not global anyway.  This builds a byte pattern from the source with m65parse - each instruction's
opcode for its addressing mode, operand bytes where the operand evaluates (RAM and constants) and
wildcards where it does not (code labels), HLL65 structures expanded as HLL65.MAC assembles them -
and searches the ROM for it.  A unique match gives the address of every label in the stretch.

    romfind.py ALDIS2 WORSCR [--count 60]
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
import m65parse                                     # noqa: E402
from cpu6502 import OPS, CPU6502, load_rev3         # noqa: E402

CODE = {(mn, mode): op for op, (mn, mode, _) in OPS.items()}
INVERSE = {"BCC": "BCS", "BCS": "BCC", "BEQ": "BNE", "BNE": "BEQ", "BMI": "BPL", "BPL": "BMI",
           "BVC": "BVS", "BVS": "BVC"}
# HLL65: IFxx assembles the branch that skips the block; xxEND ("end when xx") the branch back to
# BEGIN while not xx, or when that is out of range, the inverse branch over a JMP back.
IFBR = {"IFCC": "BCS", "IFCS": "BCC", "IFEQ": "BNE", "IFNE": "BEQ", "IFMI": "BPL", "IFPL": "BMI",
        "IFVC": "BVS", "IFVS": "BVC"}
ENDBR = {"CCEND": "BCS", "CSEND": "BCC", "EQEND": "BNE", "NEEND": "BEQ", "MIEND": "BPL",
         "PLEND": "BMI", "VCEND": "BVS", "VSEND": "BVC"}
PREFIX = [p for p, _ in m65parse.MODES]


def b(x):
    return re.escape(bytes([x & 0xFF]))


ANY = b"(?s:.)"


def insn_pattern(ln, ev):
    mn, mode, opnd = ln.op, ln.mode, ln.operand or ""
    o = opnd
    for p in PREFIX:
        if o.upper().startswith(p):
            o = o[len(p):]
            break
    v = ev.value(o) if o else None
    if mode == "implied":
        if (mn, "acc") in CODE:
            return b(CODE[(mn, "acc")])
        return b(CODE[(mn, "imp")])
    if mode == "rel":
        return b(CODE[(mn, "rel")]) + ANY
    if mode == "imm":
        return b(CODE[(mn, "imm")]) + (b(v) if v is not None else ANY)
    if mode in ("(zp),Y", "(zp,X)"):
        m6 = "izy" if mode == "(zp),Y" else "izx"
        return b(CODE[(mn, m6)]) + (b(v) if v is not None else ANY)
    forced = {"abs,X!": "abx", "abs,Y!": "aby", "zp,X!": "zpx", "zp,Y!": "zpy", "zp!": "zp",
              "abs!": "abs"}
    if mode in forced:
        m6 = forced[mode]
    else:
        zpm, absm = {"abs/zp": ("zp", "abs"), ",X": ("zpx", "abx"), ",Y": ("zpy", "aby")}[mode]
        if mn in ("JMP", "JSR"):
            zpm = None
        use_zp = v is not None and 0 <= v < 0x100 and (mn, zpm) in CODE
        m6 = zpm if use_zp else absm
    op = CODE[(mn, m6)]
    if m6 in ("zp", "zpx", "zpy"):
        return b(op) + (b(v) if v is not None else ANY)
    if v is None:
        return b(op) + ANY + ANY
    return b(op) + b(v) + b(v >> 8)


def pattern(lines, start_label, count, ev):
    """Regex over ROM bytes for `count` statements from start_label; named groups for labels."""
    i = next(k for k, l in enumerate(lines)
             if any(x.split()[0] == start_label for x in l.labels) and not l.dead)
    parts, labels, n = [], [], 0
    while i < len(lines) and n < count:
        ln = lines[i]
        i += 1
        if ln.dead:
            continue
        for lab in ln.labels:
            name = lab.split()[0]
            g = "L%d" % len(labels)
            labels.append(name)
            parts.append(b"(?P<%s>)" % g.encode())
        if ln.kind == "insn":
            parts.append(insn_pattern(ln, ev))
            n += 1
        elif ln.kind == "hll":
            h = ln.op
            if h in IFBR:
                parts.append(b(CODE[(IFBR[h], "rel")]) + ANY)
            elif h == "ELSE":
                parts.append(b(0xB8) + b(CODE[("BVC", "rel")]) + ANY)
            elif h in ENDBR:
                br = ENDBR[h]
                parts.append(b"(?:" + b(CODE[(br, "rel")]) + ANY + b"|" +
                             b(CODE[(INVERSE[br], "rel")]) + b(3) + b(0x4C) + ANY + ANY + b")")
            n += 1
        elif ln.kind in ("macro", "directive") and ln.op not in (".PAGE", ".SBTTL", ".LIST",
                                                                   ".NLIST", ".GLOBL"):
            break
    return b"".join(parts), labels


def diagnose(lines, label, count, ev, rom):
    """Where a pattern stops matching: the first statement count with no hit, and the source line."""
    for n in range(1, count + 1):
        pat, _ = pattern(lines, label, n, ev)
        if not re.search(pat, rom):
            first = next(k for k, l in enumerate(lines) if any(x.split()[0] == label for x in l.labels))
            live = [l for l in lines[first:] if l.kind in ("insn", "hll") and not l.dead]
            ln = live[n - 1] if n - 1 < len(live) else None
            return "; first mismatch at statement %d: line %s %r" % (
                n, ln.no if ln else "?", ln.text.strip() if ln else "")
    return ""


def find(file, label, count=60, cpu=None):
    p = m65parse.Parser()
    for f in ("ALCOMN",):
        p.parse(os.path.join(p.srcdir, f + ".MAC"), own=False)
    lines = p.parse(os.path.join(p.srcdir, file.upper() + ".MAC"))
    cpu = cpu or load_rev3(CPU6502())
    rom = bytes(cpu.mem[0x9000:0xE000])
    pat, labels = pattern(lines, label.upper(), count, p.ev)
    hits = [m for m in re.finditer(pat, rom)]
    if len(hits) != 1:
        raise LookupError("%s %s: %d matches for %d statements%s" % (
            file, label, len(hits), count, diagnose(lines, label.upper(), count, p.ev, rom)))
    m = hits[0]
    addrs = {}
    for k, name in enumerate(labels):
        addrs.setdefault(name, 0x9000 + m.start("L%d" % k))
    return addrs, 0x9000 + m.end()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("label")
    ap.add_argument("--count", type=int, default=60)
    a = ap.parse_args()
    addrs, end = find(a.file, a.label, a.count)
    for k, v in addrs.items():
        print("%-10s $%04X" % (k, v))
    print("(pattern ends at $%04X)" % end)


if __name__ == "__main__":
    main()
