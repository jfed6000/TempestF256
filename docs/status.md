# Tempest for NitrOS-9 Level 2 on Wildbits F256: status

**2026-09-23.** Stage 0 complete; the D6 pilot, the translator and the D6 hand work done, reviewed
and committed (`07e63de`): the game, hand-finished in `src/`, runs all 2,417 game frames recorded
from MAME byte-exact against Atari's ROM. **Stage 2's interpreter is done on the host, for review**
(section "Stage 2 on the host" below): `src/avg.a` walks the display list into `SS.BmLine` records
and a glyph text list, byte-exact against its specification (`avgview.py`'s `PortAVG`) on every
captured frame and 20,000 random lists. It costs **17.4 ms a play frame (median) at 8 MHz**, too much
beside the game and the driver: the budget is the main point for review. Nothing has run on
hardware.

## Decisions so far

- **D1 revision:** Rev 3 ("2A(alt)").
- **D4 controls (user):** no spinner. Keyboard (← → constant rate, Shift fire, `z` superzapper),
  mouse (proportional, via `SS.MsDelta`), joystick (constant rate, buttons 0/1).
- **D8 (user):** the math coprocessor at `$FEE0` is approved.
- **`SS.MsDelta` $D0 (user):** layout approved (plan 6.1). Not coded.
- **D6 register model (user, 2026-09-22): model B** — 6502 X and Y in the zero-page
  pseudo-registers `<RX`/`<RY` (pointers `RXP`/`RYP` at $B8-$BB), B always scratch (section
  "D6 pilot"). **The `pilot/pilot.d` conventions approved too (user, same day):** U/DP = the data
  area, the arcade's 2K page for page; `RXP`/`RYP` at $B8-$BB; port variables from $800 (`POKIMG`);
  `(zp),Y` pointers big-endian logical addresses; the coprocessor divide masked.
- **D3 text (user):** glyph masks on a third, front bitmap, redrawn only when the text changes;
  two sizes rendered on the host from the vector ROM (plan D3).
- **D6 hand work (user, 2026-09-23, "proceed"):** the recommendations stand: ZATC4V neutralised,
  CASCAL's exact overflow path (`MBDV24`) kept, the data area to $B9D; committed `07e63de`.
- **The rest (D2, D5, D6, D7, D9, D10):** the plan's recommendations stand unless the user says
  otherwise. D9 loses its triple-buffer option (all three bitmaps are used).

## Hardware findings

**The line engine drops pixels** (K2, the DMA-fixed core and a newer one, 2026-09-22). Clear-then-fan
shows gaps that move every run; a second pass fills most. DMA fills and CPU writes are clean. With the
FPGA developer; **the port assumes a fix** (user). Full account: `docs/port-tempest.md` §4.2. Re-run
bmtest `C`+`L` and `C`+`F` on each new core.

## Stage 0 results (host, no hardware)

**Tools.** `tools/avgcap.lua` (stock MAME 0.276, Lua `-autoboot_script`, MAME unmodified) dumps vector
ROM once and vector RAM + colour RAM every frame. `tools/avgview.py` is a literal port of MAME's Tempest
AVG (state PROM `136002-125.d7` plus handlers) with the port's 320×240 mapping, Liang-Barsky clipping,
the `colour×16+intensity` CLUT and a Bresenham renderer.

**Checked against MAME:** attract frame 4200 (the demo well) rendered by `avgview` matches MAME's own
snapshot of the same frame — geometry, text, colours and orientation. The first mapping had the rows
flipped (text upside down); corrected to displayed row = MAME x, column = MAME y. The picture fills 240
rows, ~236 columns, centred. **Text is small at this size**: a character is about 5-6 pixels tall.

**The load, 90 s of attract mode** (5,401 frames; demo gameplay and the text screens), in line records
after clipping and pixels the engine would enqueue:

| Frames | Records: median / max | of which characters (median) | Pixels: median / max |
|---|---|---|---|
| With a well (play-like), 458 sampled | 473 / 696 | 226 | 3,106 / 13,809 |
| Text screens, 622 sampled | 509 / 696 | 490 | 2,408 / 6,297 |
| All 5,401 | 502 / 696 | | 2,460 / 14,781 |

Record lengths (attract average per frame): 1 px 67, 2 px 42, 3 px 59, 4 px 86, 5 px 49, 6 px 101,
7-19 px ~36, 20 px and over 16. About 45 records a frame duplicate another in the same frame.
Characters are vector-ROM subroutines at `$3000`-`$31E3` (`VGMSGA` follows at `$31E4` in the link map).

**What it means:**

- **Pixels are not the constraint.** Even the worst frame is ~15K pixels, and the FIFO pacing,
  the `WAIT` flag and the exact-room change (plan 6.2 (1), (2)) look unnecessary. Stage 1 confirms.
- **Records are.** ~500-700 a game frame at the estimated 25-30 µs each is **12-20 ms of a 36.6 ms
  frame**, and more than 255 a call. **The per-record cost (`tline` key `S`) is now the number that
  decides the design.** Plan 6.2 (3) (more than 255 records a call) is justified by these numbers.
- **D3 (text) is reopened.** Characters are about half the records in play and nearly all on text
  screens. Drawing a character as a glyph (the interpreter recognising a `JSRL` into `$3000`-`$31E3`
  and plotting a mask, rendered on the host from the same vector ROM so it looks identical) would
  remove most of them. Decide after `tline S`.

**Text uses exactly two sizes.** Every message in `ALLANG`'s table (`MESS` lines 64-93) has scale 0
(big: HIGH SCORES, PLAYER, AVOID SPIKES) or 1 (everything else); scores and the rating screen set scale
1 (`ALSCO2` 50, 447, 1078). The one variable-scale site, `SCARNG` (`ALSCO2` 1339), zooms the **logo
picture**, not characters. The attract capture agrees: character draws at binary scale 1 (97 a frame)
and 0 (3.5), 31 distinct characters. So a host-rendered font needs **two sizes of about 40 glyphs**,
drawn as masks in any colour. The VICKY text font and tile sets are fixed at 8×8 and cannot match
either size; that is not a limit on masks, which are our own pixels.

**The D3 font (`tools/glyphs.py`, 2026-09-22).** The 41-entry `VGMSGA` table of character `JSRL`s is
at `$31E4` in the Rev 3 ROM too (checked by decoding it): blank, 0-9 (0 shares O's routine), A-Z, a
second blank, DASH, HALF, COPYR. Each is run through `avgview`'s AVG at both scales: normal glyphs are
up to 5×6 pixels, big up to 8×11. Every character drawn in the attract capture is in the set (27,286
draws). Characters use **their own stroke intensities** (12; 10 in a few), not the STAT intensity, and
HALF resets the scale on exit and moves the beam off the baseline; both recorded per glyph.
**Glyphs versus line-drawn text:** 27% of pixels differ, but a line-drawn character takes ~2 shapes
(up to 5) depending on where it falls on the pixel grid, and even the best single shape per character
differs by 21.5%. Side by side on the high-score and demo screens the glyph text is the more legible
(line-drawn "COIN" smears into "CCCIN"). One shape per character, rendered at pixel phase 0.

**A played game (2026-09-22).** `avgcap.lua` gained three optional modes: `AVGCAP_PLAY=1` plays
(coin and start through MAME's input fields, fire tapped, superzapper every 1,500 frames, the knob by
writing `TBHD` = `$50`, found from `MOVCUR`'s clamp at `$975B` in the Rev 3 ROM; seeded, so a run
repeats), `AVGCAP_TIMING` logs `MAINLN`'s work per game frame (`FRTIMR` = `$53`, wait loop at `$C7A7`),
and `AVGCAP_POKEY` logs every POKEY write. 300 s of play, snapshots confirming real games on the circle
and cross wells:

| Played frames (18,001; sampled every 10th past frame 500 for the split) | median | 95% | max |
|---|---:|---:|---:|
| Line records, all | 288 | 323 | 413 |
| **Line records, characters excluded (what the port sends, D3)** | **148** | **265** | **305** |
| Characters (glyphs) | 17 | 94 | 94 |
| Pixels | 1,972 | 2,702 | 3,583 |

Play is lighter than attract's text screens. With glyphs, **one or two `SS.BmLine` calls a frame**:
at the estimated 25-30 µs a record, ~4.4 ms median and ~9 ms worst of a 36.6 ms game frame.

**The 6502's work per game frame** (8,128 game frames = **27.1 Hz**, as predicted): median **21.4 ms**
(58% of the 36.6 ms frame, ~32,000 cycles at 1.512 MHz), 90% 31.6 ms, 99% 41.3 ms, max 44.9 ms.
**The arcade overruns too**: 6% of frames took 10-12 IRQs instead of 9. So the budget for the
translated game logic plus the display-list build is ~32K 6502 cycles typical and ~68K worst, which
must fit beside the interpreter and the driver calls in 36.6 ms at 8 MHz. Arithmetic, once the D6
pilot gives the expansion ratio.

**POKEY writes:** 825 a second. `POTGO`/`POTGO2` (`$0B`, `$1B`) are 246 a second each — the IRQ kicking
the pot scan for the spinner and switches, not sound. The sound writes are `AUDF`/`AUDC` on both
chips, POKEY 1 channel 3 (`$04`/`$05`) far the busiest, and `AUDCTL`/`SKCTL` only at start-up
(12 and 24 writes). So the register image of plan D5 is 8 × (`AUDF`, `AUDC`) and nothing else changes
in play.

**`tools/m65parse.py` (2026-09-22): the MAC65 reader.** Classifies every line of the 11 game files
(labels, assignments, instructions with their addressing mode, HLL65 structures, directives, macro
calls, macro bodies) with **no unrecognised statements** and **HLL65 nesting balanced in every
file**. It evaluates `.IF`/`.IFF`/`.ENDC` MACRO-11-style (left to right, no precedence) and treats
`.REPT 0` blocks — Atari's block comments — as dead: ALDIS2's 154 dead lines are the `.IF NE,0`
multiply/window code, ALVROM's 168 the space-game remnants. It follows macro-defining macros:
HLL65's `DEFIF`/`DEFEND`, and **ALWELG's enemy behaviour, which is a small bytecode** — `CAMAC`,
`CAMA2I`, `CAMA2F` (`ALWELG.MAC:1579`) each make a jump-table entry (`TABJSR`) and a macro emitting
the opcode byte (`VSMOVE`, `VEXIT`, `VSETPC`, ...), so the cam tables translate as data plus one
dispatcher.

**Addressing modes, 5,548 live instructions** — the input to D6's register model:

| Mode | Count | Share |
|---|---:|---:|
| absolute / zero page | 2,377 | 42.8% |
| immediate | 1,248 | 22.5% |
| implied / accumulator | 1,008 | 18.2% |
| `abs,X` / `zp,X` | 483 (+22 forced) | 8.7% |
| `abs,Y` | 229 (+6 forced) | 4.1% |
| `(zp),Y` | 112 | 2.0% |
| relative (explicit branches; HLL65 adds more) | 57 | 1.0% |

Top mnemonics: LDA 1,395, STA 992, JSR 392, LDX 267, LDY 242, CMP 199, RTS 193, AND 187, ADC 155.
Note for the translator: HLL65's `ELSE` is `CLV` plus an always-taken `BVC`, so the V flag does not
survive an `ELSE`.

**Stage 0 is complete.**

## D6 pilot (2026-09-22, host only) — for review

Three routines translated by hand from 6502 to position-independent 6809 under both register models,
exactly as the translator would emit them, then checked against Atari's own code in the Rev 3 ROM.
**No translator and no game code has been written; that waits for the review.**

### What was built

| File | What it is |
|---|---|
| `tools/cpu6502.py` | NMOS 6502, cycle-counted (page-cross and branch penalties), and **MAME's Math Box** ported from `mathbox.cpp`; loads the Rev 3 program ROM as MAME's `ROM_START(tempest)` does. The oracle |
| `tools/cpu6809.py` | 6809, the whole documented instruction set, cycle-counted with the indexed extras |
| `tools/romfind.py` | Finds a source routine in the Rev 3 ROM from its opcode skeleton (m65parse lines, HLL65 expanded as `HLL65.MAC` assembles it) and returns every label's address. `ALEXEC.MAP` is linked from Rev 1 names, so this is how Rev 3 addresses are got |
| `tools/m65parse.py` | Now tracks the `.ASECT` location counter, so RAM labels have addresses (`FRTIMR` $53 and `TBHD` $50 agree with what stage 0 found in the ROM). The mode census is unchanged |
| `tools/d6pilot.py` | The differential test and the measurements; also writes `pilot/arcade.d` (symbols from the source) and `pilot/sound.bin` (the sound table, from the ROM) |
| `pilot/` | `pilot.d` (conventions), `worscr.a` (both models), `modsnd_a.a`, `modsnd_b.a`, `dspnym_a.a`, `dspnym_b.a` |

Rev 3 addresses found: `WORSCR` $C098, `MODSND` $CD0A, `FSNDON` $CCC7, `DSPNYM` $B498, `VGSTAT` $DF4C,
`VGYAB1` $C765 (and `MOVCUR` $9749, consistent with stage 0's clamp at $975B).

**The routines.** `WORSCR` (`ALDIS2.MAC:2208`, arithmetic and the Math Box); `MODSND`
(`ALSOUN.MAC:270`, table-driven, X and Y both live); and `DSPNYM` (`ALDIS2.MAC:457`, the nymphs,
a builder with fourteen `STA NY,VGLIST` a nymph) **together with everything it calls**: `VGSTAT`,
`VGADD2`/`VGADD3`, `VGADD`, `VGSCA1`/`VGSCAL` (`ALVGUT`) and `VGYAB1`/`VGYABS` (`ALDIS2:3240`).

### The test

`d6pilot.py` gives Atari's routine (run from the ROM on the host 6502) and the translation (on the
host 6809) the same inputs, then compares **all 2K of arcade RAM** (less the 6502's stack top
$1D0-$1FF and the four pseudo-register bytes), **all 4K of vector RAM**, the **POKEY register image**,
and the 6502's **A, X and Y**. Each 6809 case runs **twice, under two layouts** — code at $8000 and at
$A1E7, the data area at $1000 and $5300, the vector-RAM window at $4000 and $2000 — and must give the
same answer and the same cycle count both times, which is the position-independence check.

- **2,000 random cases per build**, with the edges forced: for `WORSCR` Δy = 0, a point behind the eye,
  the saturation limits, and PZ = EZ / PX = EX; for `MODSND` every path (restart, kill, the 9-bit
  table half, odd and even channels, `SINDEX`); for `DSPNYM` busy and empty nymph tables, the security
  byte `QT1`, and a list pointer anywhere in vector RAM over a random background (stray writes show).
- **`MODSND` also plays the game's own sounds for 5,000 IRQs**: the ROM's `FSNDON` starts one of the
  13 sounds at random, its changes are copied to the 6809, and both interpreters step in lockstep.
- **Every executed 6809 instruction's cycle count is checked against lwasm's `--6809` listing** (828
  instruction checks over the seven builds; none disagree).
- **The test catches bugs:** three deliberate one-line mutations (a `blo` made `bls`, a POKEY image
  offset, a list offset) were each caught, the subtlest at case 244 before the equality cases were
  added.

**Result: every case of every build is byte-exact against the ROM, in both layouts.** One bug was
found on the way, in the host 6809 itself (`LEAS`/`LEAU` swapped), not in a translation.

### The register models, as built

Common to both:

- **U = the data area's base and DP = its page, for the whole game.** The arcade's 2K sits in it page
  for page: a zero-page variable is `<name`, anything else `name,U` (16-bit offset, 4 bytes, 8 cycles
  against the 6502's 3 and 4). Port variables go past $800 (`POKIMG`, the POKEY image, is at $800).
- **The pseudo-registers need nothing moved.** Zero page is not quite full: **$4B and $B8-$BC are
  never allocated** (`ALCOMN.MAC:473` "UNUSED", and the gap between `SECUVG` and the EAROM's $BD).
  `RXP` = $B8/$B9 and `RYP` = $BA/$BB are pointers: the high byte is the data area's page, set once at
  start-up, the low byte the 6502 register, so **`ldx <RXP` is data base + X in one load**. $4B and
  $BC stay spare. (The only wholesale zero-page writer outside self-test is the anti-tamper
  `ZQVAVG`'s `INC X,0`, `ALWELG.MAC:3089`, which the port neutralises anyway.)
- **Block-local pointer caches** (the translator's one real analysis): 6809 Y holds data base + X from
  `ldy <RXP` until X changes; 6809 X holds a table or list pointer (`SOUND`+Y, `VGLIST`+Y) until Y or
  the pointer changes, and **later `INY`s fold into the offset** (`sta 5,x`), so a run of
  `STA NY,VGLIST / INY` costs 2 bytes and 5 cycles a store plus the `INY`'s own `inc <RY`.
- **`VGLIST` is big-endian on the port** (a logical address; `<VGLIST` high): every 6502 byte access
  to it is swapped, and `ldx <VGLIST` is the pointer. The list's contents stay little-endian, since the
  interpreter is ours. Any other pointer used through `(zp),Y` gets the same treatment.

| 6502 | Model A: X in B, Y in `<RY` | Model B: X in `<RX`, Y in `<RY` |
|---|---|---|
| `LDX #n` (2 B, 2 cyc) | `ldb #n` 2 B, 2 | `ldb #n / stb <RX` 4 B, 6 |
| `INX`, `DEX` (1, 2) | `incb` 1, 2 | `inc <RX` 2, 6 |
| `TAX` / `TXA` (1, 2) | `tfr a,b` / `tfr b,a` 2, 6 | `sta <RX` / `lda <RX` 2, 4 |
| `CPX #n` (2, 2) | `cmpb #n` 2, 2 | `ldb <RX / cmpb #n` 4, 6 |
| `INY`, `DEY` (1, 2) | `inc <RY` 2, 6 | same |
| `LDA tab,X`, tab in RAM (3, 4) | cache: `stb <RX / ldy <RXP` 5, 10; then `lda tab,y` 4, 8 | cache: `ldy <RXP` 3, 6; then the same |
| `LDA tab,Y`, tab in ROM (3, 4) | pointer: `leax tab,pcr / pshs b / ldb <RY / abx / puls b` 11, 28 when X is live; then `lda k,x` 2, 5 | `leax tab,pcr / ldb <RY / abx` 7, 16; then the same |
| `STA (zp),Y` (2, 6) | pointer: `pshs b / ldx <zp / ldb <RY / abx / puls b` 9, 24 when X is live; then `sta k,x` 2, 5 | `ldx <zp / ldb <RY / abx` 5, 12; then the same |
| `JSR` (3, 6), `RTS` (1, 6) | `lbsr` 3, 9 (`bsr` 2, 7); `rts` 1, 5 | same |
| HLL65 `ELSE` = `CLV / BVC` (3, 5) | `bra` 2, 3 | same |

Model A has to know when B is free: it needs **global liveness of the 6502's X** (which routines read
X on entry) to avoid a `pshs b` at every pointer build, and a wrong answer there silently corrupts X.
Model B's B is always scratch, so the translation is correct without any liveness at all.

### Numbers (2,000 cases each; cycles are per call, the caller's `JSR` excluded)

| Routine | Model | 6502 bytes | 6809 bytes | Size ratio | 6502 cycles min / median / max | 6809 cycles min / median / max | Cycle ratio (means) | Wall time at 8 MHz vs 1.512 MHz |
|---|---|---:|---:|---:|---|---|---:|---:|
| `WORSCR` | A | 214 | 188 | 0.88 | 192 / 195 / 220 | 224 / 293 / 315 | 1.45 | 3.7× faster |
| `WORSCR` | B | 214 | 190 | 0.89 | 192 / 195 / 220 | 228 / 297 / 319 | 1.47 | 3.6× |
| `WORSCR` | B, `SOFTDIV` | 214 | 213 | 1.00 | 192 / 195 / 220 | 228 / 2,105 / 2,253 | 9.45 | 0.6× |
| `MODSND` | A | 139 | 234 | 1.68 | 282 / 775 / 1,292 | 614 / 1,544 / 2,562 | 1.99 | 2.7× |
| `MODSND` | **B** | 139 | **219** | **1.58** | 282 / 775 / 1,292 | 634 / 1,514 / 2,426 | 1.95 | 2.7× |
| `DSPNYM` + callees | A | 304 | 382 | 1.26 | 1,678 / 5,353 / 6,046 | 3,034 / 7,838 / 9,085 | 1.50 | 3.5× |
| `DSPNYM` + callees | **B** | 304 | **372** | **1.22** | 1,678 / 5,353 / 6,046 | 2,982 / 7,786 / 9,033 | 1.49 | 3.6× |

Playing the game's sounds (5,000 IRQs), `MODSND` averages 406 6502 cycles and **853 (B) / 865 (A)**
6809 cycles: at the 246 Hz virtual IRQ that is 210K cycles a second, **2.6% of the CPU**. The
6502's `WORSCR` counts are a floor: MAME's Math Box reports "done" at once, the real one does not.
`MODSND`'s sizes leave out its 516-byte table on both sides.

**`WORSCR` shrinks** because its Math Box traffic (register writes and `BIT MSTAT` polls) becomes one
coprocessor divide, `DIVQ`: exact against MAME's Math Box for **every Δy from 1 to $7FFF**, which is
everything `WORSCR` can produce after its own clamp, and for Δy = 0 the Math Box returns $FFFF, which
`DIVQ` reproduces with an explicit test (the coprocessor's answer to a zero divisor is not defined
anywhere). The divide runs with interrupts masked (D8). The `SOFTDIV` build is the D8 fallback; it
passes, but this straightforward loop costs ~900 cycles a divide and would want work before use.

### Recommendation: **model B**

- **It is smaller and faster** in both mechanically translated routines (`MODSND` 219 against 234
  bytes, `DSPNYM` 372 against 382; fewer cycles in both), and **ties** on `WORSCR`, where the only
  difference is one store.
- **The margin is small (2-6%)**, and it could go the other way on X-heavy code: over the whole game
  model A saves on the 488 X-register instructions (`LDX` 267, `STX` 69, `DEX`/`INX` 73, `TAX`/`TXA` 56,
  `CPX` 23 — roughly 800 bytes) and pays on every pointer build made while X is live (the `pshs b`
  pairs) and on each X cache (`stb <RX` first) — several hundred bytes the other way. Size does not
  decide it.
- **What decides it is the translator.** B needs no register liveness to be correct; A does, and its
  failure mode is a silently wrong X. With "compare against the listing" gone, the simpler and more
  uniform translation is the one to trust.

### What it implies for the module

The game's translated code is about **13,460 bytes of 6502** (instructions and HLL65 branches counted
from the source with m65parse: `ALWELG` 5,316, `ALDIS2` 4,265, `ALSCO2` 2,242, `ALEXEC` 795, `ALSOUN`
299, `ALCOIN` 269, `ALVGUT` 211, `ALLANG` 60) plus **about 4,930 bytes of data** that copies across 1:1
(messages, the well and skill tables, the sound tables, the cam bytecode). `ALTES2`, `ALHAR2` and
`ALEARO` are not translated (dropped, rewritten into the frame loop, replaced by the settings file).

| Code ratio | Game code | + data | + vector ROM | Total | Left of 40,192 for the platform layer, the AVG interpreter, glyphs, sound output |
|---|---:|---:|---:|---:|---:|
| **1.33** (model B, the two mechanical routines together: 591 / 443) | 17,900 | 4,930 | 4,096 | **26,930** | **13,260** |
| 1.58 (the worst routine, `MODSND`) | 21,260 | 4,930 | 4,096 | 30,290 | 9,900 |

For scale, Joust's platform-type files (`platform`, `gfx`, `snd`, `dma`, `sys`, `text`, `reloc`,
`cmos`, `sched`) come to about 6,800 bytes of its module. **So the module fits, with vector ROM
inside it,** and the plan's fallback (vector ROM into window A's block, section 3) is not needed on
these numbers. The pilot over-weights the expensive idioms (`MODSND` is 16% `abs,Y` from a ROM table,
the game 2%; `DSPNYM` is dense in `STA NY`), so **1.33 is the planning figure and likely high**.

**Time.** The pilot's cycle ratios, 1.45-1.95 6809 cycles a 6502 cycle, are **0.27-0.37 of the 6502's
time** at 8 MHz. Applied to stage 0's measurement of the 6502's work a game frame (median 21.4 ms, 99%
41.3 ms), the translated game needs roughly **6-8 ms median and 11-15 ms at the 99th percentile** of
the 36.6 ms frame, before the interpreter and `SS.BmLine` (stage 0's estimate 4.4 ms median, 9 ms
worst, at an unmeasured per-record cost).

### Rules the translator inherits from the pilot

1. **Carry.** After a 6809 subtract or compare, C means *borrow*, the 6502's opposite. Branches map
   (`IFCS` after `CMP` → `blo` to the else), and `SBC` chains stay consistent because both CPUs feed
   their own convention forward. **Any other consumer of a compare's carry** (a rotate, an `ADC`) is
   inverted and must be flagged: `DSPNYM`'s `CMP I,50 ... ROL/ROL/ROL/AND I,3` is one, harmless only
   because the `AND` drops the bit.
2. **Flags the 6502 leaves alone.** 6809 `STA`, `LDA`, `CLR`, `COMA` all set flags; `PULS` sets none
   where `PLA` sets N and Z. The translator needs flag liveness to use `CLR`/`CLRA`/`COMA` (they clear
   or set C) and to add a `TSTA` after a `PULS A` whose flags are read. None were read in the pilot.
3. **`SEC; SBC` → `suba`, `CLC; ADC` → `adda`**; a lone `SEC; ADC` (`VGADD`) stays `orcc #1 / adca`.
4. **HLL65 `ELSE` → `bra`**, one byte shorter; V does not survive it on either CPU.
5. **zp,X wraps within page 0 on the 6502 and not on the 6809.** Nothing in the pilot wraps; the
   translator must check each zp,X table's bound.
6. **`JSR` and `JMP` between files are `lbsr`/`lbra`**; routine order is kept, so fall-throughs
   (`VGADD3` into `VGADD`) stay fall-throughs.

### Unchecked, and what would check it

- **The coprocessor's divide latency.** The divider is a Xilinx IP core clocked by the CPU clock
  (`JR_Math_Block.v:103`) whose configuration is not in the repository. `DIVQ` reads the quotient one
  instruction after writing the dividend, as NitrOS-9's own `wild.asm` does (lines 1988-1992); nobody
  here has proved that on hardware. A dozen-line harness on the K2 would.
- **Whole-game ratio.** The figure above is from 443 bytes of 6502. The translator's first run gives
  the real number file by file; the budget target will report it.
- **Cycle counts are the data sheet's.** They assume no bus stretching on the F256.

### For review

1. ~~Model B~~ **Approved (user, 2026-09-22).**
2. ~~The conventions in `pilot/pilot.d`~~ **Approved (user, 2026-09-22).**
3. **Go (user, 2026-09-22):** D6 step 1, `tools/m65to09.py`, emitting what `pilot/*_b.a` shows (routine order, labels and
   6502 line numbers kept), with `d6pilot.py` grown into the per-routine differential test.

## D6 step 1: the translator (2026-09-23, host only)

After the approvals, `tools/m65to09.py` translates the whole game mechanically into model B, as
the pilot's `*_b.a` do. The output is the **first draft** of the plan's D6 ("mechanical first draft,
hand finish, differential test"): nothing of it is hand-finished, nothing is in `src/`, nothing has
run on hardware. `xlat/` is regenerated by the tool (gitignored).

### The tools

| File | What it is |
|---|---|
| `tools/romalign.py` | **Every statement of the 12 files aligned with the Rev 3 ROM** (link order from `ALEXEC.MAP`). Each file is cut into runs of statements whose bytes are known in shape, separated by macro calls of unknown size; runs must follow on exactly, or after a bounded gap. All 12 sections come out **exactly** the sizes in the link map ($9000-$DFDB, 20,444 bytes); **179 labels** known both from the alignment and from an aligned reference to them **agree, none disagree**. It supplies every label's Rev 3 address, every data byte, and the bytes the macros make. 177 labels inside macro-built data (the messages, the cam bytecode, the `VEC` pictures) have no exact place, and need none: nothing names them except in label differences, whose values the ROM bytes already hold |
| `tools/m65to09.py` | **The translator.** Writes `xlat/*.a` in link order plus `port.d`, `arcade.d`, `stubs.a` and the 4K `vrom.bin`, and assembles `xlat/tempest.bin` with lwasm, retrying short branches that do not reach as long ones |
| `tools/xlattest.py` | **The differential test on the translated module**: named routines with their case generators (MODSND, DSPNYM), or `--fuzz`, every routine a JSR reaches on random RAM; `--trace` prints where the 6502's and the 6809's source-line paths part |
| `tools/m65parse.py` | Now: MACRO-11's **six-character symbols** (`INDYLOC` is `INDYLO`), the `.ASECT` location counter seen by assignments (`CBUF1 =.`), a line's radix, `#` immediates, RAM labels and `.GLOBL`s |
| `tools/cpu6502.py` | Now loads the **vector ROM at $3000** too (the CPU reads it), and records zero-page index wraps and decimal arithmetic on non-BCD digits for the fuzz |

### What the translator does

- **Model B throughout**, with the pilot's block-local caches (6809 Y = data base + X, 6809 X = list
  or table pointer + Y), `INX`/`INY` folded into offsets, and caches kept across a join when every
  way into it agrees (only joins that branches alone can reach: a source label may be a JSR or
  dispatch target).
- **Flags as a whole-program dataflow**: backward liveness of N, Z, V, C through JSR and RTS (an
  RTS is live in what is live after its routine's calls; routines entered only by Atari's RTS
  dispatch return where the dispatcher was called from; `PHP` is paired with its `PLP`), and forward
  tracking of how the 6809's CC holds the 6502's (carry inverted after a subtract or compare,
  `CLC`/`SEC`/`CLV` held as constants, N and Z disturbed by stores and pointer set-ups). At every
  join, call and return the live flags are put into 6502 form (`tfr cc,b / eorb #1 / tfr b,cc`
  inverts a carry); a branch on an inverted carry is simply inverted when nothing downstream reads
  it; a store that would change live N/Z the 6502 keeps runs inside `pshs cc / puls cc`.
- **Decimal mode as a dataflow** (`SED`...`CLD` across loops and calls): `ADC` in decimal mode gets
  `daa`. ZQAT4C's `SED` (anti-tamper sabotage, `ALEXEC:267`) is neutralised.
- **`BIT`** by what is read after it: N only → `tst`, Z only → `bita`, V only → `ldb m / andb #$40 /
  addb #$40` (V = bit 6 exactly).
- **Atari's RTS dispatch** (`LDA i,T+1 / PHA / LDA i,T / PHA`, then an RTS; seven sites) becomes
  one jump, and its table becomes 6809 offsets from itself (`fdb target-T`) with a parallel table of
  the 6502 words' low bytes, so A, N and Z at the target are exactly the 6502's.
- **The address macros** `LDAL`/`LDAH`/`LAH`/`LXL` are instructions; a vector-RAM address stored
  next into a CPU pointer is **relocated to window A** (`lda VWIN,u / adda #hi-$20`: the window is 8K
  aligned, so only the high byte moves), one used for a `JSRL` stays an AVG address.
- **I/O**: POKEY audio registers go to `POKIMG` by the symbol the source names (`STA X,AUDF2-8` is
  POKEY 2 even though its value is POKEY 1's AUDCTL); colour RAM to `CLRSHD` (for `SS.ClutWrite`);
  vector ROM reads to the module's `VROM`; everything else to a named shadow `HW_xxxx`, marked HAND.
- **Data is the ROM's own bytes.** One original quirk found by the test: MODSND reads the last
  sound sequence's `0,0` terminator's NUMBER byte from the code after the table (IPEXPL's `LDA
  I,SIDDI`); the module repeats those three ROM bytes after the table so the port reads the same.

### The draft

**28,013 bytes**, including the 4,096-byte vector ROM. **The translated game code is 17,829 bytes
against 13,188 bytes of 6502 instructions: a ratio of 1.35**, the pilot's planning figure (1.33).
Per file:

| File | 6502 bytes | 6809 bytes (code + data) |
|---|---:|---:|
| ALWELG | 6,320 | 8,123 (7,042 + 1,081) |
| ALDIS2 | 5,610 | 7,172 (5,789 + 1,383) |
| ALSCO2 | 2,310 | 3,202 (3,147 + 55) |
| ALLANG | 1,746 | 1,770 (84 + 1,686) |
| ALEXEC | 865 | 1,094 (986 + 108) |
| ALSOUN | 733 | 892 (458 + 434) |
| ALVROM (CPU side) | 326 | 326 (data) |
| ALVGUT | 211 | 323 |
| ALCOIN | 269 | 269 (kept as 6502 bytes: HAND) |
| ALHAR2, ALEARO | 522 | 725 (to be replaced by the platform layer) |
| vector ROM | (4,096) | 4,096 |

So the module budget stands as the pilot said: about **27.3K** for the game with its data and
vector ROM once ALCOIN is translated and ALHAR2/ALEARO give way to the platform, **leaving about
12.9K of the 40,192** for the platform layer, the AVG interpreter and the rest. Cycles: the
generated MODSND runs at **1.97** 6809 cycles a 6502 cycle, DSPNYM at **1.54** (the hand pilot:
1.95, 1.49).

### Hand work left, as the translator marks it (`* HAND:` lines)

| Category | Sites | What |
|---|---:|---|
| hardware | 92 | switch, option, watchdog, VG, EAROM, Math Box and coin registers: shadows `HW_xxxx` the platform layer fills or ignores |
| address-table | 33 | `.WORD` tables of 6502 addresses: ALWELG's skill table `WTABLE` (pairs of ROM-table and RAM addresses), ALLANG's language pointers, one self-word (`ALDIS2:1033`) |
| vram-table | 28 | `.WORD` tables of vector-RAM addresses (`BUFASL`, `BUFBSL`, `BUFSWL` and kin): relocated to window A at start-up, as the plan says |
| vram-absolute | 18 | vector RAM by absolute address: translated through `VWIN`, to be checked |
| bit, flag-lost | 8 | two `BIT`s that need both V and Z, two that need N and Z, two calls into routines the port does not have (`GETOP3`, `MOOLAH`) |
| irq, stack, brk | 5 | the IRQ (`ALHAR2`) and `SEI`/`CLI` around the POKEY check |
| stub | 3 | `GETOP3` (in the dropped self-test), `MOOLAH` and `RESET` (COIN65 and the reset code) |
| decimal | 2 | an `SBC` in decimal mode (`PRORAT`'s seconds countdown) and an `ADC` reached in both modes |
| dispatch | 2 | two state-table entries into the dropped self-test: `DSPSYS` in DROUTAD, ALTES2's entry ($D7E1) in ROUTAD |
| coin65 | 1 | ALCOIN is COIN65's macros; its 269 bytes are still 6502 |

Plus what was always going to be hand-made: **WORSCR and CASCAL on the coprocessor** (the pilot's
`worscr.a` is the model), and the **start-up relocation** of the pointer tables and pointer
constants (Joust's `reloc.a` way).

### The test, and what it found

**The pilot's routines from the translator are byte-exact**: MODSND and DSPNYM with their callees,
2,000 random cases each and 5,000 IRQs of the game's own sounds, at two code addresses.

**The fuzz: every routine a JSR reaches (190), on random RAM, against the ROM.** A case the game
cannot produce is skipped, not compared, and the rules for "cannot produce" are themselves a list
of what the port assumes: a data read of ROM code, or an index carrying a read out of its table's
stretch of ROM data; a zero-page index that wraps (none in real use found); an indexed or indirect
access landing on a pointer byte, a pseudo-register or the 6502 stack; decimal arithmetic on
non-BCD digits; a read through a pointer into ROM or outside RAM and vector RAM (those pointers are
relocated at start-up); a write carried onto POKEY by another device's index; a Math Box read.
Variables the game keeps small (`PLAYUP`, the state and type indices, the dispatchers' arguments)
are drawn from their real ranges.

| Result (30 random cases a routine) | |
|---|---:|
| Routines passing, every in-domain case byte-exact | **169** |
| Routines failing | **4**, all at HAND sites: INICHK, GAMSTA, INILIT (`GETOP3`), ENDGAM (`BIT` N and Z) |
| Routines with no in-domain case | 17: the Math Box users (through WORSCR/CASCAL: CHPLKI, SCAPIC, CALOUT, DSTARF, TIPACT, ...) and routines that work through ROM pointers or address tables (RNKDSP, DSPCRD, CONTOU, ...) |
| Cases compared, all byte-exact | 4,395 (1,186 skipped) |

**Translator bugs the test found and that are fixed**: code macros emitted as 6502 bytes; an
edit that dropped `BCC`/`BCS` from the flag table (every explicit carry branch looked unused); a
store through a pointer taken for a store to it (the list cache thrown away at every `STA
NY,VGLIST`); POKEY 2 mapped by value; labels keyed by name across files (ALSCO2's private `VGCNTR`
shadowing ALVGUT's); caches kept across a source label that is also a JSR target; macro-made words
anchoring the alignment in the wrong place (ALVROM's `JMPBLO`, which sent a switch pointer into
code). **Harness bugs likewise**: the 6502 had no vector ROM, its flags were never reset between
cases, memory was not cleared between cases, a layout overflowed 64K.

**What the fuzz is not**: random states, not game states. It shows the translation does what the
6502 does from any in-domain state; it does not show a game is played correctly, and its coverage
is thin where routines work through relocated pointers (the messages) until relocation exists.

### Decisions (user, 2026-09-23)

1. **Approved:** `xlat/` is generated and never edited; hand-finished code lives in `src/`, taken
   from the draft and re-tested with `tools/xlattest.py`.
2. **Approved, the recommended order:** the coprocessor WORSCR/CASCAL (from the pilot); start-up
   relocation of the pointer tables and constants; the six flag and `BIT` sites; PRORAT's decimal
   `SBC`; ALCOIN; the hardware shadows as the platform layer's seams.
3. **Approved:** extend the test with recorded game states (MAME RAM at frame boundaries, from
   `avgcap.lua`).

### Review points as put (answered above)

1. The draft's shape: `xlat/` generated, hand-finishing in `src/` from it (the translator's output
   is regenerated, never edited).
2. The hand-work list above, and its order. Proposed: the coprocessor WORSCR/CASCAL (from the
   pilot); start-up relocation of the pointer tables and constants; the six flag and `BIT` sites;
   PRORAT's decimal `SBC`; ALCOIN; the hardware shadows as the platform layer's seams.
3. Whether to extend the test with **recorded game states** (MAME's RAM at frame boundaries, from
   `avgcap.lua`) so that routines run on states the game really produces.

## D6 hand work (2026-09-23, host only) — for review

The approved order, each piece re-tested against Atari's ROM before the next. `src/` began as a copy
of the draft (`xlat/`, untouched and still regenerable) and is where the game is now finished by
hand; each file's first line says so. Nothing has run on hardware.

### How `src/` is tested

- **`tools/xlattest.py --src`** assembles `src/tempest.a` into `src/build/` (gitignored) and runs
  the named tests, the fuzz (`--fuzz`) or the recorded game frames (`--states`) on it. Without
  `--src` it tests the draft as before.
- **The named tests move everything.** With `--src` each routine runs with the code at $8000 and
  $8321, the data area at $1000 and $5300 and window A at $4000 and $6000, so a missed relocation
  shows. Each test names the routine's pointers, and a mapper carries their values between the
  arcade's addresses and the port's (RAM to the data area, vector RAM to the window, reloc.a's
  tables to their copies, ROM data to the module). The fuzz cannot do this: in random RAM a word
  may be a pointer or two scalars (TEMP3/TEMP4 are both, by turns).
- **One set of domain rules** for the fuzz and the named tests (`domain_checks`): a case the game
  cannot produce is skipped, not compared. Added this session: an index carrying a RAM table's
  access past $7FF; each relocated table a stretch of its own, which an index may not carry a read
  into; a data read of the top ROM's mirror ($F000-$FFFF); a `(zp),Y` access after an `INY` has
  wrapped Y, before Y is loaded again (below); `NUMPLA` 0 or 1; `UPSCLI`'s scale and player 0 or 1;
  COIN65's table at $CFD9 as data.
- **The translator's `INY` folding, measured.** It folds `INY`s into the next `(zp),Y` access's
  offset (`sta 1,x`), which is wrong if Y wraps from $FF to 0 in between. **Y does wrap in the real
  game** (1,621 times in the recorded frames, at `ALDIS2:3029`, `3158`, `3191`, `3206`, all at the
  end of a list block), **but in all 2,417 frames no `(zp),Y` access follows a wrap before Y is
  loaded again**. So the recorded frames confirm the folding, and the fuzz treats a random state
  that does this (a list offset of $FF) as outside the domain.

### 1. WORSCR and CASCAL on the coprocessor

**WORSCR** is the pilot's (`pilot/worscr.a`): its two Math Box divides are `DIVQ`.

**CASCAL** (`ALDIS2:1444`) asks the Math Box for `SZXD` with N = 24, dividend YDEUNI×256, divisor
Δy = PYL − EY (16 bits, signed). Run exhaustively in C against MAME's model over all 16.7 million
(YDEUNI, Δy) pairs, it is **the low 16 bits of floor(YDEUNI × 65536 / |Δy|), negated when Δy < 0**,
except where its 16-bit registers overflow: |Δy| ≤ 53 (and YDEUNI ≥ $80). Objects do come that near
the eye, in the dive down the tube, so the port reproduces both:

- `DIVF`, the fast path: two coprocessor divides, the second (the remainder × 256) done a bit at a
  time when the first remainder is 256 or more. Exact for YDEUNI < $80 and |Δy| ≥ 1 that is ≥ 54 or
  ≥ YDEUNI, which is **all of steady play** (there |Δy| ≥ YDEUNI, since PYL ≥ $10 and
  YDEUNI = $10 − EY).
- `MBDV24` everywhere else: MAME's own 25-step loop, overflow and all, in 6809.

Both paths were checked in C against MAME's model over every input they take (0 wrong of 8.4
million each), then on the 6809 by the differential test, with every path forced.

| | 6502 cycles (mean) | 6809 cycles |
|---|---:|---:|
| WORSCR | 198 | 290 |
| CASCAL, in play | 135 (+ the Math Box's time, which MAME does not model) | 352 median, 391 max |
| CASCAL, far objects (a wave's start: the bit-at-a-time second step) | | ~700 |
| CASCAL, nearer than YDEUNI (the dive: `MBDV24`) | | ~1,400 |

`DIVF` reads the coprocessor's remainder (`CP.REM`, $FEF6), which `JR_Math_Block.v` says is right
from rc14 on. **Unchecked on hardware**, like the divide's latency (D6 pilot, "Unchecked").

### 2. Start-up relocation

**`src/reloc.a`**, Joust's `reloc.a` way: each table's relocation source stays in the module in the
table's own place and size (so nothing around it moves), and `RELINI` copies it at start-up to the
data area from $A00 (`R.xxx` in `port.d`, 414 bytes to $B9D), adding the module's address (M), the
data area's (D) or window A's less $2000 (W). It writes the copies little-endian, as the translated
code reads them a byte at a time.

| Table | Words | Kind | Readers changed |
|---|---:|---|---|
| `BUFASL`, `BUFBSL`, `BUFSWL` (`ALVROM:2017-2049`; `BFASTA`, `BFBSTA` inside) | 27 | W | SBCLOG, SBCACT, SBCSWI, BIGTEX, WHICHB |
| `LNGTAB` (`ALLANG:253`) | 4 | D, to the copies below | INILIT |
| `ENGMSG`, `FREMSG`, `GERMSG`, `SPAMSG`: the message addresses | 120 | M | (read through `LITRAL`) |
| `WTABLE` (`ALWELG:728`): a skill table and the variable it sets | 28 × 2 | M, D | CONTOUR |

The message tables were not among the translator's HAND sites: the `MESS` macro builds them, so
they came out as plain bytes. **Pointer constants**: `ALSCO2:101` (INDYLO = HSCORL+23, a RAM
address: + the data area's page) and `ALSCO2:208` (INDYHI = 0, zero page: the data area's page).
**Not addresses after all**: `BONPTM` (bonus points) and `ALDIS2:1033` (a `.WORD` of its own
location inside a byte table, read as data); `ROTFLG`'s $2C (`ALDIS2:2502`) is only a flag. **The
18 vector-RAM-absolute sites**: each offset from `VWIN` checked against its symbol; all right.

Found on the way:

- **ZATC4V (`ALSCO2:105`) is anti-tamper** that `docs/port-tempest.md` §2.4 does not list: it XORs
  the 6502 code calling the ATARI message (`ZATC4S`) into `QT2`. The port's code there is 6809, so
  the check failed (`QT2` = $F9 instead of 0). **Neutralised** to its passing result (A = 0,
  Y = $FF, `QT2` = 0). The fuzz had hidden it, since a case reading code as data is skipped. `QT2`'s
  consumer is `ZQAT4C` (`ALEXEC:262`), whose `SED` the translator already neutralises.
- **A cross-file distance.** The draft reaches `MSGLBS` (ALLANG) as `ANITAB+509` (ALVROM),
  because `MSGLBS` has no label of its own in the module. That holds only while ALCOIN, linked
  between the two, keeps its 6502 size. Translating ALCOIN broke it, and the recorded game frames
  caught it at once (wrong message colours). `MSGLBS` is now a label. A scan finds no other
  cross-file offsets.

### 3. Flags, BIT, decimal, COIN65

- **`BIT WFUSCH`** (`ALWELG:2129`, `2149`; V and Z read) and **`BIT QSTATUS`** (`ALWELG:3112`,
  `ALEXEC:448`; N and Z): the 6502's BIT exactly for the flags read. V is bit 6 (or N bit 7) of
  memory, and Z is A AND memory.
- **Decimal `SBC`**: PRORAT's seconds (`ALWELG:208`, `SBC #1`) and UPSCOR's bonus-interval
  division (`ALEXEC:570`, `SBC BLIFIN` in a loop). A binary subtract sets N, Z and C as the NMOS
  6502 does in decimal mode, then −6 and −$60 make the digits BCD. Exact for BCD digits (non-BCD is
  outside the domain, as before).
- **GETOP3** (a stub; `ALTES2:632`, in the self-test the port drops): option bank 3 through the
  POKEYs' pot ports, into shadows. INILIT, INICHK and GAMSTA, which failed on the stub, now pass.
- **ALCOIN = COIN65 with Tempest's options** (BONADD=1, CNTINT=0, COIN=0, COIN01=1, SLAM=0, three
  mechs, three counters). COIN65 is mostly assembly-time conditionals, so the 6809 follows the Rev 3
  ROM's bytes ($CF24-$D030), each line marked with its address: 307 bytes against 269. Tested with
  2,000 random states and **20,000 interrupts of coins dropped** on the three mechs (switches closed
  for 20-40 ms, the odd slam, the coin mode changed now and then), compared at every interrupt;
  credits accrue as they should.
- The V "needed" after `JSR MOOLAH` (`ALHAR2:147`) is the IRQ's, which the platform rewrites; after
  `JSR GETOP3` nothing reads it.

### 4. Recorded game states

`tools/avgcap.lua` gained `AVGCAP_RAM`: at the start of every n-th game frame (MAINLN's
`STA FRTIMR` at $C7AF, just before `JSR EXSTAT`), MAME's 2K of RAM, the 4K of vector RAM and the
switches (IN0, both option banks, both POKEYs' ALLPOT). **The switches matter**: they are active
low, and a rig answering 0 has the test switch on, so the game walks into its self-test.
`xlattest.py --src --states FILE...` runs **whole game frames**: EXSTAT, NONSTA and DISPLA in turn
on both CPUs, each from the 6502's result of the last, everything compared after each.

Captured (MAME unmodified, `captures/`, regenerable): **300 s of the scripted played game** (every
5th frame: 1,623 states across play, pause, new life, end of wave, the high-score states and the
bonus) and **150 s of attract** (794 states: the demo, the logo, the text screens). From
`captures/`:

    AVGCAP_OUT=/dev/null AVGCAP_EVERY=0 AVGCAP_PLAY=1 AVGCAP_RAM=states_play.bin AVGCAP_RAMEVERY=5 \
      /usr/games/mame tempest -rompath ../tempest_orig/notebooks/roms -autoboot_script ../tools/avgcap.lua \
      -nothrottle -seconds_to_run 300 -video none -sound none

and the same without `AVGCAP_PLAY` into `states_attract.bin` for 150 s (about 30 s and 15 s).

**Result: all 2,417 game frames are byte-exact after each of the three calls.** Per frame, the
6502 averages 30,601 cycles and the 6809 60,020 (ratio 1.96): **7.5 ms of the 36.6 ms frame at
8 MHz**, inside the pilot's 6-8 ms estimate, before the interpreter and `SS.BmLine`.

These run with the data area and the window at the arcade's places: a real state's pointers are
not all known (the named tests are where things move). `LITRAL` is mapped. The other pointers
compare equal, or equal once mapped back. That includes a leftover page: after CONTOUR, TEMP4 still
holds a skill table's page while TEMP3 has since been used as a scalar.

### Results (the final tools, `src/`)

| Test | Result |
|---|---|
| Recorded game frames (`--states`, both captures) | **2,417 byte-exact**, after each of EXSTAT, NONSTA, DISPLA |
| Named tests (`--src`, 1,000 cases each, everything moved) | **21 routines, all byte-exact**: 1,000 cases each (in the domain: PRORAT 705, INFO 42, which the recorded frames cover), MOOLAH also 20,000 interrupts |
| The fuzz (`--src --fuzz`, 30 random cases a routine) | **176 of 190 pass, none fail**; 14 have no in-domain random case (they work through relocated pointers). The recorded frames run 13 of them, most hundreds of times; **`PL1RNK` is run by neither** (untested) |
| The draft (`xlattest.py`) and the pilot (`d6pilot.py`) | unchanged: all pass |

### The module

**28,352 bytes** (the draft 28,013): WORSCR with CASCAL's divides 377 bytes (was 252), COIN65 307
(was 269), `reloc.a` 122, GETOP3 27. The data area now needs up to $B9D for the relocated tables,
before the stack and the platform's variables.

**HAND markers left: 78**, all the platform layer's: 69 hardware registers (the shadows `HW_xxxx`,
the approved seams), ALHAR2's IRQ (`SEI`, `CLI`, `RTI`, `TSX`, `BRK`, MOOLAH's V), the RESET stub and
the self-test's two dispatch entries (`DSPSYS` in DROUTAD, ALTES2's $D7E1 in ROUTAD).

### Harness changes (tools)

`xlattest.py`: `--src`, `--states`/`--every`/`--limit`, the relocated named layouts with per-routine
pointers (big-endian, little-endian, swapped, soft), `Mapper`, `domain_checks` shared, generators
for CASCAL, the relocation users, UPSCOR (BCD scores near a 10K boundary), PRORAT, MOOLAH and the
coin sequence. `d6pilot.py`: `Rig.case` takes registers to skip (BIGTEX and DSBOOM leave a pointer's
high byte in A or Y) and an `accept` hook. `avgcap.lua`: `AVGCAP_RAM`, `AVGCAP_RAMEVERY`.

### For review

1. **ZATC4V neutralised** (anti-tamper, not in `port-tempest.md` §2.4's list; added there now).
2. **CASCAL's exact overflow path** (`MBDV24`, ~1,400 cycles, only for objects nearer the eye than
   YDEUNI, as in the dive) against the formula there (fewer cycles, a different scale for those
   objects than the arcade's). Recommendation: keep it exact; the dive is short.
3. **The data area** now runs to $B9D (the relocated tables); the platform layer's layout starts
   from there.
4. Next, by the plan: the platform layer (the hardware seams, the IRQ as the frame loop, the module
   header and `make pic`), for which the SS calls are proposed first.

## Stage 2 on the host: the AVG interpreter (2026-09-23) — for review

The plan's stage 2 without the hardware half: the 6809 AVG interpreter, run on the host 6809 over
MAME's captured display lists and checked record for record against its specification. **No SS
call is needed**: the interpreter uses `SS.BmLine` as it is (255 records a call; below). Nothing has
run on hardware.

### What was built

- **`tools/avgview.py`**, three additions beside the float pipeline (which stays, as stage 0's
  reference to MAME):
  - `InstrAVG`: the AVG one instruction at a time. The state PROM runs a fixed handler sequence per
    opcode and the timer is 0 whenever a vector starts, so an instruction-level machine is exact:
    **`--verify` finds its beam points identical to the PROM machine's on all 6,282 captured
    frames**, and checks the arithmetic below on every one of their 3,797,586 vectors.
  - `PortAVG`: **the 6809 interpreter's specification**, integer only (below). `--port` gives its
    numbers and, with `--png`, its picture (glyph text from `captures/glyphs`).
  - `--compare` (the port against the float pipeline) and `--tables` (writes `src/avgtab.a`).
- **`src/avg.a`**: the interpreter, `AvgRun`, by hand. **1,504 bytes**, and **`src/avgtab.a`**
  (generated by `avgview.py --tables`: the glyph map and table), 1,041: 2,545 in all, with the
  vector ROM already in the module.
- **`tools/avgtest.py`**: assembles `avg.a` with a test `AvgFlush`, runs `AvgRun` on the host 6809
  and compares every record, every text entry and the end state with `PortAVG`; frames alternate
  between two layouts (module, data area and window A all moved). `--fuzz N` runs random display
  lists instead; `--sw` builds the software multiply. Models the coprocessor's multiplier as the
  RTL has it and fails any access with IRQ unmasked.
- **Captures** (`captures/`, regenerable, as stage 0's): `avg_attract.bin` (150 s, every 3rd frame)
  and `avg_play.bin` (300 s of the scripted game, every 5th):

      AVGCAP_OUT=avg_attract.bin AVGCAP_EVERY=3 /usr/games/mame tempest -rompath ../tempest_orig/notebooks/roms \
        -autoboot_script ../tools/avgcap.lua -nothrottle -seconds_to_run 150 -video none -sound none

  and `AVGCAP_OUT=avg_play.bin AVGCAP_EVERY=5 AVGCAP_PLAY=1 ... -seconds_to_run 300`.

### The arithmetic (`PortAVG`, `avg.a`)

- **MAME's move is exactly `v_eff × L × 2^(8−bs)`** for an integer `v_eff` (L = linear scale ^ $FF,
  bs the binary scale): `v_eff` = v, except that a VCTR whose normalisation count n is below 3
  drops its low 3−n bits, n + bs ≥ 16 clamps the timer (v shifted up by n+bs−15), and an SVEC is
  2·v5, shifted up when n + bs > 8. n comes from T, the OR of the components' magnitudes-less-one,
  with no loop. Checked on every captured vector (above).
- **The beam is kept in bitmap pixels**, 16.8 fixed point, 3 bytes an axis, half a pixel high so its
  integer bytes are the rounded pixel. A vector moves it by `v_eff × Q / 256`, truncated toward zero,
  with `Q = round(L × 12/29 × 256 / 2^bs)` set by each SCAL (a repeated SCAL, 67% of them, is
  skipped). So no per-point mapping: the 580×570 → 240-row scaling is folded into Q.
- **Clipping**: Cohen-Sutherland on whole pixels, rounded intersections (a software 32/16 divide;
  0.3% of lines need it, 41 at most in a frame). Endpoints beyond ±8,192 px drop the line.
- **Against the float pipeline** (`--compare`, glyphs off): of 8.9 million coordinates, **0.39% are
  1 px off and none more**; 7 of 6,282 frames differ by one or two lines at a screen edge (the
  rounded clip keeps a line the exact one drops). Side by side (play frame 3000) the pictures are
  the same, glyph text apart.
- **Characters (D3)**: a JSRL to one of the 41 VGMSGA characters at a text scale ((1,0) or (0,0))
  is not run: it appends a text entry (glyph, big flag, colour × 16 + the glyph's intensity, the
  rounded beam) and moves the beam by the glyph's advance, computed by running the character
  through this same arithmetic, so the beam ends exactly where running it would leave it. **DASH,
  HALF and COPYR lie after the VGMSGA table** (word addresses $91B-$92E), so the map runs
  $800-$92E (303 bytes). HALF leaves scale (1,0), as recorded.
- **Output**: 8-byte `SS.BmLine` records in batches of at most 255 (its existing limit), each handed
  to `AvgFlush` (the platform's: X records, B count, U/DP the data area's) as it fills and at the
  end; texts (6 bytes: glyph, CLUT, column, row) up to 256. **Plan 6.2 (3), more than 255 records
  a call, is not needed** for this.
- **A list ends** at HALT or JMPL 0; after 1,024 control transfers it is a runaway, cut off.
  Unspecified (the 6809 walks on): running off the end of vector RAM or ROM without a jump.

**Layout** (in `port.d`): the interpreter's variables are one page, **`AVGPG` = $0C00** of the data
area, DP while it runs (so the data area must be page-aligned, as OS-9 allocates it). Window A:
vector RAM $0000-$0FFF, the record batch **$1000-$17F7**, the text list **$1800-$1DFF**.

### Results

| Test | Result |
|---|---|
| `avgtest.py`, both captures (6,282 frames, both layouts), coprocessor multiply | **6,282 byte-exact** |
| the same, `--sw` (software multiply) | **6,282 byte-exact** |
| `--fuzz 10000`, each variant | **10,000 random lists, 0 failed** |

The fuzz found one bug the captures met once (attract frame 8106): the clamp at bs = 4 was
skipped. Fixed; with the bug put back, the fuzz fails 2 lists in 1,000.

**The load** (`avgview.py --port`, frames from 600): play, records median **206**, 95% 287, max
415; texts up to 78; attract up to **646 records** (the logo zoom, frames 1929-2133 of each cycle:
thousands of short strokes) and 148 texts. **Single-pixel records ("dots") are 59% of play's
records**: objects far down the tube, whose strokes round to one pixel.

### Time (host 6809 cycles, 8 MHz)

| Frames | Median | 95% | Max |
|---|---:|---:|---:|
| Play (3,481) | 139,566 (**17.4 ms**) | 181,849 (22.7 ms) | 229,634 (28.7 ms) |
| Attract (2,801) | 136,532 (17.1 ms) | 316,602 (39.6 ms: the logo) | 359,752 (45.0 ms) |
| Play, software multiply (`--sw`) | 149,285 (18.7 ms) | 197,886 (24.7 ms) | 248,937 (31.1 ms) |

Per vector: decode ~80 cycles, move ~95 (with the coprocessor), a record ~140. Tried and measured
on the way: the first draft took 28 ms; the half-pixel bias, inline records and the SCAL skip took
it to 21; the coprocessor's multiplier to 17.5.

**Measured and dropped: reusing unchanged sub-lists.** The list is nine JSRLs to buffers; about half
of them look unchanged from one captured video frame to the next, but only because the game draws
a new list on about 45% of video frames (27 Hz): between game frames nearly everything changes.

**The frame budget, median play frame**: the game 7.5 ms (D6 hand work) + the interpreter 17.4 ms
+ the driver ~5-6 ms (206 records at the estimated 25-30 µs, one call) + sound, input, the clock
≈ 31 ms of **36.6**. It fits the median with little room; the 95% frame (22.7 ms here, and the
game's heavy frames) does not, so those frames stretch, as 6% of the arcade's own do. The attract
logo runs at about half speed.

### For review

1. **The CPU budget.** The interpreter is the largest item, at about twice the plan's hope. Ways
   down, not built:
   - **Drop redundant dots** (a spec change, picture identical): a single-pixel record in the
     colour of the record just before it, on one of its ends, repaints nothing. 30 of ~158 records
     a play frame (sampled): ~0.75 ms of driver time and ~0.4 ms here.
   - **Accept stretched frames** in heavy scenes (the arcade's own behaviour).
   - Further tuning here: I estimate 14-15 ms at best with this design.
   - The driver's per-record cost (stage 1's `tline S`) is the other half of the question.
2. **The coprocessor's multiplier**: `AvMove` uses the D8 unit's 16×16 multiply (combinational:
   `TextAddy_Mult`, PipeStages 0), masked per vector as the divide is. D8 approved the unit for the
   divide; this extends it to the multiplier (`CP.MA`, `CP.MB`, `CP.PROD` in `port.d`), and saves
   1.2 ms a play frame (7%). The software multiply stays behind `AVGSWM`. Unchecked on hardware, like the divide.
3. **The layout**: `AVGPG` $0C00 (one page), window A's record batch and text list.
4. **Next**, by the plan: stage 2's hardware half (`avgplay`) waits for the fixed core; before it,
   the platform layer, whose SS calls are proposed first.

## Open items

1. The line-engine holes (FPGA developer).
2. `tline` for stage 1, when the core is fixed: above all the per-record cost.
3. **Stage 2 on the host, for review** (section "Stage 2 on the host", "For review"): the CPU
   budget above all.
4. `SS.MsDelta` storage (5 bytes of vtio statics, 242 → 247 of 256).
5. The coprocessor divide's read-after-write timing, and its remainder, on hardware (D6 pilot,
   "Unchecked"; `DIVF` reads the remainder). Now also the multiplier's (`avg.a`, if approved).
6. Stage 2's hardware half (`avgplay`): the interpreter's records through `SS.BmLine` on the fixed
   core, photographed against `avgview.py --port --png`.
