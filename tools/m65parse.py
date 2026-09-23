#!/usr/bin/env python3
"""m65parse.py - read Atari's MAC65 sources into a line model (plan stage 0, D6).

The translator and every checker build on this.  It reads a .MAC file (CRLF and stray CRs handled,
line numbers kept as an editor shows them) and classifies every line:

  label(s)      NAME: or NAME:: (global), local n$:
  assignment    NAME = expr, NAME == expr (global), NAME =: expr, and .=expr (location counter)
  instruction   a 6502 mnemonic, with its MAC65 addressing mode decoded from the operand prefix:
                I, imm   X, Y, (abs/zp,X/Y)   NY, (zp),Y   NX, (zp,X)   Z, ZX, ZY (zero page forced)
                A, AX, AY (absolute forced)   none (implied/accumulator)
  hll           an HLL65 structured-control macro (IFxx, ELSE, THEN, ENDIF, BEGIN, xxEND)
  directive     .BYTE .WORD .BLKB .IF ... and the rest
  macro         a call of a macro defined in the file or its includes (VCTR, JSRL, LAH, ...)
  macrodef      a line inside a .MACRO ... .ENDM body (a definition, not code)

.IF/.IFF/.IFT/.IFTF/.ENDC and .IIF are evaluated where their symbols are known (MACRO-11 rules:
strictly left-to-right, no precedence), so code assembled out (ALDIS2's .IF NE,0 block, the
SPACG=0 space-game remnants) is marked dead rather than counted.  .INCLUDE'd files contribute
symbols and macros; their lines are not reported as the file's own.  HLL65 nesting is checked.

Usage:
  m65parse.py FILE.MAC ... [--stats] [--modes] [--json OUT]
"""

import argparse
import collections
import json
import os
import re
import sys

MNEMONICS = set("""ADC AND ASL BCC BCS BEQ BIT BMI BNE BPL BRK BVC BVS CLC CLD CLI CLV CMP CPX CPY
DEC DEX DEY EOR INC INX INY JMP JSR LDA LDX LDY LSR NOP ORA PHA PHP PLA PLP ROL ROR RTI RTS SBC SEC
SED SEI STA STX STY TAX TAY TSX TXA TXS TYA""".split())
BRANCHES = {"BCC", "BCS", "BEQ", "BMI", "BNE", "BPL", "BVC", "BVS"}
HLL_IF = {"IFCC", "IFCS", "IFEQ", "IFNE", "IFMI", "IFPL", "IFVC", "IFVS"}
HLL_END = {"CCEND", "CSEND", "EQEND", "NEEND", "MIEND", "PLEND", "VCEND", "VSEND"}
HLL = HLL_IF | HLL_END | {"ELSE", "THEN", "ENDIF", "BEGIN"}
# Operand prefixes, longest first so NY, is not read as N...
MODES = [("NY,", "(zp),Y"), ("NX,", "(zp,X)"), ("AX,", "abs,X!"), ("AY,", "abs,Y!"),
         ("ZX,", "zp,X!"), ("ZY,", "zp,Y!"), ("I,", "imm"), ("X,", ",X"), ("Y,", ",Y"),
         ("Z,", "zp!"), ("A,", "abs!")]

SRC = os.path.join(os.path.dirname(__file__), "..", "tempest_orig", "src")


class Line:
    __slots__ = ("file", "no", "text", "labels", "kind", "op", "operand", "mode", "comment",
                 "dead", "depth", "sym", "value")

    def __init__(self, file, no, text):
        self.file, self.no, self.text = file, no, text
        self.labels = []
        self.kind = "blank"
        self.op = self.operand = self.mode = self.comment = self.sym = None
        self.value = None
        self.dead = False
        self.depth = 0

    def as_dict(self):
        return {k: getattr(self, k) for k in self.__slots__ if k != "text"}


def read_lines(path):
    with open(path, "rb") as f:
        raw = f.read().decode("latin-1")
    return [l.replace("\r", " ") for l in raw.split("\n")]


def split_comment(s):
    """Cut at the first ';' that is not inside <...> or a 'c character constant."""
    depth = 0
    i = 0
    while i < len(s):
        c = s[i]
        if c == "'" and i + 1 < len(s):
            i += 2
            continue
        if c == "<":
            depth += 1
        elif c == ">" and depth:
            depth -= 1
        elif c == ";" and depth == 0:
            return s[:i], s[i + 1:]
        i += 1
    return s, None


class Evaluator:
    """MACRO-11 expressions: left to right, no precedence.  Returns None when a symbol is unknown."""

    TOK = re.compile(r"\s*(\^[CcHhDdOoBb]|'.|[A-Za-z_.$][A-Za-z0-9_.$]*|[0-9A-Fa-f]+\.?|[-+*/&!<>]|\S)")

    def __init__(self, syms):
        self.syms = syms
        self.radix = 16

    def value(self, s):
        try:
            toks = self.TOK.findall(s.strip())
            v, i = self._expr(toks, 0)
            return v
        except (IndexError, ValueError, ZeroDivisionError):
            return None

    def _term(self, t, i):
        tok = t[i]
        if tok == "<":
            v, i = self._expr(t, i + 1)
            if i < len(t) and t[i] == ">":
                i += 1
            return v, i
        if tok == "-":
            v, i = self._term(t, i + 1)
            return (None if v is None else -v), i
        if tok == "+":
            return self._term(t, i + 1)
        if tok.upper() == "^C":
            v, i = self._term(t, i + 1)
            return (None if v is None else (~v) & 0xFFFF), i
        if tok.upper() in ("^H", "^D", "^O", "^B"):
            r = {"^H": 16, "^D": 10, "^O": 8, "^B": 2}[tok.upper()]
            return int(t[i + 1], r), i + 2
        if tok.startswith("'"):
            return ord(tok[1]), i + 1
        if re.fullmatch(r"[0-9][0-9A-Fa-f]*\.?", tok) or (self.radix == 16 and
                                                         re.fullmatch(r"[0-9][0-9A-Fa-f]*", tok)):
            if tok.endswith("."):
                return int(tok[:-1], 10), i + 1
            return int(tok, self.radix), i + 1
        key = tok.upper()
        if key in self.syms:
            return self.syms[key], i + 1
        if self.radix == 16 and re.fullmatch(r"[0-9A-Fa-f]+", tok) and tok[0].isdigit():
            return int(tok, 16), i + 1
        return None, i + 1

    def _expr(self, t, i):
        v, i = self._term(t, i)
        while i < len(t) and t[i] in "+-*/&!":
            op = t[i]
            w, i = self._term(t, i + 1)
            if v is None or w is None:
                v = None
                continue
            v = {"+": v + w, "-": v - w, "*": v * w, "/": int(v / w) if w else 0,
                 "&": v & w, "!": v | w}[op]
        return v, i


def cond_true(kind, val):
    if val is None:
        return None
    k = kind.upper()
    return {"EQ": val == 0, "Z": val == 0, "NE": val != 0, "NZ": val != 0, "GT": val > 0,
            "G": val > 0, "GE": val >= 0, "LT": val < 0, "L": val < 0, "LE": val <= 0}.get(k)


class Parser:
    def __init__(self, srcdir=SRC):
        self.srcdir = srcdir
        self.syms = {}
        self.macros = set(HLL) | {"LDAL", "LDAH", "HLL65", "DEFIF", "DEFEND", "IFXX", "LOC", "FND",
                                  "SWAP", "..END", ".LOC.", ".FND.", ".SWAP.", ".END."}
        self.ev = Evaluator(self.syms)
        self.included = set()
        # Macros that define macros (HLL65's DEFIF/DEFEND, ALWELG's CAMAC/CAMA2I/CAMA2F): the
        # outer macro's name -> which of its arguments becomes a new macro name when it is called.
        self.generators = {"DEFIF": 0, "DEFEND": 0}

    def parse(self, path, own=True):
        name = os.path.basename(path).upper()
        out = []
        macro_depth = 0
        rept_depth = 0
        cond = []                       # stack of (active: True/False/None)
        hll = []                        # HLL65 nesting stack: (kind, line)
        problems = []
        for no, text in enumerate(read_lines(path), 1):
            ln = Line(name, no, text)
            body, ln.comment = split_comment(text)
            s = body.strip()
            live = all(c is not False for c in cond)
            ln.dead = not live
            if not s:
                out.append(ln)
                continue
            words = s.split(None, 1)
            head = words[0].upper()
            rest = words[1] if len(words) > 1 else ""

            # Macro definition bodies: track nesting, record the name, classify as macrodef.
            if head == ".MACRO":
                if macro_depth == 0 and live:
                    parts = rest.replace(",", " ").split()
                    mname = parts[0].upper() if parts else ""
                    self.macros.add(mname)
                    cur_macro, cur_params = mname, [x.upper() for x in parts[1:]]
                elif macro_depth == 1 and rest:
                    inner = rest.replace(",", " ").split()[0].upper()
                    if inner in cur_params:
                        self.generators[cur_macro] = cur_params.index(inner)
                macro_depth += 1
                ln.kind = "macrodef"
                out.append(ln)
                continue
            if macro_depth:
                if head == ".ENDM":
                    macro_depth -= 1
                elif head == ".MACRO":
                    macro_depth += 1
                ln.kind = "macrodef"
                out.append(ln)
                continue
            # .REPT 0 ... .ENDR is how these sources comment out a block: treat it as dead.
            if head in (".REPT", ".IRP", ".IRPC"):
                rept_depth += 1
                zero = head == ".REPT" and self.ev.value(rest) == 0
                cond.append(False if zero or not live else None if head == ".REPT" else True)
                ln.kind, ln.op, ln.operand = "directive", head, rest
                out.append(ln)
                continue
            if head == ".ENDR" and rept_depth:
                rept_depth -= 1
                if cond:
                    cond.pop()
                ln.kind, ln.op = "directive", head
                out.append(ln)
                continue

            # Conditionals.
            if head == ".IF":
                parts = rest.split(",", 1)
                val = self.ev.value(parts[1]) if len(parts) > 1 else None
                t = cond_true(parts[0].strip(), val) if parts[0].strip().upper() not in ("DF", "NDF", "B", "NB", "IDN", "DIF") else None
                if parts[0].strip().upper() in ("DF", "NDF") and len(parts) > 1:
                    d = parts[1].strip().upper() in self.syms
                    t = d if parts[0].strip().upper() == "DF" else not d
                cond.append(t if live else False)
                ln.kind, ln.op, ln.operand = "directive", head, rest
                out.append(ln)
                continue
            if head in (".IFF", ".IFT", ".IFTF") and cond:
                top = cond[-1]
                outer_live = all(c is not False for c in cond[:-1])
                if head == ".IFF":
                    cond[-1] = (None if top is None else (not top)) if outer_live else False
                elif head == ".IFTF":
                    cond[-1] = True if outer_live else False
                ln.kind, ln.op, ln.operand = "directive", head, rest
                out.append(ln)
                continue
            if head == ".ENDC":
                if cond:
                    cond.pop()
                ln.kind, ln.op = "directive", head
                out.append(ln)
                continue

            # Labels (possibly more than one), then the statement.
            while True:
                m = re.match(r"([A-Za-z_.$][A-Za-z0-9_.$]*|[0-9]+\$)(::?)\s*(.*)$", s)
                if not m or m.group(1).upper() in (".", ):
                    break
                lab = m.group(1).upper()
                ln.labels.append(lab + (" (global)" if m.group(2) == "::" else ""))
                s = m.group(3)
                if not s:
                    break
            if ln.labels and not s:
                ln.kind = "label"
                out.append(ln)
                continue

            # Assignment.
            m = re.match(r"([A-Za-z_.$][A-Za-z0-9_.$]*)\s*(==|=:|=)\s*(.*)$", s)
            if m and not s.upper().startswith(".IIF"):
                ln.kind, ln.sym, ln.operand = "assign", m.group(1).upper(), m.group(3).strip()
                if live and ln.sym != ".":
                    v = self.ev.value(ln.operand)
                    ln.value = v
                    if v is not None:
                        self.syms[ln.sym] = v
                    elif ln.sym in self.syms and not rept_depth:
                        del self.syms[ln.sym]
                out.append(ln)
                continue

            words = s.split(None, 1)
            head = words[0].upper()
            rest = words[1].strip() if len(words) > 1 else ""
            ln.op, ln.operand = head, rest or None

            if head == ".RADIX" and live:
                v = Evaluator({}).value(rest) if rest else None
                if rest.strip().endswith("."):
                    self.ev.radix = int(rest.strip()[:-1])
                elif v:
                    self.ev.radix = int(rest.strip(), 10) if rest.strip().isdigit() else v
                ln.kind = "directive"
            elif head == ".INCLUDE":
                ln.kind = "directive"
                inc = rest.split()[0].upper() if rest else ""
                p = os.path.join(self.srcdir, inc + ".MAC")
                if live and inc and inc not in self.included and os.path.exists(p):
                    self.included.add(inc)
                    saved = self.ev.radix
                    self.parse(p, own=False)
                    self.ev.radix = saved
            elif head in MNEMONICS:
                ln.kind = "insn"
                ln.mode = self.mode(head, rest)
            elif head in HLL:
                ln.kind = "hll"
                if live and own:
                    if head in HLL_IF:
                        hll.append(("IF", no))
                    elif head == "BEGIN":
                        hll.append(("BEGIN", no))
                    elif head == "ELSE":
                        if not hll or hll[-1][0] != "IF":
                            problems.append("%s:%d ELSE without IF" % (name, no))
                    elif head in ("ENDIF", "THEN"):
                        if not hll or hll[-1][0] != "IF":
                            problems.append("%s:%d %s without IF" % (name, no, head))
                        else:
                            hll.pop()
                    elif head in HLL_END:
                        if not hll or hll[-1][0] != "BEGIN":
                            problems.append("%s:%d %s without BEGIN" % (name, no, head))
                        else:
                            hll.pop()
                ln.depth = len(hll)
            elif head.startswith("."):
                ln.kind = "directive"
            elif head in self.macros:
                ln.kind = "macro"
                if live and head in self.generators and rest:
                    args = [x.strip().upper() for x in rest.split(",")]
                    i = self.generators[head]
                    if i < len(args) and args[i]:
                        self.macros.add(args[i])
            else:
                ln.kind = "unknown"
            out.append(ln)
        if own:
            for k, n in hll:
                problems.append("%s:%d %s never closed" % (name, n, k))
        self.problems = getattr(self, "problems", []) + problems
        return out

    @staticmethod
    def mode(op, rest):
        if not rest:
            return "implied"
        if op in BRANCHES:
            return "rel"
        for pre, m in MODES:
            if rest.upper().startswith(pre):
                return m
        return "abs/zp"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--stats", action="store_true", help="per-file counts")
    ap.add_argument("--modes", action="store_true", help="addressing-mode totals over live instructions")
    ap.add_argument("--json", help="write the whole model here")
    ap.add_argument("--unknown", action="store_true", help="list statements not recognised")
    a = ap.parse_args()

    model = {}
    modes = collections.Counter()
    mnem = collections.Counter()
    p = Parser(os.path.dirname(os.path.abspath(a.files[0])))
    for f in a.files:
        lines = p.parse(f)
        model[os.path.basename(f).upper()] = lines
        if a.stats:
            k = collections.Counter(l.kind for l in lines if not l.dead)
            dead = sum(1 for l in lines if l.dead and l.kind in ("insn", "hll", "macro"))
            print("%-11s %5d lines  insn %5d  hll %4d  macro %4d  directive %4d  assign %4d  "
                  "macrodef %4d  dead code %4d  unknown %d" %
                  (os.path.basename(f), len(lines), k["insn"], k["hll"], k["macro"], k["directive"],
                   k["assign"], k["macrodef"], dead, k["unknown"]))
        for l in lines:
            if l.kind == "insn" and not l.dead:
                modes[l.mode] += 1
                mnem[l.op] += 1
        if a.unknown:
            for l in lines:
                if l.kind == "unknown" and not l.dead:
                    print("  unknown %s:%d  %s" % (l.file, l.no, l.text.strip()))
    if a.modes:
        tot = sum(modes.values())
        print("live instructions: %d" % tot)
        for m, c in modes.most_common():
            print("  %-10s %5d  %4.1f%%" % (m, c, 100.0 * c / tot))
        print("mnemonics:", ", ".join("%s %d" % x for x in mnem.most_common()))
    for pr in p.problems:
        print("HLL65:", pr)
    if a.json:
        with open(a.json, "w") as fo:
            json.dump({k: [l.as_dict() for l in v] for k, v in model.items()}, fo)


if __name__ == "__main__":
    main()
