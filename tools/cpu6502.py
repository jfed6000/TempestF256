#!/usr/bin/env python3
"""cpu6502.py - an NMOS 6502 for the host, cycle-counted: the D6 differential test's oracle.

Runs Atari's own routines out of the Rev 3 ROM image so a translated routine can be checked against
the original on the same inputs.  Documented opcodes only (an undocumented one raises), decimal mode
as the NMOS part does it for valid BCD, cycle counts from the MOS data sheet including the page-cross
and taken-branch penalties.

Memory is a 64K bytearray.  Reads and writes in a range can be diverted to a device with
map_io(lo, hi, read_fn, write_fn); the Math Box model below is one.

    cpu = CPU6502(); cpu.load(0x9000, rom)
    cycles = cpu.call(0xCD0A)        # JSR to it, run to its RTS; returns the cycles spent inside
"""

N, V, U, B, D, I, Z, C = 0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01

# (mnemonic, mode, base cycles); mode names below.  Page-cross +1 applies to the reads marked in
# PAGE_PENALTY; stores and read-modify-writes are already at their fixed count.
OPS = {}


def _op(code, mn, mode, cyc):
    OPS[code] = (mn, mode, cyc)


for mn, base in (("ORA", 0x00), ("AND", 0x20), ("EOR", 0x40), ("ADC", 0x60), ("STA", 0x80),
                 ("LDA", 0xA0), ("CMP", 0xC0), ("SBC", 0xE0)):
    st = mn == "STA"
    _op(base + 0x01, mn, "izx", 6)
    _op(base + 0x05, mn, "zp", 3)
    if not st:
        _op(base + 0x09, mn, "imm", 2)
    _op(base + 0x0D, mn, "abs", 4)
    _op(base + 0x11, mn, "izy", 6 if st else 5)
    _op(base + 0x15, mn, "zpx", 4)
    _op(base + 0x19, mn, "aby", 5 if st else 4)
    _op(base + 0x1D, mn, "abx", 5 if st else 4)
for mn, base in (("ASL", 0x00), ("ROL", 0x20), ("LSR", 0x40), ("ROR", 0x60)):
    _op(base + 0x06, mn, "zp", 5)
    _op(base + 0x0A, mn, "acc", 2)
    _op(base + 0x0E, mn, "abs", 6)
    _op(base + 0x16, mn, "zpx", 6)
    _op(base + 0x1E, mn, "abx", 7)
for mn, base in (("DEC", 0xC0), ("INC", 0xE0)):
    _op(base + 0x06, mn, "zp", 5)
    _op(base + 0x0E, mn, "abs", 6)
    _op(base + 0x16, mn, "zpx", 6)
    _op(base + 0x1E, mn, "abx", 7)
for code, mn in ((0x10, "BPL"), (0x30, "BMI"), (0x50, "BVC"), (0x70, "BVS"), (0x90, "BCC"),
                 (0xB0, "BCS"), (0xD0, "BNE"), (0xF0, "BEQ")):
    _op(code, mn, "rel", 2)
for code, mn in ((0x18, "CLC"), (0x38, "SEC"), (0x58, "CLI"), (0x78, "SEI"), (0xB8, "CLV"),
                 (0xD8, "CLD"), (0xF8, "SED"), (0xAA, "TAX"), (0x8A, "TXA"), (0xA8, "TAY"),
                 (0x98, "TYA"), (0xBA, "TSX"), (0x9A, "TXS"), (0xCA, "DEX"), (0xE8, "INX"),
                 (0x88, "DEY"), (0xC8, "INY"), (0xEA, "NOP")):
    _op(code, mn, "imp", 2)
_op(0x48, "PHA", "imp", 3)
_op(0x08, "PHP", "imp", 3)
_op(0x68, "PLA", "imp", 4)
_op(0x28, "PLP", "imp", 4)
_op(0x20, "JSR", "abs", 6)
_op(0x60, "RTS", "imp", 6)
_op(0x40, "RTI", "imp", 6)
_op(0x00, "BRK", "imp", 7)
_op(0x4C, "JMP", "abs", 3)
_op(0x6C, "JMP", "ind", 5)
_op(0x24, "BIT", "zp", 3)
_op(0x2C, "BIT", "abs", 4)
for mn, base in (("CPY", 0xC0), ("CPX", 0xE0)):
    _op(base + 0x00, mn, "imm", 2)
    _op(base + 0x04, mn, "zp", 3)
    _op(base + 0x0C, mn, "abs", 4)
_op(0xA2, "LDX", "imm", 2)
_op(0xA6, "LDX", "zp", 3)
_op(0xAE, "LDX", "abs", 4)
_op(0xB6, "LDX", "zpy", 4)
_op(0xBE, "LDX", "aby", 4)
_op(0xA0, "LDY", "imm", 2)
_op(0xA4, "LDY", "zp", 3)
_op(0xAC, "LDY", "abs", 4)
_op(0xB4, "LDY", "zpx", 4)
_op(0xBC, "LDY", "abx", 4)
_op(0x86, "STX", "zp", 3)
_op(0x8E, "STX", "abs", 4)
_op(0x96, "STX", "zpy", 4)
_op(0x84, "STY", "zp", 3)
_op(0x8C, "STY", "abs", 4)
_op(0x94, "STY", "zpx", 4)

SIZE = {"imp": 1, "acc": 1, "imm": 2, "zp": 2, "zpx": 2, "zpy": 2, "izx": 2, "izy": 2, "rel": 2,
        "abs": 3, "abx": 3, "aby": 3, "ind": 3}
PAGE_PENALTY = {"ORA", "AND", "EOR", "ADC", "LDA", "CMP", "SBC", "LDX", "LDY"}


class Halt(Exception):
    pass


class CPU6502:
    RETURN = 0xFFF0     # call() pushes RETURN-1; reaching RETURN ends the call

    def __init__(self):
        self.mem = bytearray(0x10000)
        self.io = []                    # (lo, hi, read, write)
        self.a = self.x = self.y = 0
        self.sp = 0xFF
        self.p = U | I
        self.pc = 0
        self.cycles = 0
        self.trace = None               # callable(cpu, pc, mnemonic) before each instruction
        self.zpwrap = []                # pcs of zp,X / zp,Y accesses that wrapped within page 0
        self.step_hook = None           # like trace, for test harnesses
        self.badbcd = []                # decimal ADC/SBC on digits that are not BCD

    def load(self, addr, data):
        self.mem[addr:addr + len(data)] = data

    def map_io(self, lo, hi, read=None, write=None):
        self.io.append((lo, hi, read, write))

    def rd(self, a):
        for lo, hi, r, _ in self.io:
            if lo <= a <= hi and r:
                return r(a) & 0xFF
        return self.mem[a]

    def wr(self, a, v):
        for lo, hi, _, w in self.io:
            if lo <= a <= hi and w:
                w(a, v & 0xFF)
                return
        self.mem[a] = v & 0xFF

    def rd16(self, a):
        return self.rd(a) | self.rd((a + 1) & 0xFFFF) << 8

    def push(self, v):
        self.mem[0x100 + self.sp] = v & 0xFF
        self.sp = (self.sp - 1) & 0xFF

    def pull(self):
        self.sp = (self.sp + 1) & 0xFF
        return self.mem[0x100 + self.sp]

    def nz(self, v):
        self.p = (self.p & ~(N | Z)) | (v & N) | (0 if v & 0xFF else Z)
        return v & 0xFF

    def flag(self, f, on):
        self.p = (self.p | f) if on else (self.p & ~f)

    def call(self, addr, limit=10_000_000):
        """JSR to addr from outside and run until it returns.  Cycles counted from the first
        instruction of the routine through its RTS (the caller's JSR is not included)."""
        r = self.RETURN - 1
        self.push(r >> 8)
        self.push(r)
        self.pc = addr
        start = self.cycles
        while self.pc != self.RETURN:
            self.step()
            if self.cycles - start > limit:
                raise Halt("cycle limit at %04X" % self.pc)
        return self.cycles - start

    def ea(self, mode):
        """Effective address for mode; returns (address, page_crossed)."""
        pc = self.pc
        if mode == "zp":
            return self.mem[pc], False
        if mode == "zpx":
            if self.mem[pc] + self.x > 0xFF:
                self.zpwrap.append(pc - 1)
            return (self.mem[pc] + self.x) & 0xFF, False
        if mode == "zpy":
            if self.mem[pc] + self.y > 0xFF:
                self.zpwrap.append(pc - 1)
            return (self.mem[pc] + self.y) & 0xFF, False
        if mode == "abs":
            return self.mem[pc] | self.mem[pc + 1] << 8, False
        if mode in ("abx", "aby"):
            base = self.mem[pc] | self.mem[pc + 1] << 8
            a = (base + (self.x if mode == "abx" else self.y)) & 0xFFFF
            return a, (a ^ base) & 0xFF00 != 0
        if mode == "izx":
            z = (self.mem[pc] + self.x) & 0xFF
            return self.mem[z] | self.mem[(z + 1) & 0xFF] << 8, False
        if mode == "izy":
            z = self.mem[pc]
            base = self.mem[z] | self.mem[(z + 1) & 0xFF] << 8
            a = (base + self.y) & 0xFFFF
            return a, (a ^ base) & 0xFF00 != 0
        if mode == "ind":
            p = self.mem[pc] | self.mem[pc + 1] << 8
            return self.mem[p] | self.mem[(p & 0xFF00) | ((p + 1) & 0xFF)] << 8, False
        raise ValueError(mode)

    def adc(self, m):
        a, c = self.a, self.p & C
        if self.p & D and ((a & 0x0F) > 9 or a > 0x99 or (m & 0x0F) > 9 or m > 0x99):
            self.badbcd.append(self.pc)
        if self.p & D:
            lo = (a & 0x0F) + (m & 0x0F) + c
            if lo > 9:
                lo += 6
            hi = (a >> 4) + (m >> 4) + (lo > 0x0F)
            b = (a + m + c) & 0xFF
            self.flag(Z, b == 0)
            self.flag(N, hi & 8)
            self.flag(V, (~(a ^ m) & (a ^ (hi << 4)) & 0x80))
            if hi > 9:
                hi += 6
            self.flag(C, hi > 0x0F)
            self.a = ((hi << 4) | (lo & 0x0F)) & 0xFF
            return
        s = a + m + c
        self.flag(C, s > 0xFF)
        self.flag(V, (~(a ^ m) & (a ^ s) & 0x80))
        self.a = self.nz(s)

    def sbc(self, m):
        a, c = self.a, self.p & C
        if self.p & D and ((a & 0x0F) > 9 or a > 0x99 or (m & 0x0F) > 9 or m > 0x99):
            self.badbcd.append(self.pc)
        s = a - m - (1 - c)
        if self.p & D:
            lo = (a & 0x0F) - (m & 0x0F) - (1 - c)
            hi = (a >> 4) - (m >> 4) - (lo < 0)
            if lo < 0:
                lo -= 6
            if hi < 0:
                hi -= 6
            self.flag(C, s >= 0)
            self.flag(V, ((a ^ m) & (a ^ s) & 0x80))
            self.nz(s & 0xFF)
            self.a = ((hi << 4) | (lo & 0x0F)) & 0xFF
            return
        self.flag(C, s >= 0)
        self.flag(V, ((a ^ m) & (a ^ s) & 0x80))
        self.a = self.nz(s)

    def cmp(self, r, m):
        s = r - m
        self.flag(C, s >= 0)
        self.nz(s & 0xFF)

    def step(self):
        pc0 = self.pc
        self.opc = pc0                  # the instruction being executed, for I/O hooks
        op = self.mem[pc0]
        if op not in OPS:
            raise Halt("undocumented opcode %02X at %04X" % (op, pc0))
        mn, mode, cyc = OPS[op]
        if self.step_hook:
            self.step_hook(self, pc0, mn)
        if self.trace:
            self.trace(self, pc0, mn)
        self.pc = (pc0 + 1) & 0xFFFF
        addr = None
        if mode not in ("imp", "acc", "imm", "rel"):
            addr, crossed = self.ea(mode)
            if crossed and mn in PAGE_PENALTY:
                cyc += 1
        opnd_pc = self.pc
        self.pc = (pc0 + SIZE[mode]) & 0xFFFF

        def val():
            return self.mem[opnd_pc] if mode == "imm" else self.rd(addr)

        if mn == "LDA":
            self.a = self.nz(val())
        elif mn == "LDX":
            self.x = self.nz(val())
        elif mn == "LDY":
            self.y = self.nz(val())
        elif mn == "STA":
            self.wr(addr, self.a)
        elif mn == "STX":
            self.wr(addr, self.x)
        elif mn == "STY":
            self.wr(addr, self.y)
        elif mn == "ORA":
            self.a = self.nz(self.a | val())
        elif mn == "AND":
            self.a = self.nz(self.a & val())
        elif mn == "EOR":
            self.a = self.nz(self.a ^ val())
        elif mn == "ADC":
            self.adc(val())
        elif mn == "SBC":
            self.sbc(val())
        elif mn == "CMP":
            self.cmp(self.a, val())
        elif mn == "CPX":
            self.cmp(self.x, val())
        elif mn == "CPY":
            self.cmp(self.y, val())
        elif mn == "BIT":
            m = self.rd(addr)
            self.flag(Z, (self.a & m) == 0)
            self.p = (self.p & ~(N | V)) | (m & (N | V))
        elif mn in ("ASL", "LSR", "ROL", "ROR", "INC", "DEC"):
            m = self.a if mode == "acc" else self.rd(addr)
            c = self.p & C
            if mn == "ASL":
                self.flag(C, m & 0x80)
                m = m << 1
            elif mn == "LSR":
                self.flag(C, m & 1)
                m = m >> 1
            elif mn == "ROL":
                self.flag(C, m & 0x80)
                m = (m << 1) | c
            elif mn == "ROR":
                self.flag(C, m & 1)
                m = (m >> 1) | (c << 7)
            elif mn == "INC":
                m = m + 1
            else:
                m = m - 1
            m = self.nz(m & 0xFF)
            if mode == "acc":
                self.a = m
            else:
                self.wr(addr, m)
        elif mode == "rel":
            cond = {"BPL": not self.p & N, "BMI": self.p & N, "BVC": not self.p & V,
                    "BVS": self.p & V, "BCC": not self.p & C, "BCS": self.p & C,
                    "BNE": not self.p & Z, "BEQ": self.p & Z}[mn]
            if cond:
                off = self.mem[opnd_pc]
                tgt = (self.pc + (off - 256 if off & 0x80 else off)) & 0xFFFF
                cyc += 1 + ((tgt ^ self.pc) & 0xFF00 != 0)
                self.pc = tgt
        elif mn == "JMP":
            self.pc = addr
        elif mn == "JSR":
            r = (pc0 + 2) & 0xFFFF
            self.push(r >> 8)
            self.push(r)
            self.pc = addr
        elif mn == "RTS":
            lo = self.pull()
            self.pc = ((self.pull() << 8 | lo) + 1) & 0xFFFF
        elif mn == "RTI":
            self.p = (self.pull() | U) & ~B
            lo = self.pull()
            self.pc = self.pull() << 8 | lo
        elif mn == "PHA":
            self.push(self.a)
        elif mn == "PHP":
            self.push(self.p | B | U)
        elif mn == "PLA":
            self.a = self.nz(self.pull())
        elif mn == "PLP":
            self.p = (self.pull() | U) & ~B
        elif mn == "TAX":
            self.x = self.nz(self.a)
        elif mn == "TXA":
            self.a = self.nz(self.x)
        elif mn == "TAY":
            self.y = self.nz(self.a)
        elif mn == "TYA":
            self.a = self.nz(self.y)
        elif mn == "TSX":
            self.x = self.nz(self.sp)
        elif mn == "TXS":
            self.sp = self.x
        elif mn == "INX":
            self.x = self.nz(self.x + 1)
        elif mn == "DEX":
            self.x = self.nz(self.x - 1)
        elif mn == "INY":
            self.y = self.nz(self.y + 1)
        elif mn == "DEY":
            self.y = self.nz(self.y - 1)
        elif mn in ("CLC", "SEC", "CLI", "SEI", "CLV", "CLD", "SED"):
            f = {"C": C, "I": I, "V": V, "D": D}[mn[2]]
            self.flag(f, mn[0] == "S")
        elif mn == "NOP":
            pass
        elif mn == "BRK":
            raise Halt("BRK at %04X" % pc0)
        else:
            raise Halt("unimplemented %s" % mn)
        self.cycles += cyc


class MathBox:
    """Atari's Math Box as MAME models it (src/mame/atari/mathbox.cpp, Eric Smith): the registers
    written at $6080-$609F, the result at $6060 (low) / $6070 (high), status always 'done'."""

    def __init__(self):
        self.reg = [0] * 16
        self.result = 0

    @staticmethod
    def s16(v):
        v &= 0xFFFF
        return v - 0x10000 if v & 0x8000 else v

    def go(self, offset, data):
        r = self.reg
        s = self.s16

        def lo(i):
            r[i] = s((r[i] & 0xFF00) | data)
            self.result = r[i]

        def hi(i):
            r[i] = s((r[i] & 0x00FF) | data << 8)
            self.result = r[i]

        simple = {0x00: (lo, 0), 0x01: (hi, 0), 0x02: (lo, 1), 0x03: (hi, 1), 0x04: (lo, 2),
                  0x05: (hi, 2), 0x06: (lo, 3), 0x07: (hi, 3), 0x08: (lo, 4), 0x09: (hi, 4),
                  0x0A: (lo, 5), 0x15: (lo, 7), 0x16: (hi, 7), 0x1A: (lo, 8), 0x1B: (hi, 8),
                  0x0D: (lo, 10), 0x0E: (hi, 10), 0x0F: (lo, 11), 0x10: (hi, 11)}
        if offset in simple:
            f, i = simple[offset]
            f(i)
            return
        if offset == 0x0C:
            r[6] = data
            self.result = data
            return
        if offset == 0x17:
            self.result = r[7]
            return
        if offset == 0x19:
            self.result = r[8]
            return
        if offset == 0x18:
            self.result = r[9]
            return
        if offset == 0x14:
            self.divide(r[10], r[11])
            return
        if offset == 0x13:
            self.divide(r[9], r[8])
            return
        raise NotImplementedError("Math Box command %02X (not used by the game's live code)" % offset)

    def divide(self, c, q):
        """MAME's step_0bf: REG7 is the divisor, (REGc, mb_q) the dividend, REG6 the step count."""
        r = self.reg
        s = self.s16
        r[12] = s(c)
        mb_q = s(q)
        r[14] = s(r[7] ^ mb_q)
        r[13] = mb_q
        if mb_q >= 0:
            mb_q = r[12]
        else:
            r[13] = s(-mb_q - 1)
            mb_q = s(-r[12] - 1)
            if mb_q < 0 and s(mb_q + 1) < 0:
                r[13] = s(r[13] + 1)
            mb_q = s(mb_q + 1)
        r[12] = r[7] if r[7] >= 0 else s(-r[7])
        r[15] = r[6]
        while True:
            r[13] = s(r[13] - r[12])
            msb = 1 if mb_q & 0x8000 else 0
            mb_q = s(mb_q << 1)
            if r[13] >= 0:
                mb_q = s(mb_q + 1)
            else:
                r[13] = s(r[13] + r[12])
            r[13] = s(r[13] << 1)
            r[13] = s(r[13] + msb)
            r[15] = s(r[15] - 1)
            if r[15] < 0:
                break
        self.result = mb_q if r[14] >= 0 else s(-mb_q)

    def attach(self, cpu, base=0x6000):
        cpu.map_io(base + 0x80, base + 0x9F, None, lambda a, v: self.go(a - base - 0x80, v))
        cpu.map_io(base + 0x40, base + 0x40, lambda a: 0x00, None)
        cpu.map_io(base + 0x60, base + 0x60, lambda a: self.result & 0xFF, None)
        cpu.map_io(base + 0x70, base + 0x70, lambda a: (self.result >> 8) & 0xFF, None)


ROMS = [("136002-133.d1", 0x9000), ("136002-134.f1", 0xA000), ("136002-235.j1", 0xB000),
        ("136002-136.lm1", 0xC000), ("136002-237.p1", 0xD000), ("136002-237.p1", 0xF000),
        ("136002-138.np3", 0x3000)]     # vector ROM, which the CPU reads too (VGMSGA, pictures)


def load_rev3(cpu, romdir=None):
    """Rev 3 program ROM and vector ROM, as MAME's ROM_START(tempest) and memory map place them."""
    import os
    romdir = romdir or os.path.join(os.path.dirname(__file__), "..", "tempest_orig", "notebooks",
                                    "roms", "tempest")
    for name, addr in ROMS:
        with open(os.path.join(romdir, name), "rb") as f:
            cpu.load(addr, f.read())
    return cpu
