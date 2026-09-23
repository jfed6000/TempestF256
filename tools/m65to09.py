#!/usr/bin/env python3
"""m65to09.py - translate Tempest's 6502 source to position-independent 6809 (plan D6, step 1).

Emits what the approved pilot (pilot/*_b.a, docs/status.md "D6 pilot") shows, register model B:

  6502 A -> A.  6502 X, Y -> <RX, <RY (zero page $B9, $BB); RXP/RYP ($B8/$BA hold the data area's
  page) make "ldy <RXP" the data base + X.  B is always scratch.  U = data area base, DP its page:
  zero page is <NAME, the rest of the arcade's 2K is NAME,U.  Code and ROM data are PC-relative.

What the translator works out for itself:

  * Flags.  Whole-program liveness of N, Z, V, C (through JSR and RTS), and forward tracking of how
    the 6809's CC stands for the 6502's: after a 6809 subtract or compare C is the inverse of the
    6502's; CLC/SEC/CLV are held as constants until something needs them; STA and the pointer
    set-ups disturb N, Z, V.  At every join (label, HLL65 ENDIF/ELSE/BEGIN), call and return, the
    live flags are put into 6502 form first; a branch on a flag in the wrong sense is inverted
    instead when nothing downstream needs it.
  * Decimal mode, as a whole-program dataflow: ADC in decimal mode gets a DAA.
  * Block-local pointer caches: 6809 Y = data base + X, 6809 X = a table or list pointer + Y
    (or + X for a ROM table), with INX/INY folded into the offsets.
  * Pointers used through (zp),Y are big-endian logical addresses: byte accesses swapped.
  * Data (.BYTE, .WORD, macro-made tables) is the ROM's own bytes, via romalign.py.

What it cannot do is marked with a "* HAND:" line, counted by category in the report: hardware
registers, address constants (a pointer set from an immediate), BIT when V or both N and Z are
read, decimal SBC, the stack pointer, a flag needed in a state that cannot be recovered, and the
macro-built code of ALCOIN (COIN65).

    m65to09.py              translate every file into xlat/, assemble the module, report
    m65to09.py --no-build   translate only
"""

import argparse
import collections
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
import m65parse                                             # noqa: E402
import romalign                                             # noqa: E402
from m65parse import sym6                                   # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "xlat")
PREFIXES = [p for p, _ in m65parse.MODES]

# The game files translated, in link order.  ALTES2 (self-test) is dropped (plan D10).
FILES = ["ALWELG", "ALSCO2", "ALDIS2", "ALEXEC", "ALSOUN", "ALVROM", "ALCOIN", "ALLANG", "ALHAR2",
         "ALEARO", "ALVGUT"]
# Replaced by the platform layer, but translated so the draft is whole (plan section 1).
REPLACED = {"ALHAR2": "the IRQ: rewritten into the frame loop", "ALEARO": "EAROM: the settings file"}

# Zero-page pointers used through (zp),Y or (zp,X): big-endian logical addresses on the port.
# Filled from the source by Translator.find_pointers().
POINTER_NOTE = "big-endian pointer (docs/status.md, D6 conventions)"

# Anti-tamper sabotage that the port neutralises by making its check pass (port-tempest 2.4):
# the statement is dropped, and dataflow ignores it.
NEUTRALISE = {("ALEXEC", 267): "ZQAT4C sets decimal mode when the copyright check fails"}

# Hardware addresses: POKEY 1/2 audio registers go to the register image POKIMG (AUDF1 at +0,
# AUDF2 at +8, as approved); everything else in the I/O pages to a shadow area, marked HAND.
POKIMG, HWSHAD, VWIN, CLRSHD = 0x0800, 0x0900, 0x0810, 0x0820

# ALCOMN's and HLL65's address macros are instructions: LDA/LDX immediate of one byte of an
# address (M68 = the high byte).  (6502 op, which byte)
ADDR_MACROS = {"LDAL": ("LDA", "lo"), "LDAH": ("LDA", "hi"), "LAH": ("LDA", "hi"), "LXL": ("LDX", "lo")}

# Tables the original reads past their end, into the code that follows them in the ROM.  After the
# data statement with this label the module repeats that many ROM bytes, so the port reads the same
# values.  MODSND loads a terminator's NUMBER byte three past it: the last sequence's 0,0 (PO6A)
# is followed by CHKSM9 and then IPEXPL's LDA I,SIDDI.
OVERRUN = {("ALSOUN", "CHKSM9"): 3}

FLAGS = "NZVC"


def sanitize(name):
    """A MACRO-11 symbol as an lwasm one: $ is a hex prefix to lwasm."""
    return name.replace("$", "_S").replace(".", "_D")


class Node:
    __slots__ = ("file", "idx", "line", "kind", "op", "mode", "operand", "succ", "uses", "defs",
                 "call", "ret", "live_in", "live_out", "labels", "join", "target", "hll",
                 "dec_in", "addr", "size", "hand", "block")

    def __init__(self, file, idx, line, kind):
        self.file, self.idx, self.line, self.kind = file, idx, line, kind
        self.op = line.op if line is not None else None
        self.mode = line.mode if line is not None else None
        self.operand = line.operand if line is not None else None
        self.succ = []
        self.uses = self.defs = frozenset()
        self.call = None
        self.ret = False
        self.live_in = self.live_out = frozenset()
        self.labels = []
        self.join = False
        self.target = None
        self.hll = None
        self.dec_in = None
        self.addr = self.size = None
        self.hand = None
        self.block = 0


USE_DEF = {
    "ADC": ("C", "NZCV"), "SBC": ("C", "NZCV"), "CMP": ("", "NZC"), "CPX": ("", "NZC"),
    "CPY": ("", "NZC"), "ASL": ("", "NZC"), "LSR": ("", "NZC"), "ROL": ("C", "NZC"),
    "ROR": ("C", "NZC"), "BIT": ("", "NZV"), "CLC": ("", "C"), "SEC": ("", "C"), "CLV": ("", "V"),
    "PHP": ("NZVC", ""), "PLP": ("", "NZVC"),       # PHP: see liveness(), paired with its PLP
    "BCC": ("C", ""), "BCS": ("C", ""),
    "BEQ": ("Z", ""), "BNE": ("Z", ""), "BMI": ("N", ""), "BPL": ("N", ""), "BVC": ("V", ""),
    "BVS": ("V", ""),
}
for _m in ("LDA LDX LDY AND ORA EOR TAX TAY TXA TYA INX INY DEX DEY INC DEC PLA TSX").split():
    USE_DEF[_m] = ("", "NZ")
BRANCH_FLAG = {"BCC": ("C", 0), "BCS": ("C", 1), "BEQ": ("Z", 1), "BNE": ("Z", 0), "BMI": ("N", 1),
               "BPL": ("N", 0), "BVC": ("V", 0), "BVS": ("V", 1)}
HLL_BRANCH = {"IFCC": "BCS", "IFCS": "BCC", "IFEQ": "BNE", "IFNE": "BEQ", "IFMI": "BPL",
              "IFPL": "BMI", "IFVC": "BVS", "IFVS": "BVC",
              # xxEND: branch back to BEGIN while not xx
              "CCEND": "BCS", "CSEND": "BCC", "EQEND": "BNE", "NEEND": "BEQ", "MIEND": "BPL",
              "PLEND": "BMI", "VCEND": "BVS", "VSEND": "BVC"}
B6809 = {("C", 1): "bcs", ("C", 0): "bcc", ("Z", 1): "beq", ("Z", 0): "bne", ("N", 1): "bmi",
         ("N", 0): "bpl", ("V", 1): "bvs", ("V", 0): "bvc"}


class Translator:
    def __init__(self):
        self.al = romalign.Aligner().run()
        self.nodes = []
        self.by_label = {}                  # (file, label) and ("", global label) -> node index
        self.files = {}
        self.hand = collections.Counter()
        self.hand_sites = collections.defaultdict(list)
        self.names = {}                     # (file, sym6 name) -> lwasm name
        self.long = set()                   # emitted branch ids that need the long form
        self.hw_used = set()                # arcade I/O addresses the translation shadows
        self.build_nodes()
        self.find_pointers()
        self.name_labels()
        self.link()
        self.find_dispatch()
        self.preds = collections.defaultdict(list)
        for n in self.nodes:
            for t in n.succ:
                self.preds[t].append(n.idx)
        self.liveness()
        self.decimal()

    # --- structure ------------------------------------------------------------------------------
    def build_nodes(self):
        """One node per statement that occupies ROM or joins control flow, per file, from the
        aligner's items (which carry each statement's ROM address and size)."""
        for f in FILES:
            p = self.al.parsers[f]
            items = self.al.files[f]
            first = len(self.nodes)
            hll = []
            local_block = 0
            for it in items:
                ln = it.line
                if ln is None:
                    n = Node(f, len(self.nodes), None, "label")
                elif ln.kind == "insn":
                    n = Node(f, len(self.nodes), ln, "insn")
                elif ln.kind == "hll":
                    n = Node(f, len(self.nodes), ln, "hll")
                elif ln.kind == "assign":
                    n = Node(f, len(self.nodes), ln, "label")
                elif ln.kind == "macro" and ln.op in ADDR_MACROS:
                    n = Node(f, len(self.nodes), ln, "insn")
                    n.op, n.mode = ADDR_MACROS[ln.op][0], "imm"
                    n.hand = "addr-" + ADDR_MACROS[ln.op][1]
                else:
                    n = Node(f, len(self.nodes), ln, "data")
                n.addr, n.size = it.addr, it.size
                n.block = local_block
                for lab in it.labels:
                    if re.fullmatch(r"\d+\$", lab):
                        name = "L%d_%s" % (local_block, lab[:-1])
                    else:
                        name = lab
                        local_block += 1
                    n.labels.append(name)
                    self.by_label[(f, name)] = n.idx
                    n.join = True
                n.block = local_block
                if n.kind == "hll":
                    h = ln.op
                    n.hll = h
                    if h in ("BEGIN",):
                        n.join = True
                        hll.append(["BEGIN", n.idx])
                    elif h.startswith("IF"):
                        hll.append(["IF", n.idx, None])
                    elif h == "ELSE":
                        top = hll[-1]
                        top[2] = n.idx
                    elif h in ("ENDIF", "THEN"):
                        top = hll.pop()
                        n.join = True
                        ifn = self.nodes_or_new(top[1], n)
                        if top[2] is not None:
                            self.nodes[top[2]].target = n.idx          # ELSE jumps to ENDIF
                            ifn.target = ("after", top[2])              # IF skips to after ELSE
                        else:
                            ifn.target = n.idx
                    elif h in HLL_BRANCH:                               # xxEND
                        top = hll.pop()
                        n.target = top[1]
                self.nodes.append(n)
            self.files[f] = (first, len(self.nodes))
            # an IF's target "after ELSE" is the node following the ELSE
            for n in self.nodes[first:]:
                if isinstance(n.target, tuple):
                    n.target = n.target[1] + 1
                    self.nodes[n.target].join = True

    def nodes_or_new(self, idx, cur):
        return self.nodes[idx] if idx < len(self.nodes) else cur

    def find_pointers(self):
        self.pointers = {}                  # zp address -> its RAM label
        for n in self.nodes:
            if n.kind == "insn" and n.mode in ("(zp),Y", "(zp,X)"):
                v = self.value(n, self.strip(n.operand))
                if v is not None:
                    p = self.al.parsers[n.file]
                    name = next((k for k in sorted(p.ram_labels) if p.syms.get(k) == v), None)
                    self.pointers[v] = sanitize(name) if name else "$%02X" % v

    def name_labels(self):
        """lwasm names.  A label that is not global and is defined in more than one file gets the
        file's name appended in every file that defines it."""
        where = collections.defaultdict(set)
        for (f, lab) in self.by_label:
            where[lab].add(f)
        for (f, lab), i in self.by_label.items():
            glob = lab in self.al.parsers[f].globals
            name = sanitize(lab)
            if len(where[lab]) > 1 and not glob:
                name = "%s_%s" % (name, f)
            self.names[(f, lab)] = name

    def find_dispatch(self):
        """Atari's RTS dispatch: LDA i,T+1 / PHA / LDA i,T / PHA (then an RTS, now or after a join)
        over a table T of .WORD target-1 (or CAMAC-family macros making the same words).  The pair
        becomes one jump through T, and T becomes 6809 offsets from itself: fdb target-T."""
        self.dispatch = {}          # first node -> (table label, index register)
        self.jtables = {}           # ROM address of a table -> (file, label, entries)
        self.folded = set()
        cams = {"CAMAC", "CAMA2I", "CAMA2F"}
        for i in range(len(self.nodes) - 3):
            a, b, c, d = self.nodes[i:i + 4]
            if not all(x.kind == "insn" for x in (a, b, c, d)) or [x.op for x in (a, b, c, d)] != \
                    ["LDA", "PHA", "LDA", "PHA"]:
                continue
            m1 = re.fullmatch(r"\s*([A-Za-z_.$][A-Za-z0-9_.$]*)\s*\+\s*1\s*", self.strip(a.operand))
            m2 = re.fullmatch(r"\s*([A-Za-z_.$][A-Za-z0-9_.$]*)\s*", self.strip(c.operand))
            if not (m1 and m2 and sym6(m1.group(1)) == sym6(m2.group(1)) and a.mode == c.mode and
                    a.mode.rstrip("!") in (",X", ",Y", "abs,X", "abs,Y")):
                continue
            tab = sym6(m2.group(1))
            tnode = self.label_node(a.file, tab)
            if tnode is None:
                continue
            start = self.al.flabels.get((self.nodes[tnode].file, tab), self.nodes[tnode].addr)
            # the table runs over the .WORD and CAM-macro statements from T to the next label
            entries = 0
            k = tnode
            while k < len(self.nodes):
                t = self.nodes[k]
                if k != tnode and t.labels:
                    break
                if t.kind == "data" and t.line is not None and (t.line.op or "").upper() == ".WORD":
                    entries += len(romalign.split_args(t.line.operand or ""))
                elif t.kind == "data" and t.line is not None and t.line.op in cams:
                    entries += 1
                elif t.kind in ("data", "insn", "hll"):
                    break
                k += 1
            reg = "X" if "X" in a.mode else "Y"
            self.dispatch[i] = (self.names[(self.nodes[tnode].file, tab)], reg)
            self.folded |= {i + 1, i + 2, i + 3}
            self.jtables[start] = (self.nodes[tnode].file, self.names[(self.nodes[tnode].file, tab)], entries)

    def label_node(self, f, name, block=None):
        if re.fullmatch(r"\d+\$", name.strip()):
            name = "L%d_%s" % (block, name.strip()[:-1])
        else:
            name = sym6(name)
        if (f, name) in self.by_label:
            return self.by_label[(f, name)]
        cands = [i for (ff, lab), i in self.by_label.items() if lab == name]
        if len(cands) == 1:
            return cands[0]
        glob = [i for (ff, lab), i in self.by_label.items()
                if lab == name and lab in self.al.parsers[ff].globals]
        return glob[0] if len(glob) == 1 else None

    def link(self):
        """Successors, uses and defs."""
        for f in FILES:
            lo, hi = self.files[f]
            for i in range(lo, hi):
                n = self.nodes[i]
                nxt = [i + 1] if i + 1 < hi else []
                if n.kind == "data":
                    n.succ = []
                    continue
                if n.kind == "label":
                    n.succ = nxt
                    continue
                if n.kind == "hll":
                    h = n.hll
                    if h.startswith("IF"):
                        br = HLL_BRANCH[h]
                        n.uses = frozenset(BRANCH_FLAG[br][0])
                        n.succ = nxt + [n.target]
                    elif h == "ELSE":
                        n.defs = frozenset("V")
                        n.succ = [n.target]
                    elif h in HLL_BRANCH:
                        br = HLL_BRANCH[h]
                        n.uses = frozenset(BRANCH_FLAG[br][0])
                        n.succ = nxt + [n.target]
                    else:
                        n.succ = nxt
                    continue
                op = n.op
                if (f, n.line.no) in NEUTRALISE:
                    n.succ = nxt
                    continue
                u, d = USE_DEF.get(op, ("", ""))
                n.uses, n.defs = frozenset(u), frozenset(d)
                if op in BRANCH_FLAG:
                    t = self.label_node(f, self.strip(n.operand), n.block)
                    n.target = t
                    n.succ = nxt + ([t] if t is not None else [])
                elif op == "JMP":
                    t = self.label_node(f, self.strip(n.operand), n.block)
                    n.target = t
                    n.succ = [t] if t is not None else []
                elif op == "JSR":
                    t = self.label_node(f, self.strip(n.operand), n.block)
                    n.call = t
                    n.succ = nxt
                elif op in ("RTS", "RTI"):
                    n.ret = True
                    n.succ = []
                elif op == "BRK":
                    n.succ = []
                else:
                    n.succ = nxt

    def liveness(self):
        """Backward flag liveness over the whole program, with calls: a JSR's live-in is its
        callee's entry live-in plus what is live after it; an RTS is live in whatever is live after
        the calls of every routine that reaches it (all four flags if none is known to)."""
        nodes = self.nodes
        callers = collections.defaultdict(list)
        for n in nodes:
            if n.call is not None:
                callers[n.call].append(n.idx)
        # which RTS nodes each called routine reaches without passing through a call
        owner = collections.defaultdict(set)
        for entry in callers:
            seen, stack = set(), [entry]
            while stack:
                i = stack.pop()
                if i in seen:
                    continue
                seen.add(i)
                if nodes[i].ret:
                    owner[i].add(entry)
                stack.extend(nodes[i].succ)
        self.owner = owner
        # PHP saves the flags for its PLP: what PHP needs is what is live after that PLP.  Pair
        # each PHP with the next unmatched PLP in the same file.
        self.php_plp = {}
        for f in FILES:
            lo, hi = self.files[f]
            stack = []
            for i in range(lo, hi):
                n = nodes[i]
                if n.kind == "insn" and n.op == "PHP":
                    stack.append(i)
                elif n.kind == "insn" and n.op == "PLP" and stack:
                    self.php_plp[stack.pop()] = i
        allf = frozenset(FLAGS)
        # Routines no JSR reaches are entered by Atari's RTS dispatch (PHA / PHA / RTS: EXSTAT and
        # kin) and return to wherever the dispatcher was called from.  Their RTS takes what is live
        # after the dispatchers' calls.
        dispatch_rts = [n.idx for n in nodes if n.ret and n.idx > 0 and nodes[n.idx - 1].kind == "insn"
                        and nodes[n.idx - 1].op == "PHA"]
        self.dispatchers = set()
        for r in dispatch_rts:
            self.dispatchers |= owner.get(r, set())
        changed = True
        while changed:
            changed = False
            for n in reversed(nodes):
                if n.ret:
                    if n.op == "RTI":
                        out = frozenset()
                    elif owner.get(n.idx):
                        out = frozenset()
                        for e in owner[n.idx]:
                            for c in callers[e]:
                                out |= nodes[c].live_out
                    elif n.idx in dispatch_rts:
                        out = frozenset()               # the dispatch itself: goes to the target
                    else:
                        out = frozenset()
                        for e in self.dispatchers:
                            for c in callers[e]:
                                out |= nodes[c].live_out
                else:
                    out = frozenset()
                    for s in n.succ:
                        out |= nodes[s].live_in
                    if n.kind == "insn" and n.op == "JMP" and n.target is None:
                        out = allf
                if n.call is not None:
                    lin = nodes[n.call].live_in | out
                elif n.idx in self.php_plp:
                    lin = nodes[self.php_plp[n.idx]].live_out | out
                else:
                    lin = n.uses | (out - n.defs)
                if lin != n.live_in or out != n.live_out:
                    n.live_in, n.live_out = lin, out
                    changed = True

    def decimal(self):
        """Forward dataflow of the D flag: 'bin', 'dec' or 'mix' at each node's entry."""
        nodes = self.nodes
        callers = collections.defaultdict(list)
        for n in nodes:
            if n.call is not None:
                callers[n.call].append(n.idx)

        def meet(a, b):
            if a is None:
                return b
            if b is None or a == b:
                return a
            return "mix"

        for n in nodes:
            n.dec_in = None
        for f in FILES:
            lo, hi = self.files[f]
            for i in range(lo, hi):
                if nodes[i].labels and not any(i in nodes[j].succ for j in range(lo, hi)):
                    nodes[i].dec_in = "bin"     # an entry point nobody branches to
        work = [n.idx for n in nodes if n.dec_in is not None]
        while work:
            i = work.pop()
            n = nodes[i]
            d = n.dec_in
            if n.kind == "insn" and (n.file, n.line.no) not in NEUTRALISE:
                if n.op == "SED":
                    d = "dec"
                elif n.op == "CLD":
                    d = "bin"
            outs = list(n.succ)
            if n.call is not None:
                c = nodes[n.call]
                nd = meet(c.dec_in, n.dec_in)
                if nd != c.dec_in:
                    c.dec_in = nd
                    work.append(c.idx)
            for s in outs:
                nd = meet(nodes[s].dec_in, d)
                if nd != nodes[s].dec_in:
                    nodes[s].dec_in = nd
                    work.append(s)

    # --- operands -------------------------------------------------------------------------------
    @staticmethod
    def strip(opnd):
        o = (opnd or "").strip()
        for p in PREFIXES:
            if o.upper().startswith(p):
                return o[len(p):].strip()
        return o

    def value(self, n, expr):
        p = self.al.parsers[n.file]
        ev = p.ev
        saved = ev.radix
        ev.radix = n.line.radix
        try:
            v = ev.value(expr)
        finally:
            ev.radix = saved
        if v is None:
            # a code or data label: its ROM address, from the alignment
            m = re.fullmatch(r"\s*([A-Za-z_.$][A-Za-z0-9_.$]*)\s*(?:([+-])\s*([0-9A-Fa-f]+)(\.?))?\s*", expr)
            if m and sym6(m.group(1)) in self.al.labels:
                v = self.al.labels[sym6(m.group(1))]
                if m.group(2):
                    k = int(m.group(3), 10 if m.group(4) else 16)
                    v += k if m.group(2) == "+" else -k
        return v

    def rom_bytes(self, n):
        return self.al.rom[n.addr:n.addr + (n.size or 0)]

    def operand_value(self, n):
        """The operand's value: from the source if it evaluates, else from the ROM bytes."""
        expr = self.strip(n.operand)
        v = self.value(n, expr)
        if v is None and n.size and n.size >= 2:
            b = self.rom_bytes(n)
            v = b[1] if n.size == 2 else b[1] | b[2] << 8
        return v

    def sym_text(self, n, expr):
        """Operand text for a RAM address: NAME, NAME+k, or the number."""
        m = re.fullmatch(r"\s*([A-Za-z_.$][A-Za-z0-9_.$]*)\s*(?:([+-])\s*([0-9A-Fa-f]+)(\.?))?\s*", expr)
        p = self.al.parsers[n.file]
        if m and sym6(m.group(1)) in p.ram_labels:
            name = sanitize(sym6(m.group(1)))
            if m.group(2):
                k = int(m.group(3), 10 if m.group(4) else 16)
                return "%s%s%d" % (name, m.group(2), k)
            return name
        return None

    def classify(self, n, v, expr, indexed=False):
        """(kind, text) for an address: zp, ram, rom, pokey, hw, vram."""
        if v is None:
            return "unknown", expr
        if v < 0x100:
            if v in self.pointers:                       # the 6502's low byte: the port's second
                return "zp", "%s+1" % self.pointers[v]
            if v - 1 in self.pointers:                   # the 6502's high byte: the port's first
                return "zp", self.pointers[v - 1]
            t = self.sym_text(n, expr)
            return "zp", t or "$%02X" % v
        if v < 0x800:
            t = self.sym_text(n, expr)
            return "ram", t or "$%04X" % v
        if 0x0800 <= v <= 0x080F:
            return "ram", "CLRSHD+%d" % (v - 0x0800)        # colour RAM: committed by SS.ClutWrite
        if 0x2000 <= v < 0x3000:
            return "vram", "$%04X" % (v - 0x2000)
        if 0x3000 <= v < 0x4000:
            return "rom", "VROM+$%03X" % (v - 0x3000)       # vector ROM, in the module (plan 3)
        # POKEY audio registers by the symbol the source names, not by value: STA X,AUDF2-8 is
        # $60C8 (POKEY 1's AUDCTL) plus an X of 8 or more, i.e. POKEY 2.
        if not indexed and (0x60C0 <= v <= 0x60C7 or 0x60D0 <= v <= 0x60D7):
            return "pokey", "POKIMG+%d" % ((v - 0x60C0) if v < 0x60D0 else 8 + (v - 0x60D0))
        m = re.search(r"\b(AUD[FC][1-4]?2?|POKEY2?)\b", expr.upper())
        if indexed and m and 0x6000 <= v < 0x7000:
            p = self.al.parsers[n.file]
            sv = p.syms.get(sym6(m.group(1)))
            if sv is not None and (0x60C0 <= sv <= 0x60C7 or 0x60D0 <= sv <= 0x60D7):
                img = (sv - 0x60C0) if sv < 0x60D0 else 8 + (sv - 0x60D0)
                return "pokey", "POKIMG%+d" % (img + v - sv)
        if 0x4000 <= v < 0x7000 or v in (0x0C00, 0x0D00, 0x0E00):
            self.hw_used.add(v)
            return "hw", "HW_%04X" % v
        if 0x9000 <= v < 0xE000:
            # the source's own symbol if the module defines it (SOUND+STVAL+100 stays SOUND+...)
            m = re.fullmatch(r"\s*([A-Za-z_.$][A-Za-z0-9_.$]*)\s*((?:[+-]\s*[A-Za-z0-9_.$]+\s*)*)", expr)
            if m:
                name = self.module_name(n.file, m.group(1))
                base = self.al.flabels.get((n.file, sym6(m.group(1))), self.al.labels.get(sym6(m.group(1))))
                if name is not None and base is not None and sym6(m.group(1)) not in self.al.ambiguous:
                    return "rom", "%s%s" % (name, "" if v == base else "%+d" % (v - base))
            lab = self.rom_label(v)
            return "rom", lab
        return "unknown", "$%04X" % v

    def code_label(self, v):
        """The name of the code label at ROM address v, preferring a label on an instruction."""
        best = None
        for (f, lab), i in self.by_label.items():
            t = self.nodes[i]
            if t.addr == v and lab not in self.al.ambiguous and self.al.flabels.get((f, lab), v) == v:
                if t.kind in ("insn", "hll"):
                    return self.names[(f, lab)]
                best = best or self.names[(f, lab)]
        return best or self.rom_label(v)

    def module_name(self, f, sym):
        """The module's name for a source symbol that is a label or an equ the module emits."""
        k = sym6(sym)
        if (f, k) in self.names:
            return self.names[(f, k)]
        for n in self.nodes:
            if n.file == f and n.kind == "label" and n.line is not None and n.line.kind == "assign" \
                    and n.line.sym and sym6(n.line.sym) == k:
                return sanitize(k)
        i = self.label_node(f, sym)
        if i is not None:
            t = self.nodes[i]
            for lab in t.labels:
                if lab == k:
                    return self.names[(t.file, lab)]
        return None

    def rom_label(self, v):
        """Name a ROM address: a label at it, or the nearest one below plus an offset."""
        if not hasattr(self, "_addrs"):
            import bisect
            self._bisect = bisect
            pairs = {}
            for (f, lab), i in self.by_label.items():
                if lab in self.al.ambiguous:
                    continue                    # not emitted: its place is unknown
                a = self.al.flabels.get((f, lab), self.nodes[i].addr)
                if a is not None:
                    pairs.setdefault(a, self.names[(f, lab)])
            self._addrs = sorted(pairs)
            self._names = [pairs[a] for a in self._addrs]
        k = self._bisect.bisect_right(self._addrs, v) - 1
        if k < 0:
            return "$%04X" % v
        a, name = self._addrs[k], self._names[k]
        return name if a == v else "%s+%d" % (name, v - a)

    # --- emission -------------------------------------------------------------------------------
    def translate_all(self):
        os.makedirs(OUT, exist_ok=True)
        for n in self.nodes:                    # name every target before anything is emitted
            for t in (n.target, n.call):
                if isinstance(t, int):
                    self.target_name(t)
        self.bid = 0
        self.branch_lines = {}
        self.incoming = collections.defaultdict(list)
        for f in FILES:
            with open(os.path.join(OUT, f.lower() + ".a"), "w") as fo:
                fo.write(self.translate_file(f))
        with open(os.path.join(OUT, "tempest.a"), "w") as fo:
            fo.write(self.top())

    def top(self):
        lines = ["* tempest.a - the translated game, generated by tools/m65to09.py; do not edit.",
                 "* Model B (docs/status.md, D6).  Assemble: lwasm --6809 --format=raw.", "",
                 "\topt\tc", "\tinclude\tport.d", "\tinclude\tarcade.d", ""]
        for f in FILES:
            lines.append("\tinclude\t%s.a" % f.lower())
        lines.append("\tinclude\tstubs.a")
        lines.append("VROM\tincludebin\tvrom.bin\t\tvector ROM (136002-138.np3), read by the CPU and the interpreter")
        return "\n".join(lines) + "\n"

    def translate_file(self, f):
        lo, hi = self.files[f]
        out = ["* %s.a - %s.MAC translated by tools/m65to09.py (model B); do not edit, regenerate." %
               (f.lower(), f), "* Each line ends with the 6502 source line it comes from."]
        if f in REPLACED:
            out.append("* HAND-FILE: %s" % REPLACED[f])
        if f == "ALCOIN":
            out.append("* HAND: ALCOIN is COIN65's macros: its 6502 code is kept as bytes here.")
            self.note("coin65", f, None)
            a, b = self.al.ranges[f]
            out += self.fcb(self.al.rom[a:b], "COIN65 code (6502)")
            out.append("")
            return "\n".join(out) + "\n"
        self.state = None
        for i in range(lo, hi):
            n = self.nodes[i]
            out += self.emit_node(n)
        out.append("")
        return "\n".join(out) + "\n"

    def note(self, cat, f, n, detail=""):
        self.hand[cat] += 1
        self.hand_sites[cat].append("%s:%s %s" % (f, n.line.no if n is not None and n.line else "-", detail))

    @staticmethod
    def fcb(data, comment=""):
        out = []
        for k in range(0, len(data), 8):
            chunk = data[k:k + 8]
            out.append("\tfcb\t" + ",".join("$%02X" % b for b in chunk) +
                       ("\t\t%s" % comment if comment and k == 0 else ""))
        return out

    def src(self, n):
        return "%s:%d %s" % (n.file, n.line.no, n.line.text.strip().replace("\t", " ")[:60]) \
            if n.line is not None else ""

    def fresh(self):
        return dict(N="ok", Z="ok", V="ok", C="ok", nz=None, ycache=None, xcache=None, php=[])

    def emit_node(self, n):
        lines = []
        st = self.state
        if n.join or st is None:
            snaps = list(self.incoming.get(n.idx, []))
            if st is not None and n.idx - 1 >= 0 and self.falls_into(n):
                lines += self.normalize(n.live_in, n)
                snaps.append(self.snapshot())
            php = st["php"] if st else []
            st = self.state = self.fresh()
            st["php"] = php
            # Every way in already emitted (a forward join) and agreeing: keep what they agree on.
            preds = self.preds.get(n.idx, [])
            # only joins that nothing but branches can reach: a source label may be a JSR or
            # dispatch target, or named in a table, none of which are among the predecessors
            source_label = any(not lab.startswith("_") for lab in n.labels)
            if not source_label and preds and all(p < n.idx for p in preds) and len(snaps) >= len(preds) and \
                    all(x is not None for x in snaps):
                for k in ("nz", "ycache", "xcache"):
                    vals = [x[k] for x in snaps]
                    if all(v == vals[0] for v in vals):
                        st[k] = vals[0]
        for lab in n.labels:
            true = self.al.flabels.get((n.file, lab))
            if lab in self.al.ambiguous:
                # inside macro-built data: only ever used in label differences (offsets), which
                # the ROM's bytes already hold, so its exact place does not matter
                lines.append("* %s: inside macro-built data, used only in offsets" % lab)
                continue
            elif true is not None and n.addr is not None and true != n.addr:
                continue                            # emitted inside the data where it really is
            lines.append("%s" % self.names[(n.file, lab)])
        if n.kind == "label":
            if n.line is not None and n.line.kind == "assign" and n.line.sym:
                lines.append("%s\tequ\t%s\t\t\t%s" % (sanitize(sym6(n.line.sym)),
                                                     re.sub(romalign.DOT, "*", n.line.operand), self.src(n)))
            return lines
        if n.kind == "data":
            lines += self.emit_data(n)
            self.state = None
            return lines
        if n.kind == "hll":
            return lines + self.emit_hll(n)
        if (n.file, n.line.no) in NEUTRALISE:
            lines.append("* %s: %s - neutralised" % (self.src(n), NEUTRALISE[(n.file, n.line.no)]))
            return lines
        return lines + self.emit_insn(n)

    def falls_into(self, n):
        """Does the statement before n fall through into it?"""
        prev = self.nodes[n.idx - 1]
        if prev.file != n.file:
            return False
        if prev.kind == "insn" and prev.op == "JMP" and prev.hand == "folded":
            return True                         # the IF's not-taken path runs on into here
        return n.idx in prev.succ and prev.kind != "data"

    # data --------------------------------------------------------------------------------------
    def emit_data(self, n):
        data = self.rom_bytes(n)
        if not data:
            return []
        # a statement wholly inside a converted dispatch table: the table's first statement
        # emitted it
        for a, (_, _, e) in self.jtables.items():
            if a < n.addr and n.addr + len(data) <= a + 2 * e:
                return ["*\t\t\t\t\t%s (in the dispatch table above)" % self.src(n)]
        # labels the alignment resolved inside this span (macro-built tables)
        inner = sorted((a, lab) for (f, lab), a in self.al.flabels.items()
                       if f == n.file and n.addr < a < n.addr + len(data) and lab not in self.al.ambiguous
                       and self.label_node(n.file, lab) is not None
                       and self.nodes[self.label_node(n.file, lab)].addr != a)
        out, pos = [], 0
        cmt = self.src(n)
        cuts = [(a, "label", lab) for a, lab in inner] + \
            [(a, "table", a) for a in self.jtables if n.addr <= a < n.addr + len(data)]
        for a, what, lab in sorted(cuts):
            cut = a - n.addr
            if cut > pos:
                out += self.fcb(data[pos:cut], cmt)
                cmt = ""
            if what == "label":
                name = next((self.names[k] for k in self.names if k[1] == lab), sanitize(lab))
                out.append(name)
                pos = cut
            else:
                f, tname, entries = self.jtables[a]
                out.append("* %s: a dispatch table, as offsets from itself (6502: .WORD target-1)" % tname)
                for e in range(entries):
                    w = self.al.rom[a + 2 * e] | self.al.rom[a + 2 * e + 1] << 8
                    if w == 0:
                        out.append("\tfdb\t0\t\t\t\tempty entry")
                        continue
                    target = self.code_label(w + 1)
                    if "+" in target:
                        out.append("* HAND: dispatch entry $%04X is not a label" % (w + 1))
                        self.note("dispatch", f, n)
                    out.append("\tfdb\t%s-%s" % (target, tname))
                lows = []
                for e in range(entries):
                    lows += [self.al.rom[a + 2 * e], 0]
                out += self.fcb(bytes(lows), "the 6502 words' low bytes: A after the dispatch")
                pos = cut + 2 * entries
        if pos < len(data):
            out += self.fcb(data[pos:], cmt)
        for lab in n.labels:
            k = OVERRUN.get((n.file, lab))
            if k:
                end = n.addr + len(data)
                out += self.fcb(self.al.rom[end:end + k],
                                "the ROM bytes the table above is read past its end into")
        in_table = any(a <= n.addr < a + 2 * e for a, (_, _, e) in self.jtables.items())
        if not in_table and n.line is not None and (n.line.op or "").upper() in (".WORD", ".") and any(
                0x9000 <= data[k] | data[k + 1] << 8 < 0xE000 for k in range(0, len(data) - 1, 2)):
            out.insert(0, "* HAND: a table of 6502 addresses (little-endian); code addresses need offsets")
            self.note("address-table", n.file, n)
        elif not in_table and n.line is not None and (n.line.op or "").upper() == ".WORD" and any(
                0x2000 <= data[k] | data[k + 1] << 8 < 0x3000 for k in range(0, len(data) - 1, 2)):
            out.insert(0, "* HAND: vector-RAM addresses (little-endian): relocate to window A at start-up")
            self.note("vram-table", n.file, n)
        return out

    # control -----------------------------------------------------------------------------------
    def emit_hll(self, n):
        h = n.hll
        if h in ("BEGIN", "ENDIF", "THEN"):
            return ["*\t\t\t\t\t" + self.src(n)]
        if h == "ELSE":
            t = self.nodes[n.target]
            out = self.normalize(t.live_in, n)
            if "V" in t.live_in:
                out.append("\tandcc\t#$FD\t\t\t6502 ELSE clears V")
            out.append(self.branch("bra", self.target_name(n.target), n, tidx=n.target))
            self.state = None
            return out
        br = HLL_BRANCH[h]
        nxt = self.nodes[n.idx + 1] if n.idx + 1 < len(self.nodes) else None
        if h.startswith("IF") and nxt is not None and nxt.kind == "insn" and nxt.op == "JMP" \
                and not nxt.labels and n.target == n.idx + 2 and nxt.target is not None:
            # IFxx / JMP L / ENDIF: one branch to L on xx (the JMP's own line is then a comment)
            inv = {"BCS": "BCC", "BCC": "BCS", "BEQ": "BNE", "BNE": "BEQ", "BMI": "BPL", "BPL": "BMI",
                   "BVS": "BVC", "BVC": "BVS"}[br]
            saved = n.target
            n.target = nxt.target
            out = self.cond_branch(n, inv, self.jump_name(nxt))
            n.target = saved
            nxt.hand = "folded"
            return out
        return self.cond_branch(n, br, self.target_name(n.target))

    def target_name(self, idx):
        t = self.nodes[idx]
        if t.labels:
            return self.names[(t.file, t.labels[0])]
        name = "_%s_%d" % (t.file, t.idx - self.files[t.file][0])
        if not t.labels:
            t.labels.append(name)
            self.names[(t.file, name)] = name
        return name

    def snapshot(self):
        st = self.state
        return None if st is None else dict(nz=st["nz"] if st["N"] == "ok" and st["Z"] == "ok" else None,
                                            ycache=st["ycache"], xcache=st["xcache"])

    def branch(self, mn, target, n, cond=None, tidx=None):
        """A branch, short unless the assembler said it did not reach (then long)."""
        if tidx is not None:
            self.incoming[tidx].append(self.snapshot())
        self.bid += 1
        key = "%s:%d:%d" % (n.file, n.line.no if n.line else 0, self.bid)
        if key in self.long:
            mn = "lbra" if mn == "bra" else "l" + mn
        return "\t%s\t%s\t\t\t%s ;br%s" % (mn, target, self.src(n), key)

    def cond_branch(self, n, br, target):
        flag, want = BRANCH_FLAG[br]
        st = self.state
        out = []
        tnode = self.nodes[n.target] if n.target is not None else None
        need = set(tnode.live_in) if tnode is not None else set(FLAGS)
        need |= set(n.live_out)
        # put every live flag other than the tested one into 6502 form first
        out += self.normalize(frozenset(need - {flag}), n)
        s = st[flag]
        if flag == "C" and s == "inv":
            if "C" in need:
                out += self.normalize(frozenset("C"), n)
                s = "ok"
            else:
                out.append(self.branch(B6809[("C", 1 - want)], target, n, tidx=n.target))
                return out
        if s in (0, 1):
            if s == want:
                out += self.normalize(frozenset(flag) & frozenset(need), n)
                out.append(self.branch("bra", target, n, tidx=n.target))
                self.state = None                                       # nothing falls through
            else:
                out.append("*\t(branch never taken: %s is %d here)\t%s" % (flag, s, self.src(n)))
            return out
        if s == "bad":
            if flag in "NZ" and not self.fix_nz(out, n):
                out.append("* HAND: %s tested but not held (%s)" % (flag, self.src(n)))
                self.note("flag-lost", n.file, n, flag)
            elif flag in "VC":
                out.append("* HAND: %s tested but not held (%s)" % (flag, self.src(n)))
                self.note("flag-lost", n.file, n, flag)
        out.append(self.branch(B6809[(flag, want)], target, n, tidx=n.target))
        return out

    def fix_nz(self, out, n):
        st = self.state
        src = st["nz"]
        fix = {"A": "\ttsta", "X": "\ttst\t<RX", "Y": "\ttst\t<RY"}.get(src)
        if fix is None and isinstance(src, str) and src.startswith("mem:"):
            fix = "\ttst\t" + src[4:]
        if fix is None:
            return False
        out.append(fix + "\t\t\t\tN, Z again (6502 flags from " + str(src) + ")")
        st["N"] = st["Z"] = "ok"
        if st["V"] == "ok":
            st["V"] = "bad"
        return True

    def normalize(self, flags, n):
        """Make the 6809's CC hold these 6502 flags as the 6502 has them."""
        st = self.state
        if st is None:
            return []
        out = []
        if ("N" in flags and st["N"] == "bad") or ("Z" in flags and st["Z"] == "bad"):
            if not self.fix_nz(out, n):
                out.append("* HAND: N/Z needed downstream, not recoverable (%s)" % self.src(n))
                self.note("flag-lost", n.file, n, "NZ")
                st["N"] = st["Z"] = "ok"
        if "C" in flags:
            s = st["C"]
            if s == "inv":
                out += ["\ttfr\tcc,b\t\t\tcarry to 6502 sense", "\teorb\t#1", "\ttfr\tb,cc"]
            elif s == 0:
                out.append("\tandcc\t#$FE\t\t\tCLC")
            elif s == 1:
                out.append("\torcc\t#1\t\t\tSEC")
            elif s == "bad":
                out.append("* HAND: C needed downstream, not held (%s)" % self.src(n))
                self.note("flag-lost", n.file, n, "C")
            st["C"] = "ok"
        if "V" in flags:
            s = st["V"]
            if s == 0:
                out.append("\tandcc\t#$FD\t\t\tCLV")
            elif s == 1:
                out.append("\torcc\t#2")
            elif s == "bad":
                out.append("* HAND: V needed downstream, not held (%s)" % self.src(n))
                self.note("flag-lost", n.file, n, "V")
            st["V"] = "ok"
        return out

    # instructions ------------------------------------------------------------------------------
    def emit_insn(self, n):
        op = n.op
        st = self.state
        out = []
        c = "\t\t\t" + self.src(n)
        if op == "JSR":
            callee = self.nodes[n.call] if n.call is not None else None
            out += self.normalize(callee.live_in if callee else frozenset(FLAGS), n)
            out.append("\tlbsr\t%s%s" % (self.jump_name(n), c))
            php = st["php"]
            self.state = self.fresh()
            self.state["php"] = php
            return out
        if op == "JMP" and n.hand == "folded":
            return ["*\t\t\t\t\t%s (folded into the branch above)" % self.src(n)]
        if op == "JMP":
            t = self.nodes[n.target] if n.target is not None else None
            out += self.normalize(t.live_in if t else frozenset(FLAGS), n)
            if n.operand and n.operand.strip().startswith("("):
                out.append("* HAND: JMP indirect")
                self.note("jmp-indirect", n.file, n)
            if n.target is not None:
                self.incoming[n.target].append(self.snapshot())
            out.append("\tlbra\t%s%s" % (self.jump_name(n), c))
            self.state = None
            return out
        if op in ("RTS", "RTI"):
            out += self.normalize(n.live_out if op == "RTS" else frozenset(), n)
            if op == "RTI":
                out.append("* HAND: RTI (the IRQ)")
                self.note("irq", n.file, n)
            out.append("\t%s%s" % (op.lower(), c))
            self.state = None
            return out
        if op in BRANCH_FLAG:
            if n.target is None:
                out.append("* HAND: branch to an unknown label")
                self.note("unknown-label", n.file, n)
            return self.cond_branch(n, op, self.jump_name(n))
        if op == "BRK":
            out.append("* HAND: BRK")
            self.note("brk", n.file, n)
            out.append("\tswi%s" % c)
            self.state = None
            return out
        return self.emit_op(n, c)

    def jump_name(self, n):
        if n.op in ("JSR", "JMP") or n.op in BRANCH_FLAG:
            t = n.call if n.op == "JSR" else n.target
            if t is not None:
                return self.target_name(t)
            name = sanitize(sym6(self.strip(n.operand)))
            self.undefined.add(name)
            return name
        return "?"

    # the data operand of an instruction -> (setup lines, operand text, kind)
    def access(self, n, out):
        st = self.state
        mode = n.mode
        expr = self.strip(n.operand)
        v = self.operand_value(n)
        forced = mode.endswith("!")
        m = mode.rstrip("!")
        if m in ("abs/zp", "zp", "abs"):
            kind, text = self.classify(n, v, expr)
            return self.direct(n, kind, text, out)
        if m in (",X", "abs,X", "zp,X"):
            return self.indexed(n, v, expr, "x", out)
        if m in (",Y", "abs,Y", "zp,Y"):
            return self.indexed(n, v, expr, "y", out)
        if m == "(zp),Y":
            p = v
            key = ("ptr", p)
            xc = st["xcache"]
            if xc is None or xc[0] != key:
                out += ["\tldx\t<%s\t\t\t(zp),Y: the pointer (big-endian)" % self.pointers.get(p, "$%02X" % p),
                        "\tldb\t<RY", "\tabx"]
                st["xcache"] = (key, 0)
                xc = st["xcache"]
                self.clobber_nzv()
            return "%d,x" % xc[1], "ind"
        if m == "(zp,X)":
            out.append("* HAND: (zp,X)")
            self.note("zpx-indirect", n.file, n)
            out += ["\tldy\t<RXP", "\tldx\t$%02X,y" % v]
            st["ycache"] = ("x", 0)
            self.clobber_nzv()
            return ",x", "ind"
        return expr, "unknown"

    def clobber_nzv(self):
        st = self.state
        st["N"] = st["Z"] = "bad"
        if st["V"] not in (0, 1):
            st["V"] = "bad"

    def direct(self, n, kind, text, out):
        if kind == "zp":
            return "<" + text, "zp"
        if kind == "ram":
            return text + ",u", "ram"
        if kind == "rom":
            return text + ",pcr", "rom"
        if kind == "pokey":
            return text + ",u", "ram"
        if kind == "hw":
            out.append("* HAND: hardware register (%s)" % self.src(n))
            self.note("hardware", n.file, n)
            return text + ",u", "ram"
        if kind == "vram":
            out.append("* HAND: vector RAM by absolute address: through window A's pointer VWIN")
            self.note("vram-absolute", n.file, n)
            out.append("\tldx\tVWIN,u")
            self.state["xcache"] = None
            self.clobber_nzv()
            return text + ",x", "ind"
        out.append("* HAND: operand not resolved (%s)" % self.src(n))
        self.note("unresolved", n.file, n)
        return text, "unknown"

    def indexed(self, n, v, expr, reg, out):
        st = self.state
        kind, text = self.classify(n, v, expr, indexed=True)
        if kind in ("zp", "ram", "pokey", "hw"):
            if kind == "hw":
                out.append("* HAND: hardware register, indexed (%s)" % self.src(n))
                self.note("hardware", n.file, n)
            if kind == "zp" and v is not None and (v in self.pointers or v - 1 in self.pointers):
                out.append("* HAND: an indexed access to a big-endian pointer byte")
                self.note("pointer-indexed", n.file, n)
            base = text
            if reg == "x":
                yc = st["ycache"]
                if yc is None:
                    out.append("\tldy\t<RXP\t\t\tY = data base + X")
                    st["ycache"] = ("x", 0)
                    yc = st["ycache"]
                    self.clobber_nzv()
                d = yc[1]
                return "%s%s,y" % (base, "" if d == 0 else "%+d" % d), "ram"
            xc = st["xcache"]
            if xc is None or xc[0] != ("ryp",):
                out.append("\tldx\t<RYP\t\t\tX = data base + Y")
                st["xcache"] = (("ryp",), 0)
                xc = st["xcache"]
                self.clobber_nzv()
            d = xc[1]
            return "%s%s,x" % (base, "" if d == 0 else "%+d" % d), "ram"
        if kind == "rom":
            m = re.fullmatch(r"([A-Za-z_.$@0-9]+?)(?:\+(\d+))?", text)
            sym, k = (m.group(1), int(m.group(2) or 0)) if m else (text, 0)
            key = ("rom" + reg, sym)
            xc = st["xcache"]
            if xc is None or xc[0] != key:
                out += ["\tleax\t%s,pcr\t\t\tROM table + %s" % (sym, reg.upper()),
                        "\tldb\t<R%s" % reg.upper(), "\tabx"]
                st["xcache"] = (key, 0)
                xc = st["xcache"]
                self.clobber_nzv()
            return "%d,x" % (k + xc[1]), "ind"
        if kind == "vram":
            out.append("* HAND: vector RAM by absolute address, indexed")
            self.note("vram-absolute", n.file, n)
            out += ["\tldx\tVWIN,u", "\tldb\t<R%s" % reg.upper(), "\tabx"]
            st["xcache"] = None
            self.clobber_nzv()
            return text + ",x", "ind"
        out.append("* HAND: indexed operand not resolved (%s)" % self.src(n))
        self.note("unresolved", n.file, n)
        return text, "unknown"

    def x_changed(self):
        st = self.state
        st["ycache"] = None
        if st["xcache"] is not None and st["xcache"][0][0] == "romx":
            st["xcache"] = None

    def y_changed(self):
        st = self.state
        if st["xcache"] is not None and st["xcache"][0][0] in ("ptr", "ryp", "romy"):
            st["xcache"] = None

    def y_step(self, d):
        st = self.state
        xc = st["xcache"]
        if xc is not None and xc[0][0] in ("ptr", "ryp", "romy"):
            st["xcache"] = (xc[0], xc[1] + d)

    def pointer_write(self, n, text):
        """A store to a pointer byte invalidates the list cache built from it; a constant stored
        there is an address the port must relocate."""
        st = self.state
        xc = st["xcache"]
        if (n.mode or "").rstrip("!") in ("(zp),Y", "(zp,X)"):
            return False                        # a store through the pointer, not to it
        v = self.operand_value(n)
        if v is not None and v < 0x100 and (v in self.pointers or v - 1 in self.pointers):
            p = v if v in self.pointers else v - 1
            if xc is not None and xc[0] == ("ptr", p):
                st["xcache"] = None
            return True
        return False

    def set_nz(self, src):
        st = self.state
        st["N"] = st["Z"] = "ok"
        st["nz"] = src

    def v_after_load(self):
        st = self.state
        if st["V"] != 0:
            st["V"] = "bad"

    def emit_addr_macro(self, n, c):
        """LDAL/LDAH/LAH/LXL: the byte is the ROM's.  A vector-RAM address stored next into a CPU
        pointer is relocated to window A (the window is 8K aligned, so only the high byte moves);
        otherwise the address is an AVG one (for a JSRL) and stays."""
        st = self.state
        out = []
        byte = self.rom_bytes(n)[1]
        v = self.value(n, (n.line.operand or "").strip())
        nxt = self.nodes[n.idx + 1] if n.idx + 1 < len(self.nodes) else None
        to_ptr = nxt is not None and nxt.kind == "insn" and nxt.op in ("STA", "STX") and \
            nxt.mode == "abs/zp" and self.operand_value(nxt) is not None and \
            (self.operand_value(nxt) in self.pointers or self.operand_value(nxt) - 1 in self.pointers)
        vram = (v is not None and 0x2000 <= v < 0x3000) or (v is None and n.hand == "addr-hi"
                                                             and 0x20 <= byte < 0x30)
        if n.op == "LDA":
            if vram and to_ptr and n.hand == "addr-hi":
                out += ["\tlda\tVWIN,u%s" % c, "\tadda\t#$%02X-$20\t\t\tvector RAM address -> window A" % byte]
            else:
                out.append("\tlda\t#$%02X%s" % (byte, c))
            self.set_nz("A")
            if vram and to_ptr:
                st["N"] = st["Z"] = "bad"           # the 6502's flags were the arcade address's
        else:
            out += ["\tldb\t#$%02X%s" % (byte, c), "\tstb\t<RX"]
            self.set_nz("X")
            self.x_changed()
        self.v_after_load()
        if vram and not to_ptr:
            out.insert(0, "* %s: a vector-RAM address used as an AVG address (JSRL), kept" % n.line.op)
        return out

    def emit_op(self, n, c):
        op, mode = n.op, (n.mode or "").rstrip("!")
        st = self.state
        out = []
        if n.idx in self.folded:
            return ["*\t\t\t\t\t%s (in the dispatch above)" % self.src(n)]
        if n.idx in self.dispatch:
            tname, reg = self.dispatch[n.idx]
            out += self.normalize(frozenset(FLAGS) & frozenset("C"), n) if False else []
            entries = next(e for a_, (f_, t_, e) in self.jtables.items() if t_ == tname)
            out += ["\tleax\t%s,pcr%s" % (tname, c),
                    "\tldb\t<R%s\t\t\tthe 6502 pushes T+i-1 and returns into it" % reg,
                    "\tabx",
                    "\tldd\t,x\t\t\t\tthe table holds offsets from itself",
                    "\tleay\t%s,pcr" % tname,
                    "\tleay\td,y",
                    "\tlda\t%d,x\t\t\t\tA (and N, Z) as the 6502 leaves them: its word's low byte"
                    % (2 * entries),
                    "\tjmp\t,y"]
            self.state = None
            return out
        if n.hand in ("addr-lo", "addr-hi"):
            return self.emit_addr_macro(n, c)
        live = n.live_out
        dec = n.dec_in
        imm = mode == "imm"
        if imm:
            expr = self.strip(n.operand)
            v = self.value(n, expr)
            if v is None and n.size == 2:
                v = self.rom_bytes(n)[1]
            p = self.al.parsers[n.file]
            toks = [sym6(t) for t in re.findall(r"[A-Za-z_.$][A-Za-z0-9_.$]*", expr)]
            difference = re.fullmatch(r"\s*[A-Za-z_.$][A-Za-z0-9_.$]*\s*-\s*[A-Za-z_.$][A-Za-z0-9_.$]*"
                                      r"(\s*[+-]\s*[0-9A-Fa-f]+\.?)?\s*", expr)
            if not difference and any(t in self.al.labels or (t in p.ram_labels and p.syms.get(t, 0) >= 0x100)
                                      for t in toks):
                out.append("* HAND: address constant %s (relocate on the port)" % expr)
                self.note("address-constant", n.file, n, expr)
            opnd = "#$%02X" % (v & 0xFF) if v is not None else "#" + expr
        # --- A register ---
        # A store must not change the 6502's N, Z: where they are live and not known to be the
        # stored register's, the store runs inside pshs cc / puls cc.
        guard = op in ("STA", "STX", "STY") and bool(set(live) & set("NZ")) and not (
            st["N"] == "ok" and st["Z"] == "ok" and st["nz"] == ("A" if op == "STA" else op[2]))
        if guard:
            out.append("\tpshs\tcc\t\t\t\tthe store must keep N, Z")
        if op in ("LDA", "AND", "ORA", "EOR", "ADC", "SBC", "CMP", "STA", "BIT"):
            keep = st["N"] == "ok" and st["Z"] == "ok" and st["nz"] == "A"
            if not imm:
                opnd, k = self.access(n, out)
            if op == "LDA":
                out.append("\tlda\t%s%s" % (opnd, c))
                self.set_nz("A")
                self.v_after_load()
            elif op == "STA":
                self.pointer_write(n, opnd)
                out.append("\tsta\t%s%s" % (opnd, c))
                if guard:
                    out.append("\tpuls\tcc")
                    st["N"] = st["Z"] = "ok"
                else:
                    st["N"] = st["Z"] = "ok" if keep else "bad"     # the 6809 sets them from A
                    self.v_after_load()
            elif op in ("AND", "ORA", "EOR"):
                mn = {"AND": "anda", "ORA": "ora", "EOR": "eora"}[op]
                if op == "EOR" and imm and v == 0xFF and "C" not in live and "V" not in live:
                    out.append("\tcoma%s" % c)
                    st["C"] = "bad"
                else:
                    out.append("\t%s\t%s%s" % (mn, opnd, c))
                self.set_nz("A")
                self.v_after_load()
            elif op == "ADC":
                s = st["C"]
                if s == 0:
                    out.append("\tadda\t%s%s" % (opnd, c))
                else:
                    if s == 1:
                        out.append("\torcc\t#1\t\t\tSEC")
                    elif s == "inv":
                        out += ["\ttfr\tcc,b\t\t\tcarry to 6502 sense", "\teorb\t#1", "\ttfr\tb,cc"]
                    elif s == "bad":
                        out.append("* HAND: ADC with the carry not held")
                        self.note("flag-lost", n.file, n, "C")
                    out.append("\tadca\t%s%s" % (opnd, c))
                if dec == "dec":
                    out.append("\tdaa\t\t\t\tdecimal mode")
                elif dec == "mix":
                    out.append("* HAND: ADC reached in both binary and decimal mode")
                    self.note("decimal", n.file, n)
                self.set_nz("A")
                st["C"] = "ok"
                st["V"] = "ok" if dec != "dec" else "bad"
            elif op == "SBC":
                s = st["C"]
                if s == 1:
                    out.append("\tsuba\t%s%s" % (opnd, c))
                else:
                    if s == 0:
                        out.append("\torcc\t#1\t\t\tCLC: borrow in")
                    elif s == "ok":
                        out += ["\ttfr\tcc,b\t\t\tcarry to borrow sense", "\teorb\t#1", "\ttfr\tb,cc"]
                    elif s == "bad":
                        out.append("* HAND: SBC with the carry not held")
                        self.note("flag-lost", n.file, n, "C")
                    out.append("\tsbca\t%s%s" % (opnd, c))
                if dec in ("dec", "mix"):
                    out.append("* HAND: SBC in decimal mode (the 6809 has no decimal subtract)")
                    self.note("decimal", n.file, n)
                self.set_nz("A")
                st["C"] = "inv"
                st["V"] = "ok"
            elif op == "CMP":
                out.append("\tcmpa\t%s%s" % (opnd, c))
                self.set_nz("cmp")
                st["C"] = "inv"
                st["V"] = "bad" if st["V"] not in (0, 1) else "bad"
            elif op == "BIT":
                need = set(live) & set("NZV")
                if need == {"V"}:
                    # V = bit 6 of the operand: $40+$40 overflows, 0+$40 does not
                    out += ["\tldb\t%s%s" % (opnd, c), "\tandb\t#$40\t\t\tBIT: V is bit 6",
                            "\taddb\t#$40"]
                    st["N"] = st["Z"] = "bad"
                    st["nz"] = None
                    st["V"] = "ok"
                    return out
                if "V" in need or ("N" in need and "Z" in need):
                    out.append("* HAND: BIT with %s read" % "".join(sorted(need)))
                    self.note("bit", n.file, n, "".join(sorted(need)))
                    out.append("\tbita\t%s%s" % (opnd, c))
                elif "N" in need:
                    out.append("\ttst\t%s%s" % (opnd, c))
                else:
                    out.append("\tbita\t%s%s" % (opnd, c))
                st["N"] = st["Z"] = "ok"
                st["nz"] = None
                st["V"] = "bad"
            return out
        # --- X and Y ---
        if op in ("LDX", "LDY", "STX", "STY", "CPX", "CPY"):
            r = "RX" if op[2] == "X" else "RY"
            keep = st["N"] == "ok" and st["Z"] == "ok" and st["nz"] == op[2]
            if not imm:
                opnd, k = self.access(n, out)
            if op in ("LDX", "LDY"):
                if imm and v == 0 and "C" not in live and "V" not in live:
                    out.append("\tclr\t<%s%s" % (r, c))
                    st["C"] = "bad"
                else:
                    out += ["\tldb\t%s%s" % (opnd, c), "\tstb\t<%s" % r]
                self.set_nz(op[2])
                self.v_after_load()
                (self.x_changed if op[2] == "X" else self.y_changed)()
            elif op in ("STX", "STY"):
                self.pointer_write(n, opnd)
                out += ["\tldb\t<%s%s" % (r, c), "\tstb\t%s" % opnd]
                if guard:
                    out.append("\tpuls\tcc")
                    st["N"] = st["Z"] = "ok"
                else:
                    self.v_after_load()
                    st["N"] = st["Z"] = "ok" if keep else "bad"
            else:
                out += ["\tldb\t<%s%s" % (r, c), "\tcmpb\t%s" % opnd]
                self.set_nz("cmp")
                st["C"] = "inv"
                st["V"] = "bad"
            return out
        # --- read-modify-write and shifts ---
        if op in ("ASL", "LSR", "ROL", "ROR", "INC", "DEC"):
            if op in ("ROL", "ROR"):
                if st["C"] != "ok":
                    out += self.normalize(frozenset("C"), n)
            mn = op.lower()
            if mode == "implied":
                out.append("\t%sa%s" % (mn, c))
                self.set_nz("A")
            else:
                opnd, k = self.access(n, out)
                self.pointer_write(n, opnd)
                out.append("\t%s\t%s%s" % (mn, opnd, c))
                self.set_nz("mem:" + opnd if k in ("zp", "ram") else None)
            if op in ("ASL", "LSR", "ROL", "ROR"):
                st["C"] = "ok"
            if op in ("ASL", "ROL", "INC", "DEC"):
                st["V"] = "bad"
            return out
        # --- implied ---
        simple = {
            "TAX": (["\tsta\t<RX"], "A", "x"), "TAY": (["\tsta\t<RY"], "A", "y"),
            "TXA": (["\tlda\t<RX"], "A", None), "TYA": (["\tlda\t<RY"], "A", None),
        }
        if op in simple:
            code, src, ch = simple[op]
            out.append(code[0] + c)
            self.set_nz(src)
            self.v_after_load()
            if ch == "x":
                self.x_changed()
            elif ch == "y":
                self.y_changed()
            return out
        if op in ("INX", "DEX", "INY", "DEY"):
            r = "RX" if op[2] == "X" else "RY"
            out.append("\t%s\t<%s%s" % ("inc" if op[0] == "I" else "dec", r, c))
            self.set_nz(op[2])
            st["V"] = "bad"
            d = 1 if op[0] == "I" else -1
            if op[2] == "X":
                yc = st["ycache"]
                if yc is not None:
                    st["ycache"] = ("x", yc[1] + d)
                xc = st["xcache"]
                if xc is not None and xc[0][0] == "romx":
                    st["xcache"] = (xc[0], xc[1] + d)
            else:
                self.y_step(d)
            return out
        if op in ("CLC", "SEC"):
            st["C"] = 0 if op == "CLC" else 1
            out.append("*\t\t\t\t\t%s" % self.src(n))
            return out
        if op == "CLV":
            st["V"] = 0
            out.append("*\t\t\t\t\t%s" % self.src(n))
            return out
        if op in ("CLD", "SED", "NOP"):
            out.append("*\t\t\t\t\t%s" % self.src(n))
            return out
        if op == "PHA":
            out.append("\tpshs\ta%s" % c)
            return out
        if op == "PLA":
            out.append("\tpuls\ta%s" % c)
            st["nz"] = "A"
            st["N"] = st["Z"] = "bad"
            if ("N" in live or "Z" in live):
                out.append("\ttsta\t\t\t\tPLA sets N, Z; PULS does not")
                st["N"] = st["Z"] = "ok"
            return out
        if op == "PHP":
            want = {"C"} | ({"V"} if st["V"] in (0, 1) else set())
            if (st["N"] == "bad" or st["Z"] == "bad") and st["nz"] in ("A", "X", "Y"):
                want |= {"N", "Z"}
            out += self.normalize(frozenset(want), n)
            out.append("\tpshs\tcc%s" % c)
            st["php"].append(dict((k, st[k]) for k in ("N", "Z", "V", "C", "nz")))
            return out
        if op == "PLP":
            out.append("\tpuls\tcc%s" % c)
            saved = st["php"].pop() if st["php"] else dict(N="ok", Z="ok", V="ok", C="ok", nz=None)
            st.update(saved)
            return out
        if op in ("SEI", "CLI"):
            out.append("* HAND: %s (interrupt mask)" % op)
            self.note("irq", n.file, n)
            out.append("\t%s%s" % ("orcc\t#$10" if op == "SEI" else "andcc\t#$EF", c))
            return out
        if op in ("TSX", "TXS"):
            out.append("* HAND: %s (the 6502 stack pointer)" % op)
            self.note("stack", n.file, n)
            out.append("*\t%s" % c)
            return out
        out.append("* HAND: %s not translated" % op)
        self.note("other", n.file, n, op)
        return out

    # --- the module -----------------------------------------------------------------------------
    def support(self):
        """port.d, arcade.d, stubs.a and vrom.bin beside the translated files."""
        romdir = os.path.join(ROOT, "tempest_orig", "notebooks", "roms", "tempest")
        with open(os.path.join(romdir, "136002-138.np3"), "rb") as fi, \
                open(os.path.join(OUT, "vrom.bin"), "wb") as fo:
            fo.write(fi.read())
        with open(os.path.join(OUT, "port.d"), "w") as f:
            f.write("* port.d - the approved conventions (docs/status.md, D6), for the translated game.\n"
                    "RXP\tequ\t$B8\nRX\tequ\t$B9\nRYP\tequ\t$BA\nRY\tequ\t$BB\n"
                    "POKIMG\tequ\t$%04X\t\tPOKEY register image (AUDF1 at +0, AUDF2 at +8)\n"
                    "VWIN\tequ\t$%04X\t\twindow A's logical address, for absolute vector RAM\n"
                    "CLRSHD\tequ\t$%04X\t\tcolour RAM's shadow, committed by SS.ClutWrite\n"
                    "HWSHAD\tequ\t$%04X\t\tshadows of the other hardware registers (HAND)\n"
                    % (POKIMG, VWIN, CLRSHD, HWSHAD))
            for k, a in enumerate(sorted(self.hw_used)):
                f.write("HW_%04X\tequ\tHWSHAD+%d\n" % (a, k))
        names = {}
        for f in FILES + ["ALCOMN"]:
            p = self.al.parsers.get(f)
            if p is None:
                continue
            for k in p.ram_labels:
                if k in p.syms and p.syms[k] < 0x800:
                    names.setdefault(sanitize(k), p.syms[k])
        with open(os.path.join(OUT, "arcade.d"), "w") as f:
            f.write("* arcade.d - the arcade's RAM labels (offsets into the data area), from the source.\n")
            for k in sorted(names):
                f.write("%-8s equ $%04X\n" % (k, names[k]))
        defined = set(self.names.values()) | set(names)
        stubs = sorted(s for s in self.undefined if s not in defined)
        with open(os.path.join(OUT, "stubs.a"), "w") as f:
            f.write("* stubs.a - symbols the translation references and cannot define (HAND).\n")
            for s in stubs:
                f.write("%s\trts\t\t\t\tHAND: stub\n" % s)
                self.hand["stub"] += 1
                self.hand_sites["stub"].append(s)

    def build(self):
        binp = os.path.join(OUT, "tempest.bin")
        lst = os.path.join(OUT, "tempest.lst")
        for attempt in range(12):
            self.hand.clear()
            self.hand_sites.clear()
            self.undefined = set()
            self.translate_all()
            self.support()
            r = subprocess.run(["lwasm.orig", "--6809", "--format=raw", "--pragma=nosymbolcase",
                                "-I", OUT, "-o", binp, "--list=" + lst, "--symbols",
                                os.path.join(OUT, "tempest.a")], capture_output=True, text=True)
            errs = r.stdout + r.stderr
            far = self.branch_errors(errs)
            if r.returncode == 0:
                return binp, lst, errs
            if not far:
                return None, lst, errs
            self.long |= far
        return None, lst, errs

    def branch_errors(self, errs):
        """Branch ids on lines lwasm reports out of range."""
        far = set()
        for m in re.finditer(r"^(\S+\.a)\((\d+)\) : ERROR : Byte overflow", errs, re.M):
            path = os.path.join(OUT, os.path.basename(m.group(1)))
            try:
                line = open(path).read().split("\n")[int(m.group(2)) - 1]
            except (OSError, IndexError):
                continue
            k = re.search(r";br(\S+)", line)
            if k:
                far.add(k.group(1))
        return far


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-build", action="store_true")
    a = ap.parse_args()
    t = Translator()
    if a.no_build:
        t.undefined = set()
        t.translate_all()
        t.support()
        return
    binp, lst, errs = t.build()
    if binp is None:
        print(errs[:4000])
        sys.exit("assembly failed")
    size = os.path.getsize(binp)
    print("module draft: %d bytes (xlat/tempest.bin)" % size)
    print("HAND markers:")
    for k, v in t.hand.most_common():
        print("  %-18s %4d" % (k, v))


if __name__ == "__main__":
    main()
