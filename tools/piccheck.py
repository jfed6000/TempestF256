#!/usr/bin/env python3
"""piccheck.py - static position-independence check over lwasm listings.

Usage: python3 tools/piccheck.py src/tempest.list [more.list ...]

Joust's tools/piccheck.py (its data-area convention item 9 and PIC rules), with Tempest's second
approved exception.  Reported, per listing line:

  EXT   an extended-mode operand (absolute address), except the two approved exceptions: the
        VS1053 registers $FF50-$FF57 and the integer coprocessor $FEE0-$FEFF (Tempest's D8)
  EXTI  extended indirect ([addr] without a register)
  IMM   an immediate whose value is a code or data address
        (#label; #label-label is a constant and passes)
  IDX   a code label as the offset from X, Y, U or S (a module address
        used as data), or a data label as a PC-relative offset
  FDB   an address stored in the module (fdb label; fdb label-Tbl passes)

Symbols are classed from the listing itself:
  data  - rmb labels after the mod line, outside .d files (data area offsets)
  code  - labels on lines that emit module bytes, local labels, equ *
  const - everything else (equ, set, rmb before mod: structure offsets)
An equ inherits the class of the labels its expression adds.

A line whose comment holds "pic:ok" is not reported (a reviewed exception).
Exit status 1 when anything is reported.
"""

import re
import sys

LINE = re.compile(r'^(?P<addr>[0-9A-F]{4}|    )(?P<dot>[. ])(?P<bytes>[0-9A-F]*)\s*'
                  r'\(\s*(?P<file>[^)]*)\):(?P<num>\d+) (?P<src>.*)$')
SYM = re.compile(r'[A-Za-z_.@][A-Za-z0-9_.@$]*')
DIRECTIVES = {
    'FCB', 'FDB', 'FQB', 'FCC', 'FCS', 'FCN', 'RMB', 'RMD', 'RMQ', 'ZMB', 'ZMD', 'BSZ',
    'FILL', 'MOD', 'EMOD', 'ORG', 'EQU', 'SET', 'USE', 'NAM', 'TTL', 'SETDP', 'ALIGN',
    'IFP1', 'IFP2', 'IFEQ', 'IFNE', 'IFGT', 'IFGE', 'IFLT', 'IFLE', 'IFDEF', 'IFNDEF',
    'ELSE', 'ENDC', 'MACRO', 'ENDM', 'ERROR', 'WARNING', 'PRAGMA', 'INCLUDEBIN', 'END',
    'OS9', 'SPC', 'PAG', 'OPT', 'INCLUDE', 'EXPORT', 'EXTERN', 'IMPORT', 'SECTION',
    'ENDSECTION', 'STRUCT', 'ENDSTRUCT', 'OPTS', 'NOOPT',
}
BRANCHES = re.compile(r'^L?B(RA|RN|HI|LS|CC|HS|CS|LO|NE|EQ|VC|VS|PL|MI|GE|LT|GT|LE|SR)$')
NO_OPERAND_ADDR = {'TFR', 'EXG', 'PSHS', 'PULS', 'PSHU', 'PULU', 'TFM', 'ADDR', 'ADCR',
                   'SUBR', 'SBCR', 'ANDR', 'ORR', 'EORR', 'CMPR', 'BITMD', 'LDMD'}
PCREGS = {'PCR', 'PC'}
IND_REGS = {'X', 'Y', 'U', 'S'}
VS1053 = range(0xFF50, 0xFF58)
COPROC = range(0xFEE0, 0xFF00)         # D8 (docs/port-plan.md): masked at every use
DATA_ADDR = {}   # data label -> its offset in the data area (from rmb lines)


def parse(path):
    """listing lines as dicts: addr, dot, bytes, file, label, op, operand, comment."""
    out = []
    with open(path, errors='replace') as f:
        for raw in f:
            m = LINE.match(raw.rstrip('\n'))
            if not m:
                continue
            src = m.group('src')
            # the listing puts 8 spaces before the source text
            src = src[8:] if src.startswith('        ') else src.lstrip(' ')
            rec = dict(addr=m.group('addr').strip(), dot=m.group('dot') == '.',
                       bytes=m.group('bytes'), file=m.group('file').strip(),
                       num=int(m.group('num')), src=src, label='', op='', operand='', comment='')
            s = src
            if not s or s[0] in '*;':
                rec['comment'] = s
                out.append(rec)
                continue
            parts = split_fields(s)
            rec.update(parts)
            out.append(rec)
    return out


def split_fields(s):
    label = ''
    if s[0] not in ' \t':
        m = re.match(r'(\S+)', s)
        label = m.group(1).rstrip(':')
        s = s[m.end():]
    s = s.lstrip()
    m = re.match(r'(\S*)', s)
    op = m.group(1)
    s = s[m.end():].lstrip()
    operand, comment = take_operand(op, s)
    return dict(label=label, op=op.upper(), operand=operand, comment=comment)


def take_operand(op, s):
    """the operand up to the first blank outside quotes and fcc delimiters."""
    u = op.upper()
    if u in ('FCC', 'FCS', 'FCN') and s:
        d = s[0]
        end = s.find(d, 1)
        if end < 0:
            return s, ''
        return s[:end + 1], s[end + 1:]
    i, q = 0, False
    while i < len(s):
        c = s[i]
        if c == "'" and not q:
            i += 2
            continue
        if c in ' \t':
            break
        i += 1
    return s[:i], s[i:]


class Expr:
    """sign-weighted label counts of an expression: code, data, and 'complex'."""

    def __init__(self, classes, here_class):
        self.classes = classes
        self.here = here_class

    def weigh(self, text):
        toks = re.findall(r"\$[0-9A-Fa-f]+|%[01]+|\d+|'.|[A-Za-z_.@][A-Za-z0-9_.@$]*|[-+*/&|^()<>!~]", text)
        w = {'code': 0, 'data': 0}
        complex_ = False
        sign = 1
        stack = []
        prev_operand = False
        lbl_in_product = False
        for t in toks:
            if t == '(':
                stack.append(sign)
                prev_operand = False
                continue
            if t == ')':
                if stack:
                    stack.pop()
                prev_operand = True
                continue
            if t in '+-':
                if not prev_operand:           # unary
                    if t == '-':
                        sign = -sign
                    continue
                outer = stack[-1] if stack else 1
                sign = outer * (1 if t == '+' else -1)
                prev_operand = False
                continue
            if t == '*' and not prev_operand:
                cls = self.here
                if cls in w:
                    w[cls] += sign
                prev_operand = True
                continue
            if t in '*/&|^<>!~':
                if lbl_in_product:
                    complex_ = True
                prev_operand = False
                lbl_in_product = True if lbl_in_product else False
                continue
            prev_operand = True
            if re.match(r"[A-Za-z_.@]", t):
                cls = self.classes.get(t.upper(), 'const')
                if cls == '.':
                    cls = self.here
                if cls in w:
                    w[cls] += sign
                    lbl_in_product = True
            elif t == '.':
                pass
        # a label next to * or / is not a plain address
        if re.search(r"[*/&|^]", re.sub(r"^\*|[(+\-]\*", '', text)) and (w['code'] or w['data']):
            complex_ = True
        return w, complex_


def classify(recs):
    classes = {}
    seen_mod = False
    here = 'const'
    pending = []
    for r in recs:
        if r['op'] == 'MOD':
            seen_mod = True
        if r['addr'] and r['op'] not in ('EQU', 'SET'):
            here = 'data' if r['dot'] else 'code'
        if not r['label']:
            continue
        name = r['label'].upper()
        in_defs = r['file'].endswith('.d') or r['file'] == 'defsfile'
        if r['op'] in ('EQU', 'SET'):
            pending.append((name, r['operand'], here if seen_mod and not in_defs else 'const'))
            continue
        if r['op'] in ('RMB', 'RMD', 'RMQ'):
            classes[name] = 'data' if seen_mod and not in_defs else 'const'
            if seen_mod and not in_defs and r['addr']:
                DATA_ADDR[name] = int(r['addr'], 16)
        elif r['op'] == 'MACRO':
            continue
        elif seen_mod and not in_defs and (r['bytes'] or not r['dot']):
            classes[name] = 'code'
        elif seen_mod and not in_defs and r['dot']:
            classes[name] = 'data'
        else:
            classes.setdefault(name, 'const')
    for _ in range(3):                       # equ chains
        for name, operand, here_cls in pending:
            e = Expr(classes, here_cls)
            if operand.strip() in ('*', '.'):
                classes[name] = here_cls
                continue
            w, cx = e.weigh(operand)
            if w['code'] > 0 and not cx:
                classes[name] = 'code'
            elif w['data'] > 0 and not cx:
                classes[name] = 'data'
            else:
                classes[name] = 'const'
    return classes


def is_extended(b):
    if len(b) < 2:
        return None
    op = int(b[0:2], 16)
    if op in (0x10, 0x11) and len(b) >= 4:
        op2 = int(b[2:4], 16)
        if op2 >> 4 in (0xB, 0xF):
            return int(b[4:8], 16) if len(b) >= 8 else -1
        return None
    if op >> 4 in (0x7, 0xB, 0xF):
        if op in (0x71, 0x72, 0x75, 0x7B):   # 6309 OIM/AIM/EIM/TIM: op, imm, addr
            return int(b[4:8], 16) if len(b) >= 8 else -1
        return int(b[2:6], 16) if len(b) >= 6 else -1
    return None


def is_direct(b):
    if len(b) < 4:
        return False
    op = int(b[0:2], 16)
    if op in (0x10, 0x11):
        return len(b) >= 6 and int(b[2:4], 16) >> 4 in (0x9, 0xD)
    return op >> 4 in (0x0, 0x9, 0xD)


def check(path):
    recs = parse(path)
    classes = classify(recs)
    problems = []
    seen_mod = False
    for r in recs:
        if r['op'] == 'MOD':
            seen_mod = True
            continue
        if not seen_mod or not r['op'] or 'pic:ok' in r['comment'].lower():
            continue
        if r['file'].endswith('.d'):
            continue
        here = 'data' if r['dot'] else 'code'
        e = Expr(classes, here)
        op, opd = r['op'], r['operand']
        where = f"{r['file']}:{r['num']}"
        text = f"{r['label']} {r['op'].lower()} {opd}".strip()
        if op in ('FDB', 'FQB'):
            for item in split_list(opd):
                w, cx = e.weigh(item)
                if w['code'] or w['data']:
                    problems.append(('FDB', where, text))
                    break
            continue
        if op in DIRECTIVES or not r['bytes']:
            continue
        if BRANCHES.match(op) or op in NO_OPERAND_ADDR:
            continue
        # extended (no immediate opcode has high nibble 7, B or F)
        ext = is_extended(r['bytes'])
        if ext is not None:
            if ext not in VS1053 and ext not in COPROC:
                problems.append(('EXT', where, text))
            continue
        # direct: page 0 of the data area; a code label there is an absolute address
        if is_direct(r['bytes']):
            w, cx = e.weigh(opd.split(',')[-1].lstrip('<'))
            if w['code']:
                problems.append(('DIR', where, text))
            else:
                # lwasm truncates a far data label to its low byte without a word:
                # <TRCPATH at $1A6A assembled as $6A and wrote the lava level
                for sym in SYM.findall(opd):
                    a = DATA_ADDR.get(sym.upper())
                    if a is not None and a >= 0x100:
                        problems.append(('DIR0', where, text + '   (far: $%04X)' % a))
                        break
            continue
        if opd.startswith('#'):
            w, cx = e.weigh(opd[1:])
            if w['code'] or w['data']:
                problems.append(('IMM', where, text))
            continue
        body = opd
        indirect = body.startswith('[') and body.endswith(']')
        if indirect:
            body = body[1:-1]
        if ',' not in body:
            if indirect:
                problems.append(('EXTI', where, text))
            continue
        off, reg = body.rsplit(',', 1)
        reg = reg.strip().upper().strip('+-')
        off = off.lstrip('<>')
        if not off or re.fullmatch(r'[ABDEFW]', off.upper()):
            continue
        w, cx = e.weigh(off)
        if reg in PCREGS:
            if w['data']:
                problems.append(('IDX', where, text))
        elif w['code']:
            problems.append(('IDX', where, text))
    return problems


def split_list(s):
    out, depth, cur = [], 0, ''
    for c in s:
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
        if c == ',' and depth == 0:
            out.append(cur)
            cur = ''
        else:
            cur += c
    out.append(cur)
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    bad = 0
    for path in sys.argv[1:]:
        probs = check(path)
        for kind, where, text in probs:
            print(f"{path}: {kind:4} {where}: {text}")
        bad += len(probs)
        print(f"{path}: {len(probs)} reported")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
