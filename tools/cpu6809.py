#!/usr/bin/env python3
"""cpu6809.py - a 6809 for the host, cycle-counted: runs translated routines in the D6 test.

The full documented 6809 instruction set (pages 0, 2 and 3; no 6309 extensions), with the data
sheet's cycle counts including the indexed-mode extras and the long-branch-taken cycle.  SYNC and
CWAI raise, since nothing here should wait for an interrupt.

Each instruction's static cycle count (everything except a taken long branch's extra cycle) is
recorded per address in `self.static`, so a test can check the table against lwasm's own --6809
listing counts.

    cpu = CPU6809(); cpu.load(0x4000, code)
    cpu.dp = 0x20; cpu.u = 0x2000
    cycles = cpu.call(0x4000)        # JSR from outside, run to its RTS
"""

E, F, H, I, N, Z, V, C = 0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01


class Halt(Exception):
    pass


def s8(v):
    return v - 0x100 if v & 0x80 else v


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


# Indexed-mode extra cycles by postbyte type (low nibble, bit 7 set): (direct, indirect).
IDX_EXTRA = {0x0: (2, None), 0x1: (3, 6), 0x2: (2, None), 0x3: (3, 6), 0x4: (0, 3), 0x5: (1, 4),
             0x6: (1, 4), 0x8: (1, 4), 0x9: (4, 7), 0xB: (4, 7), 0xC: (1, 4), 0xD: (5, 8),
             0xF: (None, 5)}

# Page 0 ALU group, low nibble -> mnemonic for the A half ($80-$BF) and the B half ($C0-$FF).
ALU_A = ["SUBA", "CMPA", "SBCA", "SUBD", "ANDA", "BITA", "LDA", "STA", "EORA", "ADCA", "ORA",
         "ADDA", "CMPX", "JSR", "LDX", "STX"]
ALU_B = ["SUBB", "CMPB", "SBCB", "ADDD", "ANDB", "BITB", "LDB", "STB", "EORB", "ADCB", "ORB",
         "ADDB", "LDD", "STD", "LDU", "STU"]
# Base cycles (imm, dir, idx, ext) by operand class.
CYC8 = (2, 4, 4, 5)
CYC16ARITH = (4, 6, 6, 7)
CYC16LD = (3, 5, 5, 6)
CYC16ST = (None, 5, 5, 6)
RMW = {0x0: "NEG", 0x3: "COM", 0x4: "LSR", 0x6: "ROR", 0x7: "ASR", 0x8: "ASL", 0x9: "ROL",
       0xA: "DEC", 0xC: "INC", 0xD: "TST", 0xE: "JMP", 0xF: "CLR"}
BRANCH = ["BRA", "BRN", "BHI", "BLS", "BCC", "BCS", "BNE", "BEQ", "BVC", "BVS", "BPL", "BMI",
          "BGE", "BLT", "BGT", "BLE"]


class CPU6809:
    RETURN = 0xFFF0

    def __init__(self):
        self.mem = bytearray(0x10000)
        self.io = []
        self.a = self.b = 0
        self.x = self.y = self.u = 0
        self.s = 0xFE00
        self.pc = 0
        self.dp = 0
        self.cc = E | F | I
        self.cycles = 0
        self.static = {}            # pc -> static cycle count of the instruction there
        self.trace = None

    # --- memory -------------------------------------------------------------------------------
    def load(self, addr, data):
        self.mem[addr:addr + len(data)] = data

    def map_io(self, lo, hi, read=None, write=None):
        self.io.append((lo, hi, read, write))

    def rd(self, a):
        a &= 0xFFFF
        for lo, hi, r, _ in self.io:
            if lo <= a <= hi and r:
                return r(a) & 0xFF
        return self.mem[a]

    def wr(self, a, v):
        a &= 0xFFFF
        for lo, hi, _, w in self.io:
            if lo <= a <= hi and w:
                w(a, v & 0xFF)
                return
        self.mem[a] = v & 0xFF

    def rd16(self, a):
        return self.rd(a) << 8 | self.rd(a + 1)

    def wr16(self, a, v):
        self.wr(a, v >> 8)
        self.wr(a + 1, v)

    def fetch(self):
        v = self.mem[self.pc]
        self.pc = (self.pc + 1) & 0xFFFF
        return v

    def fetch16(self):
        v = self.mem[self.pc] << 8 | self.mem[(self.pc + 1) & 0xFFFF]
        self.pc = (self.pc + 2) & 0xFFFF
        return v

    # --- registers ----------------------------------------------------------------------------
    @property
    def d(self):
        return self.a << 8 | self.b

    @d.setter
    def d(self, v):
        self.a = (v >> 8) & 0xFF
        self.b = v & 0xFF

    def getr(self, code):
        return {0: lambda: self.d, 1: lambda: self.x, 2: lambda: self.y, 3: lambda: self.u,
                4: lambda: self.s, 5: lambda: self.pc, 8: lambda: self.a, 9: lambda: self.b,
                0xA: lambda: self.cc, 0xB: lambda: self.dp}[code]()

    def setr(self, code, v):
        if code == 0:
            self.d = v & 0xFFFF
        elif code in (1, 2, 3, 4, 5):
            setattr(self, {1: "x", 2: "y", 3: "u", 4: "s", 5: "pc"}[code], v & 0xFFFF)
        elif code in (8, 9, 0xA, 0xB):
            setattr(self, {8: "a", 9: "b", 0xA: "cc", 0xB: "dp"}[code], v & 0xFF)
        else:
            raise Halt("bad register code %X" % code)

    def flag(self, f, on):
        self.cc = (self.cc | f) if on else (self.cc & ~f & 0xFF)

    def nz8(self, v):
        v &= 0xFF
        self.cc = (self.cc & ~(N | Z)) | (N if v & 0x80 else 0) | (0 if v else Z)
        return v

    def nz16(self, v):
        v &= 0xFFFF
        self.cc = (self.cc & ~(N | Z)) | (N if v & 0x8000 else 0) | (0 if v else Z)
        return v

    # --- stack --------------------------------------------------------------------------------
    def push8(self, sp, v):
        val = (getattr(self, sp) - 1) & 0xFFFF
        setattr(self, sp, val)
        self.wr(val, v)

    def push16(self, sp, v):
        self.push8(sp, v)
        self.push8(sp, v >> 8)

    def pull8(self, sp):
        a = getattr(self, sp)
        setattr(self, sp, (a + 1) & 0xFFFF)
        return self.rd(a)

    def pull16(self, sp):
        return self.pull8(sp) << 8 | self.pull8(sp)

    # --- addressing ---------------------------------------------------------------------------
    def indexed(self):
        """Decode an indexed postbyte; returns (effective address, extra cycles)."""
        pb = self.fetch()
        rn = ("x", "y", "u", "s")[(pb >> 5) & 3]
        if not pb & 0x80:
            off = pb & 0x1F
            if off & 0x10:
                off -= 0x20
            return (getattr(self, rn) + off) & 0xFFFF, 1
        t = pb & 0x0F
        ind = bool(pb & 0x10)
        if t not in IDX_EXTRA:
            raise Halt("illegal indexed postbyte %02X" % pb)
        extra = IDX_EXTRA[t][1 if ind else 0]
        if extra is None:
            raise Halt("illegal indexed postbyte %02X" % pb)
        r = getattr(self, rn)
        if t == 0x0:
            ea = r
            setattr(self, rn, (r + 1) & 0xFFFF)
        elif t == 0x1:
            ea = r
            setattr(self, rn, (r + 2) & 0xFFFF)
        elif t == 0x2:
            ea = (r - 1) & 0xFFFF
            setattr(self, rn, ea)
        elif t == 0x3:
            ea = (r - 2) & 0xFFFF
            setattr(self, rn, ea)
        elif t == 0x4:
            ea = r
        elif t == 0x5:
            ea = (r + s8(self.b)) & 0xFFFF
        elif t == 0x6:
            ea = (r + s8(self.a)) & 0xFFFF
        elif t == 0x8:
            ea = (r + s8(self.fetch())) & 0xFFFF
        elif t == 0x9:
            ea = (r + self.fetch16()) & 0xFFFF
        elif t == 0xB:
            ea = (r + self.d) & 0xFFFF
        elif t == 0xC:
            off = s8(self.fetch())
            ea = (self.pc + off) & 0xFFFF
        elif t == 0xD:
            off = self.fetch16()
            ea = (self.pc + off) & 0xFFFF
        else:
            ea = self.fetch16()
        if ind:
            ea = self.rd16(ea)
        return ea, extra

    def operand_ea(self, mode):
        """mode 1 direct, 2 indexed, 3 extended: (ea, extra cycles)."""
        if mode == 1:
            return (self.dp << 8) | self.fetch(), 0
        if mode == 2:
            return self.indexed()
        return self.fetch16(), 0

    # --- arithmetic ---------------------------------------------------------------------------
    def add8(self, r, m, c=0):
        s = r + m + c
        self.flag(H, ((r & 0xF) + (m & 0xF) + c) & 0x10)
        self.flag(V, (~(r ^ m) & (r ^ s)) & 0x80)
        self.flag(C, s & 0x100)
        return self.nz8(s)

    def sub8(self, r, m, c=0):
        s = r - m - c
        self.flag(V, ((r ^ m) & (r ^ s)) & 0x80)
        self.flag(C, s & 0x100)
        return self.nz8(s)

    def add16(self, r, m):
        s = r + m
        self.flag(V, (~(r ^ m) & (r ^ s)) & 0x8000)
        self.flag(C, s & 0x10000)
        return self.nz16(s)

    def sub16(self, r, m):
        s = r - m
        self.flag(V, ((r ^ m) & (r ^ s)) & 0x8000)
        self.flag(C, s & 0x10000)
        return self.nz16(s)

    def rmw(self, mn, m):
        c = self.cc & C
        if mn == "NEG":
            r = self.sub8(0, m)
        elif mn == "COM":
            r = self.nz8(~m)
            self.flag(V, 0)
            self.flag(C, 1)
        elif mn == "LSR":
            self.flag(C, m & 1)
            r = self.nz8(m >> 1)
        elif mn == "ROR":
            self.flag(C, m & 1)
            r = self.nz8((m >> 1) | (c << 7))
        elif mn == "ASR":
            self.flag(C, m & 1)
            r = self.nz8((m >> 1) | (m & 0x80))
        elif mn == "ASL":
            self.flag(C, m & 0x80)
            self.flag(V, (m ^ (m << 1)) & 0x80)
            r = self.nz8(m << 1)
        elif mn == "ROL":
            self.flag(C, m & 0x80)
            self.flag(V, (m ^ (m << 1)) & 0x80)
            r = self.nz8((m << 1) | c)
        elif mn == "DEC":
            self.flag(V, m == 0x80)
            r = self.nz8(m - 1)
        elif mn == "INC":
            self.flag(V, m == 0x7F)
            r = self.nz8(m + 1)
        elif mn == "TST":
            self.nz8(m)
            self.flag(V, 0)
            r = None
        elif mn == "CLR":
            self.cc = (self.cc & ~(N | V | C)) | Z
            r = 0
        else:
            raise Halt(mn)
        return r

    def cond(self, k):
        cc = self.cc
        n, z, v, c = bool(cc & N), bool(cc & Z), bool(cc & V), bool(cc & C)
        return [True, False, not (c or z), c or z, not c, c, not z, z, not v, v, not n, n,
                n == v, n != v, (not z) and n == v, z or n != v][k]

    # --- execution ----------------------------------------------------------------------------
    def call(self, addr, limit=10_000_000):
        self.push16("s", self.RETURN)
        self.pc = addr
        start = self.cycles
        while self.pc != self.RETURN:
            self.step()
            if self.cycles - start > limit:
                raise Halt("cycle limit at %04X" % self.pc)
        return self.cycles - start

    def step(self):
        pc0 = self.pc
        if self.trace:
            self.trace(self, pc0)
        op = self.fetch()
        page = 0
        if op in (0x10, 0x11):
            page = op
            op = self.fetch()
        cyc, dyn = self.execute(page, op)
        self.static[pc0] = cyc
        self.cycles += cyc + dyn

    def execute(self, page, op):
        """Run one instruction; returns (static cycles, dynamic extra cycles)."""
        hi, lo = op >> 4, op & 0x0F
        if page == 0x10:
            return self.page2(op)
        if page == 0x11:
            return self.page3(op)

        # Read-modify-write group: $00 direct, $40 A, $50 B, $60 indexed, $70 extended.
        if hi in (0x0, 0x4, 0x5, 0x6, 0x7) and lo in RMW:
            mn = RMW[lo]
            if hi in (0x4, 0x5):
                if mn == "JMP":
                    raise Halt("illegal opcode %02X" % op)
                reg = "a" if hi == 4 else "b"
                r = self.rmw(mn, getattr(self, reg))
                if r is not None:
                    setattr(self, reg, r)
                return 2, 0
            mode = {0x0: 1, 0x6: 2, 0x7: 3}[hi]
            ea, extra = self.operand_ea(mode)
            if mn == "JMP":
                self.pc = ea
                return {1: 3, 2: 3, 3: 4}[mode] + extra, 0
            r = self.rmw(mn, self.rd(ea))
            if r is not None:
                self.wr(ea, r)
            return {1: 6, 2: 6, 3: 7}[mode] + extra, 0

        if hi == 0x2:
            off = s8(self.fetch())
            if self.cond(lo):
                self.pc = (self.pc + off) & 0xFFFF
            return 3, 0

        if hi in (0x8, 0x9, 0xA, 0xB, 0xC, 0xD, 0xE, 0xF):
            return self.alu(op)

        if op == 0x12:
            return 2, 0
        if op == 0x16:
            off = self.fetch16()
            self.pc = (self.pc + off) & 0xFFFF
            return 5, 0
        if op == 0x17:
            off = self.fetch16()
            self.push16("s", self.pc)
            self.pc = (self.pc + off) & 0xFFFF
            return 9, 0
        if op == 0x19:
            a, cc = self.a, self.cc
            cf = 0
            if (a & 0x0F) > 9 or cc & H:
                cf |= 0x06
            if a > 0x99 or cc & C or ((a & 0xF0) > 0x80 and (a & 0x0F) > 9):
                cf |= 0x60
            s = a + cf
            self.a = self.nz8(s)
            self.flag(C, (cc & C) or s > 0xFF)
            return 2, 0
        if op == 0x1A:
            self.cc |= self.fetch()
            return 3, 0
        if op == 0x1C:
            self.cc &= self.fetch()
            return 3, 0
        if op == 0x1D:
            self.a = 0xFF if self.b & 0x80 else 0
            self.nz16(self.d)
            return 2, 0
        if op in (0x1E, 0x1F):
            pb = self.fetch()
            src, dst = pb >> 4, pb & 0x0F
            if (src < 8) != (dst < 8):
                raise Halt("TFR/EXG between sizes %02X" % pb)
            if op == 0x1F:
                self.setr(dst, self.getr(src))
                return 6, 0
            a, b = self.getr(src), self.getr(dst)
            self.setr(src, b)
            self.setr(dst, a)
            return 8, 0
        if 0x30 <= op <= 0x33:
            ea, extra = self.indexed()
            reg = "xysu"[op - 0x30]            # LEAX, LEAY, LEAS, LEAU
            setattr(self, reg, ea)
            if op in (0x30, 0x31):
                self.flag(Z, ea == 0)
            return 4 + extra, 0
        if op in (0x34, 0x35, 0x36, 0x37):
            mask = self.fetch()
            sp = "s" if op in (0x34, 0x35) else "u"
            other = "u" if sp == "s" else "s"
            n = 0
            if op in (0x34, 0x36):
                for bit, r in ((0x80, "pc"), (0x40, other), (0x20, "y"), (0x10, "x")):
                    if mask & bit:
                        self.push16(sp, getattr(self, r))
                        n += 2
                for bit, r in ((0x08, "dp"), (0x04, "b"), (0x02, "a"), (0x01, "cc")):
                    if mask & bit:
                        self.push8(sp, getattr(self, r))
                        n += 1
            else:
                for bit, r in ((0x01, "cc"), (0x02, "a"), (0x04, "b"), (0x08, "dp")):
                    if mask & bit:
                        setattr(self, r, self.pull8(sp))
                        n += 1
                for bit, r in ((0x10, "x"), (0x20, "y"), (0x40, other), (0x80, "pc")):
                    if mask & bit:
                        setattr(self, r, self.pull16(sp))
                        n += 2
            return 5 + n, 0
        if op == 0x39:
            self.pc = self.pull16("s")
            return 5, 0
        if op == 0x3A:
            self.x = (self.x + self.b) & 0xFFFF
            return 3, 0
        if op == 0x3B:
            self.cc = self.pull8("s")
            if self.cc & E:
                for r in ("a", "b", "dp"):
                    setattr(self, r, self.pull8("s"))
                for r in ("x", "y", "u"):
                    setattr(self, r, self.pull16("s"))
                self.pc = self.pull16("s")
                return 15, 0
            self.pc = self.pull16("s")
            return 6, 0
        if op == 0x3D:
            r = self.a * self.b
            self.d = r
            self.flag(Z, r == 0)
            self.flag(C, r & 0x80)
            return 11, 0
        raise Halt("unimplemented opcode %02X at %04X" % (op, (self.pc - 1) & 0xFFFF))

    def alu(self, op):
        hi, lo = op >> 4, op & 0x0F
        half_a = hi < 0xC
        mn = (ALU_A if half_a else ALU_B)[lo]
        mode = (hi - 0x8) & 3           # 0 imm, 1 dir, 2 idx, 3 ext
        if mn in ("SUBD", "ADDD", "CMPX"):
            table = CYC16ARITH
        elif mn in ("LDX", "LDD", "LDU"):
            table = CYC16LD
        elif mn in ("STX", "STD", "STU"):
            table = CYC16ST
        elif mn == "JSR":
            table = (7, 7, 7, 8)        # imm slot is BSR
        else:
            table = CYC8
        base = table[mode]
        if base is None or (mode == 0 and mn in ("STA", "STB")):
            raise Halt("illegal opcode %02X" % op)
        wide = mn in ("SUBD", "ADDD", "CMPX", "LDX", "LDD", "LDU", "STX", "STD", "STU")
        extra = 0
        if mn == "JSR" and mode == 0:        # BSR
            off = s8(self.fetch())
            self.push16("s", self.pc)
            self.pc = (self.pc + off) & 0xFFFF
            return 7, 0
        if mode == 0:
            m = self.fetch16() if wide else self.fetch()
            ea = None
        else:
            ea, extra = self.operand_ea(mode)
            m = None
        if mn == "JSR":
            self.push16("s", self.pc)
            self.pc = ea
            return base + extra, 0

        def val():
            if m is not None:
                return m
            return self.rd16(ea) if wide else self.rd(ea)

        reg = "a" if half_a else "b"
        if mn in ("SUBA", "SUBB"):
            setattr(self, reg, self.sub8(getattr(self, reg), val()))
        elif mn in ("CMPA", "CMPB"):
            self.sub8(getattr(self, reg), val())
        elif mn in ("SBCA", "SBCB"):
            setattr(self, reg, self.sub8(getattr(self, reg), val(), self.cc & C))
        elif mn in ("ADDA", "ADDB"):
            setattr(self, reg, self.add8(getattr(self, reg), val()))
        elif mn in ("ADCA", "ADCB"):
            setattr(self, reg, self.add8(getattr(self, reg), val(), self.cc & C))
        elif mn in ("ANDA", "ANDB", "BITA", "BITB", "EORA", "EORB", "ORA", "ORB", "LDA", "LDB"):
            v = val()
            r = getattr(self, reg)
            k = mn[:-1] if mn not in ("ORA", "ORB") else "OR"
            res = {"AND": r & v, "BIT": r & v, "EOR": r ^ v, "OR": r | v, "LD": v}[k]
            self.nz8(res)
            self.flag(V, 0)
            if k != "BIT":
                setattr(self, reg, res)
        elif mn in ("STA", "STB"):
            v = getattr(self, reg)
            self.wr(ea, v)
            self.nz8(v)
            self.flag(V, 0)
        elif mn == "SUBD":
            self.d = self.sub16(self.d, val())
        elif mn == "ADDD":
            self.d = self.add16(self.d, val())
        elif mn == "CMPX":
            self.sub16(self.x, val())
        elif mn in ("LDX", "LDD", "LDU"):
            v = val()
            self.nz16(v)
            self.flag(V, 0)
            if mn == "LDD":
                self.d = v
            else:
                setattr(self, mn[2].lower(), v)
        elif mn in ("STX", "STD", "STU"):
            v = self.d if mn == "STD" else getattr(self, mn[2].lower())
            self.wr16(ea, v)
            self.nz16(v)
            self.flag(V, 0)
        else:
            raise Halt(mn)
        return base + extra, 0

    def page2(self, op):
        hi, lo = op >> 4, op & 0x0F
        if hi == 0x2:
            off = self.fetch16()
            if self.cond(lo):
                self.pc = (self.pc + off) & 0xFFFF
                return 5, 1
            return 5, 0
        mode = (hi - 0x8) & 3
        if lo in (0x3, 0xC) and hi >= 0x8 and hi <= 0xB:      # CMPD, CMPY
            base = (5, 7, 7, 8)[mode]
            if mode == 0:
                m, extra = self.fetch16(), 0
            else:
                ea, extra = self.operand_ea(mode)
                m = self.rd16(ea)
            self.sub16(self.d if lo == 0x3 else self.y, m)
            return base + extra, 0
        if lo in (0xE, 0xF) and hi >= 0x8:                      # LDY/STY ($8x-$Bx), LDS/STS ($Cx-$Fx)
            reg = "y" if hi <= 0xB else "s"
            store = lo == 0xF
            if store and mode == 0:
                raise Halt("illegal opcode 10 %02X" % op)
            base = (4, 6, 6, 7)[mode]
            if mode == 0:
                v = self.fetch16()
                extra = 0
            else:
                ea, extra = self.operand_ea(mode)
            if store:
                v = getattr(self, reg)
                self.wr16(ea, v)
            else:
                if mode:
                    v = self.rd16(ea)
                setattr(self, reg, v)
            self.nz16(v)
            self.flag(V, 0)
            return base + extra, 0
        raise Halt("unimplemented opcode 10 %02X" % op)

    def page3(self, op):
        hi, lo = op >> 4, op & 0x0F
        if lo in (0x3, 0xC) and 0x8 <= hi <= 0xB:              # CMPU, CMPS
            mode = hi - 0x8
            base = (5, 7, 7, 8)[mode]
            if mode == 0:
                m, extra = self.fetch16(), 0
            else:
                ea, extra = self.operand_ea(mode)
                m = self.rd16(ea)
            self.sub16(self.u if lo == 0x3 else self.s, m)
            return base + extra, 0
        raise Halt("unimplemented opcode 11 %02X" % op)


def listing_cycles(path):
    """lwasm --6809 listing with 'opt c' -> {offset: (base, extra, line)}.  '[5+?]' (a long branch)
    counts as 5, matching `static`; base + extra is the instruction's static count."""
    import re
    out = {}
    for line in open(path):
        m = re.match(r"([0-9A-F]{4}) [0-9A-F]+\s+\(.*?\):\d+ \[(\d+)(?:\+(\d+|\?))?\]", line)
        if m:
            base = int(m.group(2))
            ext = m.group(3)
            out[int(m.group(1), 16)] = (base, 0 if ext in (None, "?") else int(ext), line.rstrip())
    return out
