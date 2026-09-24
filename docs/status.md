# Tempest for NitrOS-9 Level 2 on Wildbits F256: status

**2026-09-23.** Stage 0 complete; the D6 pilot, the translator and the D6 hand work done, reviewed
and committed (`07e63de`): the game, hand-finished in `src/`, runs all 2,417 game frames recorded
from MAME byte-exact against Atari's ROM. Stage 2's interpreter is done on the host (section
"Stage 2 on the host"; its CPU budget and layout approved). **The platform layer is built, for
review** (section "The platform layer"): `src/tempest`, a 34,693-byte OS-9 module, runs the whole
game on the host 6809 with the OS-9 calls scripted (`tools/osrun.py`, every frame checked) and
starts, takes a coin and a start and exits cleanly on NitrOS-9 in the Wildbits MAME. The loop runs
**one pass a tick, the game frame split across passes** (`SS.Tick`, proposed first, was
withdrawn): the game's clock keeps time, at 14 game frames a second in the model. Committed at
`8a5f02a` before the split; the split is not committed. Nothing has run on hardware.

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
- **Stage 2 (user, 2026-09-23):** redundant dot records are dropped (below, "Stage 2 on the
  host"), and **the coprocessor's multiplier is approved**, as D8's divide is: masked per use.
- **Stage 2's CPU budget and layout (user, 2026-09-23):** approved; heavy frames stretch, no
  more tuning before `tline S`; `AVGPG` $0C00 and window A as built.
- **The rest (D2, D5, D6, D7, D9, D10):** the plan's recommendations stand unless the user says
  otherwise. D9 loses its triple-buffer option (all three bitmaps are used).

## Hardware findings

**The line engine drops pixels** (K2, the DMA-fixed core and a newer one, 2026-09-22). Clear-then-fan
shows gaps that move every run; a second pass fills most. DMA fills and CPU writes are clean. With the
FPGA developer; **the port assumes a fix** (user). Full account: `docs/port-tempest.md` §4.2. Re-run
bmtest `C`+`L` and `C`+`F` on each new core.

**Fixed (user, 2026-09-23): "Line engine is fixed."** On the new core the K2 then ran **`tempest`
(the split-frame build, edition 2), the first run on hardware: it plays.** The user's photograph of
the square well in play shows solid lines, the well, claw and enemies in the right colours and
places, and the glyph text (score, lives, high score, level) lined up with them. **"It plays, but
it is really slow."** Not yet measured: the next build prints game frames, passes and seconds on
`q` (the host model's own figures: 14.7 frames and 60 passes a second). The user's idea for later:
**640×240**, to look more like a vector monitor, once the line engine can do it. The defs list only
320×240 and 320×200 bitmaps (`wildbits.d:866`), so that is a core question first. **The same
day the developer sent a core with the line engine and a 640×240 mode**: for the next session,
with the optimisation.

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
- **`src/avg.a`**: the interpreter, `AvgRun`, by hand. **1,590 bytes**, and **`src/avgtab.a`**
  (generated by `avgview.py --tables`: the glyph map and table), 1,041: 2,631 in all, with the
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
  end; texts (6 bytes: glyph, CLUT, column, row) up to 256. **A redundant dot is not sent**
  (decided 2026-09-23): a zero vector (a dot where the beam is) in the colour of the last record
  sent, on that record's end, would repaint the pixel it has just painted, so the picture is the
  same. The interpreter keeps the last record's end and colour in its page (13 cycles a record)
  and tests only zero vectors, which no longer call the move at all. Nearly every such dot is a
  tiny picture deep in the tube: an invisible move that rounds to no move, then a zero vector.
  In the captures all 27 a play frame are on the last record's end (none on its start only), and
  91% of the single-pixel records that could go are zero vectors; a general check on every record
  cost more in the interpreter (+1.3 ms) than it saved in the driver, so it was not kept. **Plan 6.2 (3), more than 255 records
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
skipped. Fixed; with the bug put back, the fuzz fails 2 lists in 1,000. Half its lists are
dot-heavy (zero vectors, two colours, the beam out through an edge and back), which catches a
last-record copy updated for a dot never sent (58 of 3,000 fail with that bug put back) and a
dot rule without its colour test (320 of 2,000).

**The load** (`avgview.py --port`, frames from 600): play, records median **161**, 95% 245, max
381 (206, 287, 415 before the redundant dots went); texts up to 78; attract up to **646 records** (the logo zoom, frames 1929-2133 of each cycle:
thousands of short strokes) and 148 texts. **Single-pixel records ("dots") are 59% of play's
records**: objects far down the tube, whose strokes round to one pixel.

### Time (host 6809 cycles, 8 MHz)

| Frames | Median | 95% | Max |
|---|---:|---:|---:|
| Play (3,481) | 134,909 (**16.9 ms**) | 176,757 (22.1 ms) | 233,183 (29.2 ms) |
| Attract (2,801) | 135,723 (17.0 ms) | 335,080 (41.9 ms: the logo) | 378,230 (47.3 ms) |
| Play, software multiply (`--sw`) | 147,258 (18.4 ms) | 197,707 (24.7 ms) | 254,786 (31.9 ms) |

With the dots dropped, play is 0.6 ms faster at the median than without (17.45 ms) and sends 45
fewer records a frame, ~1.1-1.4 ms of the driver at its estimated 25-30 µs a record.

Per vector: decode ~80 cycles, move ~95 (with the coprocessor), a record ~140. Tried and measured
on the way: the first draft took 28 ms; the half-pixel bias, inline records and the SCAL skip took
it to 21; the coprocessor's multiplier to 17.5.

**Measured and dropped: reusing unchanged sub-lists.** The list is nine JSRLs to buffers; about half
of them look unchanged from one captured video frame to the next, but only because the game draws
a new list on about 45% of video frames (27 Hz): between game frames nearly everything changes.

**The frame budget, median play frame**: the game 7.5 ms (D6 hand work) + the interpreter 16.9 ms
+ the driver ~4-5 ms (161 records at the estimated 25-30 µs, one call) + sound, input, the clock
≈ 30 ms of **36.6**. It fits the median with little room; the 95% frame (22.1 ms here, and the
game's heavy frames) does not, so those frames stretch, as 6% of the arcade's own do. The attract
logo runs at about half speed.

### Decided (user, 2026-09-23), and what is left

1. **Redundant dots are dropped** (above). **The coprocessor's multiplier is approved** for
   `AvMove`, as D8's divide: masked per use; the software multiply stays behind `AVGSWM`
   (`CP.MA`, `CP.MB`, `CP.PROD` in `port.d`). Unchecked on hardware, like the divide.
2. **The CPU budget: approved (user, 2026-09-23)** as recommended: heavy frames stretch (the
   arcade's own behaviour); no further interpreter tuning until stage 1's `tline S` gives the
   driver's per-record cost.
3. **The layout: approved (user, 2026-09-23)**: `AVGPG` $0C00 (one page), window A's record batch
   ($1000-$17F7) and text list ($1800-$1DFF).
4. **Next**, by the plan: stage 2's hardware half (`avgplay`) waits for the fixed core; before it,
   the platform layer, whose SS calls are proposed first.

## The platform layer (2026-09-23, host and MAME) — for review

The module now exists: **`src/tempest`, an OS-9 program module of 34,873 bytes** (the budget is
40,192), built by `make` in `src/` with the budget and **`make pic` clean**. The game, the
interpreter and the platform layer run together on the host 6809 with the OS-9 calls played by a
script, and start, draw text, take input and exit on NitrOS-9 in the Wildbits MAME. **Nothing has
run on hardware**, and MAME has no line engine, so no line has been drawn by a real driver yet.

### What was built

| File | What it is |
|---|---|
| `src/tempest.asm` | The module: header, `data.a`, the platform files, `avg.a` with its tables, the game in link order, `hw.a`, `reloc.a`, the vector ROM. `src/tempest.a` stays the host tests' build of the game alone |
| `src/makefile` | `make` builds, checks the budget (40,192) and runs `make pic`; `make install DSK=` is the targeted copy |
| `src/data.a` | The data area, 8K: the arcade's 2K, the port's variables, the hardware shadows, `RELTAB`, `AVGPG`, then the platform's (the last text list, the CLUT buffer, windows, input, the loop) and a 2K stack from `$1800` |
| `src/platform.a` | Joust's: start-up, window A (`F$AllRAM` + `F$MapBlk`, cleared, `VWIN`), `Map1`, pause (`SS.WSig`), the signal intercept, the terminal options, the exit on every path, the sign-off |
| `src/frame.a` | The frame loop, **one pass a tick**, and **the IRQ on a virtual 246 Hz clock** (below); the game frame split across passes, the drawing a coroutine; the arcade's reset |
| `src/input.a` | Keyboard, stick and mouse into the arcade's switch bytes and encoder (D4) |
| `src/gfx.a` | Three bitmaps, the clear, the flip, **`AvgFlush` into `SS.BmLine`**, the CLUT from colour RAM |
| `src/text.a` | **The text bitmap (D3)**: the interpreter's text list drawn as glyph masks, only what changed |
| `src/glyphs.a` | Generated (`tools/glyphs.py --asm`): the 41 glyphs at both sizes as 15-byte mask records |
| `src/hw.a` | `RANDOM`/`RANDO2` as a generator (below) |
| `tools/osrun.py` | **The host run**: the module on the host 6809, every `os9` call answered by the script (bitmaps in "physical" blocks, the line engine with avgview's Bresenham, the CLUT, the layers, keys from a script, the coprocessor, a tick every 133,333 cycles); checks after every game frame and pictures |
| `tools/piccheck.py` | Joust's, with **the coprocessor `$FEE0-$FEFF` as the second approved exception** (D8) |

### The seams, as built

- **The IRQ is ALHAR2's own**, a subroutine now (`RTI` is `RTS`; the 6502 stack check and its
  reset are gone). The loop runs it once a **virtual IRQ: 246.09375 Hz is exactly 525/128 of the
  tick**, so each tick adds 525 to an accumulator and each 128 is one IRQ (MOOLAH, MODSND, FRTIMR,
  the clocks). A game frame runs when FRTIMR reaches 9, the arcade's rule. Before each virtual IRQ
  the platform fills the three input shadows the IRQ reads, in the arcade's polarity (from MAME's
  `tempest.cpp` and the captured switches): `ALLPOT` = the encoder counter inverted, upright;
  `ALLPO2` = zap, fire and the starts active high; `IN1` = coins and switches active low, **bit 6
  set: the vector generator is always halted** between frames, which `DISPLA`'s halt handshake
  needs. The encoder moves at most 7 counts a virtual IRQ, the rest wait (the IRQ reads a 4-bit
  difference, as the arcade's knob).
- **Ticks: one pass a tick, as Joust, and the game frame split** (below, "The split frame").
  `SS.Tick` was proposed first and withdrawn (plan 6.3).
- **`RANDOM` and `RANDO2`** (20 reads in the game) call `RNDA`/`RNDB`: a 16-bit xorshift (7, 9, 8),
  one state (`RNDST`), stepped a read, seeded from the clock. The differential tests give Atari's
  code the same generator read for read, and compare its final state (a one-line mutation is
  caught at frame 40). **`ZPOKST` and `ZPONTS` are neutralised** to their passing results: both
  test for a real POKEY, which the generator is not (docs/port-tempest.md 2.4). The self-test's
  two dispatch entries (`CSYSTM`, `CDSYST`) are no-ops now.
- **The EAROM** is not read at start (`REHIIN` is not called): the high scores are the game's
  defaults each run until the settings file (stage 7f). Its writes land in the shadow page, and
  its source pointers are made logical (`EASRCE` + the data area's page).
- **The display** (D3, D9): bitmaps 0 and 1 the lines, double-buffered, the hidden one cleared
  first in a game frame's logic pass (`SS.BmClear`, wait mode 7, 16-bit; the CPU through the service window if
  that ever fails) and shown after (`SS.Layer`, layer 1); bitmap 2 the text on layer 0 in front;
  layer 2 tile map 0, with tile maps off. One CLUT: `colour × 16 + intensity`, the 16 entries of
  each colour RAM byte that changed, one `SS.ClutWrite` for the range.
- **The text bitmap** redraws only what changed: an entry changed when it differs from last
  frame's at the same index; changed old ones are erased (drawn in 0) and their rows marked,
  changed new ones drawn, and unchanged ones on a marked row redrawn. The bitmap is reached a
  block at a time through the service window, a glyph row at a time.
- **Logical space**: module 5 blocks, data area 1, window A 1, the service window 1 (text rows now;
  the sound page `$C4` too once D5 is built, by turns): 8. `F$MapBlk` is only ever asked for one.
- **Controls** (D4): arrows turn at 2 counts a tick (a guess, direction unchecked), Shift fires,
  `z` zaps, `1`/`2` start, `5` drops a coin (the left mech closed for 8 virtual IRQs), `q` quits;
  joystick 0 the same; the mouse through `SS.MsDelta` when the driver has it (it does not yet: the
  program asks and runs without).

### Tests

| Test | Result |
|---|---|
| `xlattest.py --src --states` (after every change here) | **2,417 game frames byte-exact**, with the generator |
| `xlattest.py --src` (named) | **all pass** (run before two label renames, which the states run covers) |
| `xlattest.py --src --fuzz -n 30` | **176 of 190 pass, none fail**, 14 without an in-domain case (as before) |
| `avgtest.py`, both captures | **6,282 frames byte-exact** |
| `make pic` | **0 reported**. It found two real faults first: `tst <SIGCODE` and `<PAUSED`, direct-page accesses to variables at `$1750` |
| **`osrun.py`, 60 s of the scripted game** (coin, start, fire and turning; a game on the circle well, lives lost, the score climbing) | **every game frame checked, none wrong**: the text bitmap equals its list drawn from scratch, the CLUT equals colour RAM's decode, the bitmap shown holds exactly that frame's records. The pictures match `avgview`'s of MAME's frames in kind (the claw's lane in yellow, as the arcade) |
| **The Wildbits MAME** (`wbjr2`, the Jr2 image, a targeted copy; weak evidence, no line engine) | starts, the three bitmaps and the CLUT set, the attract text screens cycle (INSERT COINS, the default HIGH SCORES, GAME OVER); **`5` then `1` gives CREDITS 1, then PLAYER 1 / RATE YOURSELF**; **`q` exits** to "Tempest over." with the text mode and the prompt back. It found one fault: the display mode passed in `R$X`'s high byte (the display was off) |

Also caught while building: case-insensitive clashes (`FRAMES` and `INPUT` with `arcade.d`,
`_DS1` between `avg.a` and `alwelg.a`, two of the platform's own) and one silent one: the game's
table `LEVEL` against the defs' `Level` (= 2), which assembled without error, as an address of 2,
until renamed (`LEVTAB`). A scan of every game operand against the defs' names finds none left.

### The split frame (2026-09-23, after review)

`SS.Tick` was withdrawn in review. The loop now counts ticks as Joust does, **one pass a tick**
(`F$Sleep X=2`, the controls, 525/128 virtual IRQs), which is right only if **no pass runs past
its tick**. A game frame is about 35 ms of work, so it is split:

- **The logic pass**: when FRTIMR reaches 9, the clear of the hidden bitmap, `EXSTAT`, `NONSTA`,
  `DISPLA` (10-13 ms with the controls and the IRQs), and nothing else. The logic varies too
  much to share its pass with drawing.
- **Drawing passes**: `Draw` (the interpreter into the hidden bitmap, the flip, the CLUT, the
  text) runs as a **coroutine on a stack of its own** (`DRWSTK`, 384 bytes; `DrwBeg`, `DrwRes`,
  `Spend`). Each step is charged to the pass's budget (`WORK`, 12,500 estimated µs) and the
  coroutine gives the tick back when the next step would not fit. `AvgFlush` charges each
  `SS.BmLine` call (160 µs a record, interpreted and drawn, and 474 a call) and **sizes the next
  batch to the budget left** (`NxtBat`, through a new byte of the interpreter's page, `AV.RMAX`:
  the caller's batch size, 0 = `RBATCH`); the text charges each glyph (1,000 µs and 60 a row,
  which covers a remap of the service window).
- A frame whose drawing is not done when FRTIMR next reaches 9 starts late, as the arcade's do.
  Between drawing passes only the IRQ's code runs, which the arcade already ran at any moment.

**Measured on the host (`osrun.py`, 120 s of play; the driver's costs still guessed):**

| | |
|---|---|
| Virtual IRQs | **245.9 a second** (the arcade's 246.1) |
| Passes | median 10.3 ms, 95% 13.1, 99% 14.7, max 17.0 of the 16.7 ms tick: **1 tick lost in 7,200** |
| Game frames | **14.1 a second** (median 3.4 ticks from the logic to the drawing's end) |
| Checks | every game frame's text bitmap, CLUT and line bitmap right |
| `avgtest.py` (the interpreter with `AV.RMAX`) | **6,282 frames byte-exact** at the default batch and with `--batch 0` (a random size set at every flush); **10,000 random lists** with `--batch 0`, none failed |
| The game's files | untouched by the split: the byte-exact results above stand |

How the estimates were chosen: a record's interpretation cost is 99 µs at the median and 208 at
the 99th percentile, and no free count (records, texts, control transfers, AVG instructions)
predicts a batch better than ±1.7-2.3 ms at the 95th; so the estimate is set high enough to lose
almost no ticks. Tried in 60 s runs: 145 µs a record, 30 ticks lost and 15.1 frames a second;
160, 3 lost, 14.8; 180, 1 lost, 14.1; **160 with a 12.5 ms budget, none lost, 14.6** (kept).

**The cost: 14 game frames a second against 21 unsplit** (the unsplit loop kept perfect time
only with a tick count). A logic pass uses about 11 ms of its 16.7 and the drawing passes about
10, the rest being the margin the estimates need. Ways to win it back, none built:

1. **An exact clock instead of estimates.** VICKY's raster row (MAME's `wbjr2` reads it at
   `$FFDA/$FFDB`; unchecked in the RTL) would let `Spend` fill each pass to the tick. It would be
   a third absolute-address exception, a read only.
2. **Overlap the logic with the drawing**, as the arcade does: the game's display lists are
   double-buffered for an AVG that runs beside it, and its halt handshake (`IN1` bit 6) would say
   "not halted" while a drawing is under way. Arcade-faithful, but the tests do not cover the
   interleaving yet.
3. **The driver's real cost** (`tline S`): every estimate above rests on a guessed `SS.BmLine`.

**In the Wildbits MAME** the split build starts, takes a coin and a start, shows the rating
screen and exits cleanly, as before. Its rating countdown ran 7 to 0 in 10 s of MAME's time,
i.e. the game's clock ran slow there. **Unexplained, and MAME is no evidence of timing**; the host
model keeps time. A hardware run will say.

### For review

1. ~~`SS.Tick`~~ **Withdrawn (user, 2026-09-23)**; the frame is split instead ("go", the same day).
2. **The seams above**: the generator for `RANDOM` and the two neutralised POKEY checks; the IRQ
   as a subroutine; the EAROM not read until the settings file; the switch polarities.
3. **The frame rate**: 14 a second split (above), and the three ways to win it back: the raster
   row as a clock (an exception), overlapping logic and drawing, `tline S`.
4. **Next**, by the plan: the hardware half needs the fixed core (the module can go on the K2
   as it is, `make install DSK=`). Without hardware: D5's sound output stage (stage 4, the SIDs on
   the service window), or `SS.MsDelta` in the driver.

## Optimising, and 640×240 (2026-09-23) — for review

### The K2's first numbers, and the lost tick

The sign-off on the K2 (line-engine-fixed core, the split build): **1,267 game frames, 5,695
passes in 116 s**. 116 s is 6,960 ticks, so **1,265 ticks were lost: one per game frame, almost
exactly** (10.9 frames and 49.1 passes a second; the game's clock, which counts passes, ran at
82%).

**The cause: the hidden bitmap's clear waited for the next vertical blank.** `SS.BmClear` wait
mode 7 polls until the fill is done, and the DMA engine only fills in vertical blanking
(`TinyVKY_DMA_Controller.v` `WAIT_2_TRF`: at once if armed before line 42 of 525, otherwise from
the next line 0, which is also the tick). The logic pass arms it after the tick's ISR, the wake,
the controls and the virtual IRQs, well past line 42, so it waited ~15 ms for the next blank and
the logic then ran into the tick after that. This also explains **the slow game clock seen in the
Wildbits MAME** (open item 4), assuming MAME's DMA waits the same way (not checked).

`osrun.py` had the fill instant. **It now models the engine** (the fill starts at once inside the
first 42 lines, else at the next tick; the CPU halted 384 µs for it in 16-bit mode; mode 7 waits
for it; mode 0 returns; `GetStat SS.BmClear` reports busy until it has run; an `SS.BmLine` into
the bitmap before its clear has run is an error). With the old build it gives the hardware's
figure: **every logic pass 25 ms (median), over the tick, 5.4 s of 30 spent waiting**.

**The fix (built, host-checked, not yet run on hardware):** `GamLog` arms the clear with wait
mode 0 (`BmArm`, `gfx.a`) and goes on with the logic; the drawing's first step, which always
comes in a later pass (the logic pass leaves it no budget), calls `BmWait` (`GetStat
SS.BmClear` until idle, bounded; on a timeout `NODMA` latches and the CPU clears). The fixed core
lets the CPU run while a fill is pending (the mode-7 note in `grfdrv256.asm`). Start-up's clears
still use mode 7.

| `osrun.py`, 30 s of play | Before (DMA modelled) | After |
|---|---:|---:|
| Logic pass, median | 25.4 ms | 11.2 ms |
| Ticks lost | one a game frame | **0** |
| Game frames a second | (not printed in that run) | **14.6** |
| Checks (text, CLUT, lines; no line before its clear) | pass | pass |

**The first build of it did not start on the K2** (user: "not even a title screen"): `GetStat
SS.BmClear` also returns the DMA's destination in R$Y and R$U (`grfdrv256.asm` `GSBmClear`, a
diagnostic), and `BmWait` did not keep U, the data area, across it. `osrun.py` left R$U alone
for that call, so it missed it; it now returns the driver's diagnostic registers, and `BmWait`
saves Y and U. The rebuilt module passes `osrun.py` and, **in the Wildbits MAME, starts, takes
`5` and `1`, shows the rating screen, and `q` gives the sign-off**. The other grfdrv calls the
program makes were checked for registers they return: none else differs from the model.

**On the K2 (user, 2026-09-23): 1,721 game frames, 6,701 passes in 112 s: 15.4 game frames and
59.8 passes a second** (before: 10.9 and 49.1). 112 s is 6,720 ticks, so 19 lost, within the
sign-off's own error (whole seconds from `F$Time`, ±60 ticks). 3.9 passes a game frame, better
than the model's 4.1: the hardware draws a little faster than `osrun.py` guesses. **Confirmed.**

What was expected: about **60 passes and 13-14 game frames a second**: the hardware's
4.5 passes a game frame, without the lost one (the model's is 4.1). Module on
`l2_wildbitsk2.dsk` (targeted copy, compared). **Untested on hardware.**

### 640×240 on the new core (commit `131a202`, read, not changed)

- **The mode** (the developer's note and the RTL): a plane's bitmap control byte bit 4 (HIRES4)
  makes it 640×240 at 4 bits a dot, high nibble the left dot; bits 7:5 the GROUP, the dot's CLUT
  entry `GROUP × 16 + nibble`; nibble 0 transparent. `$FFCB` bit 0 does it for every plane (not
  wanted: the text plane stays 320). **Same 76,800 bytes a bitmap**, same stride: the port's
  memory, the clear and the text bitmap are unchanged (not 19 blocks, as feared).
- **The line engine** (`LineDraw.v`): in HIRES4 (the target plane's bit 4, or `$FFCB` bit 0)
  X runs 0-639 and each pixel is a **read-modify-write of its nibble** (the colour's low 4 bits).
  The FIFO is still 4,096 pixels, and its full flag is now connected: the walk stalls rather than
  losing pixels. Each hi-res pixel costs an SRAM read and a merge before its write, still only in
  the engine's draw slots, so draining is slower by an unmeasured factor.
- **grfdrv256 already has `SS.BmCfg` ($ED)**: HIRES4 and GROUP per plane. **`SS.BmLine` needs a
  change** (for review, not coded): its range check is fixed at X ≤ 319 (`LD.MaxX`) and its FIFO
  margin at 320 pixels (`LD.Room`); for a HIRES4 target they would become 639 and 640. No layout
  change: the record stays X0, X1, Y0, Y1, colour. With the full flag connected, a line that
  stalls on a full FIFO could also outlast the COMPLETE poll (`LD.Poll`, 200), which then lowers
  GO and drops the rest; the 640 margin avoids that as the 320 one does now.
- **Colours: 16 a plane, 15 visible.** The port's CLUT is colour × 16 + intensity. In 40 s of play
  the game draws only **14 colour/intensity pairs, at intensities 10, 12 and 14** (colour 6/12
  29%, 1/12 20%, 1/10 14%, ...). Two ways: a fixed map (colour RAM index to nibble, intensity
  dropped or 2 levels for the common colours), or a per-frame map of the pairs in use (the attract
  logo's intensity ramp needs more than 15; it would fall back to the nearest). My recommendation:
  the fixed map first, colour index + 1 (colour 15 shares 15), full intensity, and see it.
- **The port's other costs**: `avg.a`'s X scale doubles and its clip becomes 0-639 (the records
  already carry 16-bit X); the record's colour byte becomes the nibble; `ClutCommit` writes 16
  entries. Horizontal runs double in pixels, so a frame's pixels rise by perhaps half, each one an
  RMW: `tline S` (or the sign-off's numbers) on a HIRES4 plane decides whether it is affordable.

### The 640×240 test (branch `hires640`, 2026-09-23) — untested on hardware

User: "let's create a 640 test branch and test 640 and see if it looks better." Built:

- **grfdrv256** (`wb/multiterm`, committed locally, not pushed): `SS.BmLine` reads the target
  plane's HIRES4 bit and allows X to 639 (`LD.MaxX4`) with a 640-pixel FIFO margin
  (`LD.Room4`); a 320 plane is unchanged. On `l2_wildbitsk2.dsk` and the Jr2 image (targeted
  copies, compared).
- **The port** (`HIRES` = 1 in `frame.a`, 0 gives the main build): bitmaps 0 and 1 set by
  `SS.BmCfg` to HIRES4, CLUT 1, group 0 (back to 320 and CLUT 0 on exit); `AvgFlush` converts each
  batch once before `SS.BmLine`, X doubled and the colour byte to nibble colour + 1 (colour 15
  shares 15); `ClutCommit` also writes CLUT 1's entries 1-15, each colour at intensity 12
  (`HIINT`). The interpreter still works in 320, so endpoints land on even 640 columns while the
  lines between are drawn at 640; `avgtest.py` is unaffected. `RECUS` 170 covers the conversion.
- `osrun.py` models `SS.BmCfg`, 4-bit planes, CLUT 1 and 640 pictures: 30 s, **0 ticks lost, 14.2
  game frames a second, every check right**. The Wildbits MAME: starts, `5`, `1`, rating screen,
  `q` exits (no line engine there).
- Unknown until the K2: the engine's speed on a 4-bit plane (each pixel a read-modify-write), and
  whether intensity 12 for everything looks right.

**On the K2 (user, 2026-09-23): it draws, and the photographs show clean 640 lines** (the circle
and the bow-tie wells, the claw, the text in front). **1,463 game frames, 6,472 passes in 108 s:
13.5 game frames a second, no ticks lost** (6,480 ticks). Not comparable with the 320 run's 15.4:
this one includes attract time with the high-score fault below. "Game play feels snappier", but the
attract is slow and **the high score screen keeps clearing and redrawing**.

**The high score screen (fixed, main too; untested on hardware).** Its text list's first entries
are a line that alternates every ~2 s between an 11- and an 8-character message. `TxCommit`
compared the lists index for index, so every entry after it differed: all 148 were erased and
redrawn, 293 glyphs, ~38 ticks (0.6 s) of visible clearing each time. `TxMatch` (`text.a`) now
walks both lists matching in order with an 8-entry look-ahead each way, flagging the changed
entries a bit each (`TXFO`, `TXFN`); the passes then erase and draw only those (and what an erase
touched, as before). In the model's attract: **20 glyphs and ~5.5 ticks a change instead of 293
and 38; every frame's text bitmap checked right**. The match costs about 1.1 ms for 148 entries,
charged as `TXMUS`. A list that has not changed is no longer copied. The high score screen's
first appearance still draws its 148 glyphs, ~21 ticks; the logo's 13 moving texts still redraw
every frame.

**The K2 with the text fix (user, 2026-09-23): 2,246 game frames, 10,390 passes in 173 s: 13.0
game frames a second, no ticks lost** (10,380 ticks, within the sign-off's ±60).

**The fonts at 640 (user: "a little too thick ... don't look crisp like the actual game"; untested
on hardware).** The glyphs were masks rendered at 320 columns, so on a 640 display every vertical
stroke was 2 dots wide. Now the text bitmap is a 640 4-bit plane too (`BmHi` on bitmap 2, CLUT 1,
the lines' 16 colours), `tools/glyphs.py --hires` renders the masks from the vector ROM at 640
columns with 1-dot strokes (16-dot, 2-byte rows, 26-byte records; normal glyphs 8×6 at most, big
14×11), and `TxDraw` doubles an entry's column and writes each dot as a nibble (colour + 1, as
the lines). The rows stay 240, so the small font is still 6 rows tall. `osrun.py` checks the 640
text plane: play and attract, every frame right. `HIRES` = 0 now also needs main's `text.a` and
`glyphs.a`.

**Spacing (user: "the J is right up against the D").** The masks were fine (8 dots wide, 10.07
advance) but a character's column was the beam rounded to 320 and then doubled: the 4.945-column
advance can round to 4, i.e. 8 dots, exactly a glyph's width. With `HIRES`, `avg.a` now writes a
text entry's column in 640ths, round(2x) from the beam's fraction (`AVTX64`; the host tests
assemble without `HIRES` and keep checking the 320 form: `avgtest.py` play capture, 3,481 frames
byte-exact). The top line's E, J, D: columns 333, 343, 353, 2-dot gaps. Play and attract checks
right. The line records still double a 320 endpoint (to do the same for lines: the next step).

**The logo's smear and the copyright line's "shadow" (K2 photographs, 2026-09-23).** The attract
logo is ~700 vectors: the TEMPEST outline repeated at a row or two apart in five colours. MAME's
own frame (`avg_attract.bin` 6861, drawn from Atari's list at 1280×960) shows the copies as
separate outlines; the same frame drawn at 640×240 merges them into exactly the photographed
smear, and `osrun.py`'s picture of the port agrees. **It is the 240 rows, not a fault.** Possible
remedy (a port simplification, the user's call): draw only some of the copies. The copyright line
is clean in the model: dark blue text on black, which a capture device smears most; to be
checked on a direct monitor.

## Small shapes collapsed (2026-09-23, host only) — for review

Built by request and measured. **In the module on branch `hires640`** (`frame.a` sets `AVCOLL`,
beside `HIRES`; without it avg.a assembles as before), on both disk images (targeted copy, copied
back and compared). Untested on hardware. The Wildbits MAME: title, coin, start, the rating
screen, `q` and the sign-off, as before. **The host model** (`osrun.py --seconds 60`, the same
estimates, `RECUS` 170): **13.7 → 14.5 game frames a second**; 166 → 147 records a frame; passes
median 10.6 → 10.4 ms, max 17.7 → 16.9; ticks lost 12 → 13 in 3,600 (the same few passes near the
tick); every check right. The gain follows the records, not the interpreter's 22%: the split frame
charges each record its estimate, whose real cost (~102 µs interpreted, against ~105 before) is
unchanged. Lowering `RECUS` is the separate next step, one change a hardware run.

**The rule** (the specification is `PortAVG(collapse=True)`): a JSRL to one of 20 ROM pictures
(`shape_table`: the game's non-character targets that are only VCTR/SVEC/STAT/JMPL, 9 strokes or
more) is not run when the picture would be drawn under **2 px across**. Instead: a block of its box,
one horizontal record a row, in the CLUT of its **last lit stroke** (it paints on top; the first
stroke's colour and the stroke majority both came out wrong, e.g. $ACA's 9 colour-8 strokes under
8 yellow ones); the beam moves by its net move × Q; the colour and intensity it leaves are set. The
test is a table compare, no multiply: Q < `qmax` = ⌈2·65536 / E⌉ (E the box's larger side, v_eff)
and bs ≤ `bslim` (above it the AVG's clamps change the geometry: bs 5-7). The beam ends exactly
where running the shape leaves it (every captured frame: the records outside collapsed shapes and
the end state are identical).

**Why it pays:** 59% of play's records are dots from enemies deep in the tube, whose 16-45 strokes
round onto 2-3 pixels. Measured first in a prototype (at 1, 2 and 3 px; dot or block): 1 px saves
nothing visible or measurable, a single dot at 2 px visibly loses the enemies, **the block at 2 px
changes 2.7 pixels a play frame** and is hard to tell from the exact picture; 3 px starts to show.

**Built:** `avgview.py` (`shape_walk`, `shape_table`, `--port --collapse`, `--tables` also writes
the table), `avgtab.a` (`AvSTab` 20 × 21 bytes, `AvSMap` 128 bytes, all under `ifdef AVCOLL`),
`avg.a` (`AvShp`, a range check at `_JS2`), `avgtest.py --collapse` (and its fuzz calls the shapes
at every binary scale). Module with `AVCOLL`: **37,662 bytes** of 40,192 (+914); `make pic` clean.

| `avgtest.py`, 8 MHz | Play median | Play 95% | Attract median | Attract 95% | Max |
|---|---:|---:|---:|---:|---:|
| Before | 16.87 ms | 22.10 | 16.97 | 41.89 | 47.28 |
| **`AVCOLL`** | **13.18** | **20.19** | **14.81** | 42.25 | 47.64 |
| `AVCOLL --sw` | 14.43 | 22.61 | 16.19 | 45.43 | 50.82 |

All 6,282 frames byte-exact against the specification (both multiplies); `--fuzz 10000` none failed
(and `--sw --batch 0 --seed 7`), ~29,000 shapes collapsed in each. Play also sends fewer records:
median **129 against 161** (vectors run: 225 against 394), about another 0.8-1 ms of driver at the
guessed 25-30 µs a record. The attract logo costs ~0.36 ms more (its ~135 JSRLs pay the range
check). Found on the way: the first table held three 6-8-stroke pieces the logo calls large
($FC4, $FD1, $FEA: tested 76 times a logo frame, almost never collapsed), which made the logo
1.4-2 ms slower; hence the 9-stroke minimum, the empty-bucket marks and the range check.

**For review:** the look (the prototype's side-by-side crops were sent in the session; `avgview.py
--port --collapse --png DIR --frames N` draws any frame), whether to put `AVCOLL` in the module's
build, and then the budget estimates (`RECUS` a record) the split frame charges, which the faster
records would let come down.

## BmWait removed (2026-09-23, host only) — untested on hardware

The drawing's first step asked `GetStat SS.BmClear` whether the clear `GamLog` armed had run: one
grfdrv call a game frame (~450 µs at Joust's K2 figures), and in the model it never once found the
fill busy. It cannot: `BUDLOG` = 0 puts the drawing in a later tick than the arming, the fill
starts at that tick's vertical blank at the latest, and the DMA halts the CPU until it is done. So
the call went, with its bounded retry and `NODMA` fallback (a fill that fails to *arm* still falls
back to the CPU clear); `frame.a` refuses to assemble with `BUDLOG` other than 0. What would show
if the argument were wrong: old lines left in the picture, not a hang. `osrun.py` 60 s (with
`AVCOLL`): **14.6 game frames a second** (14.5), 5 ticks lost in 3,600 (13), no line drawn before its
clear, every check right. Module 37,614 bytes. The calls a game frame now makes (`osrun.py`):
`SS.LiveKeys` and `SS.Joy` 4 each (one a pass), `SS.BmLine` 2.4, `SS.BmClear` 1, `SS.Layer` (the
flip) 1, `SS.ClutWrite` 0.5.

**On both disk images together with the small-shapes build** (user's call, one hardware run for
both; targeted copy, copied back and compared). The Wildbits MAME: title, coin, start, the rating
screen, `q` and the sign-off.

Also: the program's `SS.DScrn` is now spelled **`SS.MCR`** (`wildbits.d`'s name for the same code;
`SS.Layer` was already used for `$8E`), and `osrun.py` uses both new names. Module byte-identical.

## RECUS 150 (2026-09-23, host only) — prepared for the run after the current one

`RECUS` is the frame loop's estimate of what one line record costs (µs): interpreting it, making it
640, and the driver drawing it. `AvgFlush` charges each `SS.BmLine` batch `records × RECUS +
CALLUS` to the pass's budget, and `NxtBat` sizes the next batch to what the budget still covers.
Too high: passes end with time unused and a game frame takes more of them. Too low: a pass runs
past its tick and loses it (the game's clock, one pass a tick, runs slow). It must stay 129-255
(an 8-bit operand, and `RECK` = 32768/`RECUS` a byte).

The sweep (`osrun.py` 60 s each, with `AVCOLL` and without `BmWait`; the driver's cost guessed):

| `RECUS` | 170 | 160 | 155 | **150** | 140 | 130 |
|---|---:|---:|---:|---:|---:|---:|
| Game frames a second | 14.6 | 14.6 | 14.8 | **15.4** | 15.7 | 16.1 |
| Ticks lost of 3,600 | 5 | 14 | 27 | **44** | 73 | 103 |

**150 is in `frame.a`, committed; NOT on the disk images**, which hold the build before it
(`78acb1e`, under test). What the hardware run says: game frames a second against the run before,
and **passes a second** from the sign-off (60 = no tick lost; the model loses 1.2% at 150, i.e.
~59.3). The model's driver cost is a guess, and the K2 drew faster than it guesses (3.9 passes a
game frame against 4.1), so the hardware may lose fewer. If it loses more than ~1%: 160.

## Hardware: the collapse and BmWait build works (user, 2026-09-23)

`78acb1e` (small shapes collapsed, `BmWait` removed) runs on the K2 (user: "current build
works"; no numbers given). **A new core followed** (user): the line engine's pixel FIFO doubled,
more RAM access time, other optimisations — expected faster. Not yet measured with this port;
the driver's FIFO margin in `SS.BmLine` (640 pixels) could grow with it (a driver change, for review).

## Sound: tsnd, the POKEY image on the SIDs (2026-09-23, host and MAME) — untested on hardware

Plan stage 4, D5 (a). **`src/sound.a`**: `SndInit`, `SndOut` (once a pass), `SndExit`, and **`tsnd`,
the sound test: `tempest s`** (the text screen stays; `0`-`9` `a` `b` `c` start sounds 0-12 through
`FSNDON`, as the game's calls do; `r` plays the sequence; `x` stops; `q` quits). **The game does not
call `SndOut` yet**: the game path is as before but for three trivial lines (the parameter read,
`GFXON`, `SndExit` in `Cleanup`).

**What the FPGA has** (read in `fpga-6809-cores-staging`, not changed): the SIDs are at physical
`$18_8000` = block **`$C4`**: left `+$000`, right `+$100`, and `+$080` ("mono") writes **both**
(`SID_OPL3_Interface.v`: two `sid6581` instances, Gideon Zweijtzer's core). **Two SIDs, six voices,
not the plan's three and nine**; the guide and the plan are corrected. The SID clock is 14.318 MHz
/ 15 = **954,545 Hz**; the SIDs, OPL3 and PSGs are mixed in the FPGA and sent to the codec over I2S
(`SoundChips2DAC_Interface.v`), so no codec input to select for them. Both SIDs are summed to both
channels unless system control bit (`ControlRegisters[1][3]`) says stereo; left alone. The Jr2's
top module wires them the same way. Reached through the service window with `Map1` (`F$MapBlk`),
no absolute address: `SndOut` maps block `$C4` when the text drawing has borrowed the window.

**What Tempest asks of it** (stock MAME, 300 s of the scripted game, every POKEY write logged):
channels sounding at once: 0 34.1%, 1 25.1%, 2 28.1%, 3 11.1%, 4 1.5%, **5 0.1%, never 6**; POKEY
1 channel 4 never. `AUDCTL` always 0 (64 kHz base, no joins, no filters). `AUDC` forms: `$A`
(pure tone) most, `$8` (17-bit noise), and the 5-bit polys `$0`, `$2`, `$6`. **So six voices are
enough, handed out as channels start sounding.**

**The mapping** (POKEY at 12.096 MHz / 8 = 1.512 MHz, base 54,000 Hz): a pure tone becomes a
50% pulse at 27,000 / (`AUDF`+1) Hz (SID frequency 474,555 / (`AUDF`+1), held to `$FFFF`); every
polynomial form becomes SID noise stepped as often as the POKEY samples its polys (SID frequency
59,319 / (`AUDF`+1), one coprocessor divide); the volume becomes the sustain level (attack, decay,
release 0). A SID's envelope does not climb to a raised sustain, so a louder volume, or a new
waveform, re-gates the voice (gate off, 25 µs, gate on): **unchecked on the soft SID**, like the
sustain-down path. The 5-bit polys as plain noise is the roughest approximation.

**Tests:** `tools/sndtest.py` runs `tempest s` on the host, presses `r`, taps every SID write and,
after every pass, checks each sounding channel has one gated voice with the right waveform,
frequency and sustain, and no stray voice: **2,699 passes, 0 wrong**, 1,420 SID writes in 45 s,
136 re-gates. The Wildbits MAME runs `tempest s` (help text, the sequence, `q`) and the game
(title, coin, start, rating screen, sign-off), but **it has no sound at all** (its WAV has no
channels), so the ears are the hardware's. **The reference**: `tools/sndref.lua` plays the same
sequence in stock MAME from the arcade's own RAM (what `FSNDON` writes) — `captures/sndref_arcade.wav`
and a DC-free copy to listen to, `captures/sndref_arcade_listen.wav` (the sequence starts at 10 s:
13 sounds of 2.5 s — cursor, explosion, fire, pulsation, special, dies, thrust tube, thrust space,
enemy shot, enemy line, slam, 3 seconds, pulsar off (silent: it only stops) — then thrust + fire
and pulsation + explosion, 4 s each). Module 38,684 bytes; `make pic` clean. **On both disk
images, with `RECUS` 150** (the game's run of that is the other test on this image).

## Hardware: RECUS 150 on the new core (user, 2026-09-23)

`9b167ec` on the K2 with the new core (doubled line FIFO): **3,429 game frames, 14,597 passes in
245 s: 14.0 game frames and 59.6 passes a second.** 245 s is 14,700 ticks, so ~103 lost (0.7%),
inside the sign-off's own error (whole seconds, ±60 ticks): **`RECUS` 150 holds on hardware** (the
model lost 1.2%). User: "earlier levels definitely felt faster; slight slowdown on later levels as
more enemies added". Not comparable one to one with the 640 build's 13.0 (that run had attract in
it; this one is play into later levels). Two changes in this run (the core and `RECUS`), so the
share of each is not known. `tsnd` not yet reported.

## Sound in the game (2026-09-23, host and MAME) — untested on hardware

`tsnd` on the K2 (user): "sounds good to me" — taken as D5 (a), the SIDs, accepted as it stands.
**The game now plays it**: `SndInit` at start (a failure leaves the game silent), **`SndOut` once
a pass** in the main loop after the virtual IRQs, `SndExit` while paused (hidden terminal) and
`SndInit` on the way back, `SndExit` on every exit.

**The window.** The SIDs share the service window with the text bitmap. The first build thrashed
it: the text's drawing mapped its block, the next pass's `SndOut` mapped `$C4` back, the text
mapped its block again — 412 `F$MapBlk` a minute against 140 without sound. **`SndOut` now waits
while a game frame's drawing is under way and the text holds the window** (`DRAWNG`), so sound is
late by up to a game frame on the few frames whose text changed: 204 a minute.

**The cost** (`osrun.py`, 60 s of play): `SndOut` **145 µs a pass median**, 200 at 95%, 643 at
most (a remap), 8.6 ms a second. It runs outside the drawing's budget, so **`BUDPAS` 12,500 ->
12,300**: ticks lost 45 in 3,600 (44 without sound; 56 before the budget gave way), **15.0 game
frames a second against 15.4 without sound**. `tools/sndtest.py --game` (120 s of play): **6,755
passes checked, 0 wrong**, up to 4 channels at once, 996 re-gates, the SIDs mapped 109 times;
374 passes ended with the text in the window (`SndOut` waited). `tsnd` unchanged (2,699, 0 wrong).
The Wildbits MAME: the game and `tempest s` as before (no sound there). Module 38,714 bytes, on
both disk images.

## Sound slower on hardware; the SIDs through the MMU (2026-09-23) — untested on hardware

**K2, `a125158` (sound in the game): 1,758 game frames, 6,304 passes in 108 s** (user: "definitely
slower with sound on"): 16.3 game frames and **58.4 passes a second, ~176 ticks lost (2.7%)**
against 0.7% the run before (0.7% was 245 s of play; this is 108 s, other levels: not a clean
comparison). The model predicted no extra loss, so something in the sound path costs more on the
hardware than the model thinks; not identified.

**The user's call: reach the SIDs through the MMU directly** — the third absolute-address exception,
`$FFA0`-`$FFAF` (`tools/piccheck.py` knows it). `SidOn`: interrupts masked, `$FFA0` saved and its
edit LUT set to the active one (bits 5-4 = bits 1-0, from `TyVKy2K2x1_MMU_Register.v`), **window
A's slot** saved and given block `$C4`; `SidOff` puts both back and the mask. Window A because only
the main loop uses vector RAM, and `SndOut` is part of it; with interrupts masked no task switch can
reload the MMU. So no `F$MapBlk` for sound at all, no sharing of the service window with the text
(`SndOut` no longer waits for it). Interrupts are masked for `SndOut`'s whole run, ~150 µs a pass
(650 at most, before; less now without the remap). `osrun.py` models the MMU registers and fails a
slot change with interrupts unmasked, in another LUT, or of a slot that is not a window OS-9
mapped, and any os9 call while a window holds another block. **`tempest n`**: the game without
sound, for comparing on one image.

Host: `sndtest.py` 2,699 passes and, `--game`, **7,146 passes (all of them now), 0 wrong**, up to
five channels at once; `osrun.py` 60 s: no errors, `F$MapBlk` back to 140 a minute, 15.0 game
frames a second, 46 ticks lost (the model never charged the remaps much, so it shows no gain). The
Wildbits MAME: `tempest`, `tempest n` and `tempest s` as before. Module 38,792 bytes, on both disk
images. **The run that says which it is: `tempest` and `tempest n`, played alike, sign-offs
compared.**

Considered (user's question): shrinking the module to leave a second free block, so the SIDs and
the text bitmap could both stay mapped. The module would have to fit 4 blocks less 768, 32,000
bytes, against 38,792: 6,800 bytes out, of which the vector ROM (4,096) would have to move into
window A (the plan's fallback), which is full, so the record batch and the text list move into the
data area, also nearly full; and ~2,700 more from tables and code. **Decided (user, 2026-09-23): not
done.** The module stays in 5 blocks; the SIDs stay behind the MMU exception.

## The well: measured, and the layer swap prepared (2026-09-23)

**The well is the display list's sub-list at vector RAM word `$205`: exactly 48 records every play
frame** (16 rim, 16 far, 16 spokes), about 30% of the median frame's 161. Between consecutive
play samples (2,531 pairs): identical 25%, **colours only 63%** (the highlighted lane follows the
player), geometry changed 12% (the zoom between levels). So its shape is fixed 88% of the time.

**The plan (agreed, user 2026-09-23), one hardware run a step:** (1) the text bitmap to the back
layer; (2) the well drawn once into it, its 48 records kept: identical, nothing sent; colours only,
the changed segments redrawn; geometry changed, the back-layer well erased (its old lines in colour
0) and the well drawn with the lines until it settles; (3) text erased over the well redraws the
segments it cut. Estimated 10-15% more game frames in play: ~42-48 records a frame fewer through the
driver and, more, through the budget's `RECUS` charge.

**Step 1, prepared** (on the disk images since the sound comparison, below): `GfxInit` puts tile map 0 (off) on layer 0 in front, the lines on layer 1, **the text
bitmap on layer 2 at the back**. A line crossing text now covers it. `osrun.py` composes its
pictures front to back from the layers as set (it had the text in front hard-coded). `osrun.py`
40 s: every check right, 15.1 game frames a second; the Wildbits MAME: title, coin, start, rating
screen (text shown from the back layer), sign-off. Module 38,792 bytes (unchanged).

## Hardware: sound through the MMU costs nothing measurable (user, 2026-09-23)

`107bf7d` on the K2: **`tempest` 1,599 game frames, 5,754 passes in 97 s** (16.5 and 59.3 a second;
~66 of 5,820 ticks lost, 1.1%); **`tempest n` 2,087 game frames, 8,065 passes in 135 s** (15.5 and
59.7; ~35 of 8,100, 0.4%). The difference is inside the sign-off's error (whole seconds, ±60
ticks); the frame rates follow what was played. The same sound through `F$MapBlk` lost 2.7%
(58.4 passes a second): **mapping the SIDs with `F$MapBlk`, and the service window swapped
between them and the text, cost the hardware far more than the model charges.** The MMU path
stays. **The layer swap (`6371403`) is now on both disk images**, for its own run.

## Hardware: the layer swap works (user, 2026-09-23)

`6371403` on the K2: **2,564 game frames, 10,521 passes in 176 s** (14.6 and 59.8 a second; ~39 of
10,560 ticks lost, 0.4%). The text on the back layer looks right.

## The well cache (2026-09-23, host and MAME) — untested on hardware

**The well is drawn once into the back layer (bitmap 2, with the text) and left there while its
geometry holds.** Atari double-buffers it: `DSPWEL` rebuilds it only when it changes (`ROTDIS`) and
patches its colour `STAT`s every frame; the top-level list always calls the switch `SWWELL`, word
**`$205`**, which jumps into the active buffer.

- **`avg.a` (`AVWELL`)**: while `AV.WENA` is set, the records made inside the JSRL to `$205` (to its
  RTSL; repeated calls add to it) go to window A + `$1E00`, 56 at most (the 56th ends it: an
  overflow, the rest go to the lines); `AV.WNC`, `AV.WOVF`. Captured records take room in the batch
  they are interpreted in (`AV.WCB`), and `AvgFlush` charges them at **`WCBUS` 110 µs** (swept in
  `osrun.py`: 50-90 lost 95-141 ticks a minute, 110-130 lost 17-19, the baseline). **Specified by
  `PortAVG(well=True)`**; `avgtest.py --well`: **6,282 frames byte-exact** (both multiplies), **fuzz
  20,000, 0 failed, 1,764 overflows** (its lists call a well at `$205`, sometimes over 56).
- **`gfx.a` `WellCom`** (after the interpreter, before the flip), against `WLOLD`, the well as in
  the back layer: **same geometry, in the back layer**: the records whose colour is not the back
  layer's (the player's lane, the pulsars' flashes) go with this frame's lines, on top, and the
  line clear takes them away next frame (**the user's idea**: nothing is redrawn in the back layer
  during play); **geometry changed** (the zoom, no well, an overflow): the back-layer well drawn
  in colour 0 (erased), the text redrawn whole (`TXALL`), the well with the lines; **with the
  lines**: after 2 frames (`WSTAB`) of the same geometry it goes into the back layer. Sends ask the
  pass for room first (`WlSend`: `WELUS` 50 µs a record and the call). `AvgFlush`'s loop is now
  `BmSend` (any bitmap, a charge a record).
- **`text.a`**: between its erase and its draw, `WlRows` draws again the well records on the rows
  the erase touched (text erased over the well cut it); `TXALL` marks every row.
- **`osrun.py`**: a model bug found on the way: its `SS.BmLine` drew into a block without first
  taking back what the program had written through a window onto it, so it undid text erases
  (fixed: `sync_out` first; on the F256 it is one memory). **New check, every frame**: the text
  bitmap holds exactly the text and, when cached, `WLOLD`'s lines (any of their colours where a
  glyph and the well, or two well records, meet), nothing else; the well's records not in the back
  layer's colour, or all of them when not cached, are among the line layer's records.

**Results** (`osrun.py` 120 s): every check right; **15.0 game frames a second**, 20 ticks lost in
7,200; line records a frame 147 -> ~110; the well in the back layer ~75% of game frames. **The
frame rate does not move in the model**: a game frame is a logic pass and then drawing passes,
whole ticks each; the drawing still needs two passes (its estimate ~15 ms against the pass's 12.3),
so frames stay at ~3 ticks. The gain arrives when a frame's drawing fits one pass; the hardware draws
faster than the model guesses, so the K2 may see it where the model does not. `sndtest.py --game`
90 s: 5,377 passes, 0 wrong. The Wildbits MAME: the game and `tempest s`. **Module 39,663 bytes of
40,192 (529 left).** On both disk images.

## The line FIFO doubled (2026-09-24) — the driver change prepared, not installed

The FPGA developer doubled the line engine's pixel FIFO to 8,192 (user: confirmed). `SS.BmLine`
stops a batch when the FIFO's count passes `LD.Room4` = `LD.Depth` - 640 and returns short; each
short return costs us a whole extra call (~450 µs). The driver had `LD.Depth` 4,096 built in, so it
used half the new FIFO. **NitrOS-9 `wb/multiterm` (committed locally, not pushed): `LD.Depth` 8,192**
(`defs/wildbits.d`; the built `grfdrv256` differs in the two room constants and the CRC; both
platforms' builds of the old source were first checked identical to the drivers on the images).
**Not on the disk images yet**, so that one run measures the old driver and the next the new.

**The measure: the sign-off's second line, "LLLLL line calls, KKKKK short"** (`BmSend` counts each
`SS.BmLine` call and each that came back short; `osrun.py`'s driver never runs short, so it
reads 0 there). On both disk images with the well cache (module 39,764 bytes, 428 left).

## Hardware: the well cache, first run (user, 2026-09-24)

`2c1701f` on the K2 (the well cache, the old 4,096 driver): **3,675 game frames, 17,958 passes in
299 s: 12.3 game frames and 60.1 passes a second, no tick lost.** Below the earlier runs' 14.0-16.5,
but those were other lengths and levels; not a clean comparison. User: "every time we change
something we get slower ... are we still calculating [the well]?" **Yes: only its drawing left the
loop.** The interpreter still runs its sub-list every frame and the budget charges it 48 x
`WCBUS` 110 µs, ~5.3 ms (it was 48 x `RECUS` 150, ~7.2 ms); and the records not in the back layer's
colour (the player's lane, most frames) go in **a call of their own**: in the Wildbits MAME (call
counts are logic, not timing) 1,800 `SS.BmLine` calls in 29 s against 1,169 with the cache off,
~55% more, at ~450 µs each on the K2. So the cache as built may well cost more than it saves.

**`tempest w`**: the game with the cache off (`AV.WENA` 0; the well with the lines, as before), for
a comparison on one image. On both disk images (module 39,772 bytes).

**The fix, proposed**: take the well out of the loop for real. Keep the well sub-list's bytes and
the interpreter's state after it; when the bytes are unchanged (Atari rebuilds the well only when
its shape changes, `ROTDIS`), do not run it at all: restore that state and charge nothing; when only
its colour `STAT`s changed, run it as now. And put the off-colour records in the frame's batch, not a
call of their own.

## The well out of the loop (2026-09-24, host and MAME) — untested on hardware

User: "Don't we know when the well changes? ... take the well out of the loop for real"; "why not just
change it when the level changes?"; "the highlighted lane ... should just be added to the array for
the one call". **Atari rebuilds the well only when its shape changes, into the spare buffer, and
then switches SWWELL's jump to it**, so SWWELL's word changing is the well changing: no checksum.
The captures: SWWELL always jumps to `$206` or `$2A7`; each buffer is one straight run (a `CNTR`, a
`SCAL`, 49-66 vectors, 17 colour STATs, `RTSL`), no jump elsewhere. The user's CLUT idea
(recolouring by CLUT, not by drawing) does not fit: the 640 planes have 16 colour indices, shared
with the text, and the well has 16 lanes and 48 segments.

- **`avg.a`**: at the frame's first call into the well, **if SWWELL's word, and the colour and
  intensity it is entered with, are the cache's, the well is not run**: the cached records at
  window A + `$1E00`, each recoloured from the colour word it was drawn in (a captured record's
  byte 7: the word offset from the buffer, `$FF` none), and the interpreter's state as the well
  left it (beam, Q, scales, colour from its last colour word, intensity, the dot rule's last
  record). A call run whole and returned from is the cache; an overflow, or the list ending inside
  it, forgets it. Nothing is charged for a skipped well. **`AvLast`**: before the list's last batch
  is sent, the platform's `AvgLast` may add records to it.
- **`gfx.a`**: `AvgLast` puts the well's records not in the back layer's colour (the player's
  lane) **into that last batch: no call of their own**; `WellCom` does the rest after the flush.
- **Checked**: `PortAVG(well=True)` specifies it, cache and all. On the frame-by-frame capture
  (`captures/avg_play_every.bin`, 120 s of play from stock MAME, every video frame) the skip gives
  **exactly** what running the well whole does in all 6,602 frames (3,870 skipped); on the sampled
  captures it does not always (436 of 3,481: the game rebuilt twice between samples, back to the
  same buffer; the port sees every game frame). `avgtest.py --well`: **6,282 frames exact** (both
  multiplies; the well skipped in 3,609), **the frame-by-frame capture 6,602 exact** (3,464 skipped;
  its 36 power-up frames fail with or without the well: vector RAM before the game wrote it, which
  the specification leaves open), **fuzz 20,000, 0 failed** (3,390 skips: a rig's last list again,
  some colour words changed; 1,617 overflows). The interpreter: **median 13.5 -> 11.1 ms** on the
  captures, 10.0 frame by frame.
- **`osrun.py` 120 s: 16.9 game frames a second (15.0 before)**, median 2.5 ticks a game frame (3.1),
  43 ticks lost in 7,200, every check right. `sndtest.py`: game 3,557 and tsnd 2,699 passes, 0 wrong.
  The Wildbits MAME (call counts): **839 `SS.BmLine` calls in 29 s**, against 1,201 with `tempest w`
  and 1,800 for the build before. **Module 40,178 bytes of 40,192: 14 left** (tsnd's help is one
  line now). On both disk images.

## Hardware: the well out of the loop (user, 2026-09-24)

`4794628` on the K2: **1,594 game frames, 5,383 passes in 89 s: 17.9 game frames and 60.5 passes a
second** (no tick lost), **3,151 line calls, 0 short**: the best run yet (12.3-16.5 before; other
levels, so `tempest w` on this image is the clean comparison, not yet run). **2.0 `SS.BmLine` calls
a game frame, and none came back short** even with the 4,096 driver: no frame's batch fills its
room, so **the 8,192 driver change (`c45760ab`, local) would gain nothing now**; it stays off the
images and unpushed unless short returns appear.

**`tempest w` on the same image** (the well run every frame): **2,524 game frames, 11,737 passes in
196 s: 12.9 game frames and 59.9 passes a second; 7,256 line calls, 0 short.** Against `tempest`:
**4.7 passes a game frame against 3.4, 2.9 line calls a game frame against 2.0**. The runs' lengths
differ (196 s reaches heavier levels than 89 s), but a game frame is a tick shorter and a call
lighter: **the well out of the loop is worth ~35-40% more game frames on the K2.**

## The 8,192 driver installed; `w` removed (2026-09-24)

User: "take out the w switch ... If the fifo has 8192, let's let the driver use it." **`grfdrv256`
with `LD.Depth` 8,192 (`c45760ab`, still unpushed) is on both disk images** (rebuilt for each
platform, identical to the builds compared before, targeted copy, copied back and compared); the
Wildbits MAME boots it and runs the game. **`tempest w` is gone** (module 40,170 bytes).

**Where the space went this session** (36,748 -> 40,170, file by file against `ec48bdf`): the well
cache ~1,450 (`avg.a` capture, skip and cache; `gfx.a` `WellCom`, `WlRows`, `AvgLast`, `BmSend`;
`text.a` hooks), the small-shape collapse ~900 (`AvShp` and its table), the SID output ~450,
`tsnd` ~450, the sign-off's second line and the switches ~100; `BmWait` -48. **Cleanup candidates**:
`tsnd` behind a build switch (~450), the `n` switch (~10), `AvgFlush` converting with `WlCv1`
(~30), `AvShp`'s repeated range check (~8), the shape map at half the resolution (~64), the
sign-off's second line (~100).

## Cleanup 1-4 (2026-09-24, host and MAME)

User: "do 1 through 4". **Module 40,170 -> 39,746 bytes (446 free).**
1. **`tsnd` only in a `TSND` build** (`make EXTRA="-DTSND"`, 40,134 bytes: it still fits):
   `TsMain` and its tables, and the start-up's parameter read. `tools/sndtest.py` assembles its own
   `TSND` module into `src/build/` (the makefile's command) and leaves `src/tempest` alone;
   `--game` runs `src/tempest`. (The routine was `Tsnd`: lwasm's case folding made it `TSND`.)
2. **`tempest n` gone** (sound is settled).
3. **`AvgFlush` converts its batch with `WlCv1`**, in place (now outside `AVWELL`).
4. **`AvShp` no longer repeats the range check `_JS2` made.**

Checked: `avgtest.py --collapse --well` 6,282 frames exact, fuzz 10,000 (both multiplies, random
batches) 0 failed; `osrun.py` 60 s 16.3 game frames a second, every check right; `sndtest.py` tsnd
2,699 and game 3,542 passes, 0 wrong; the Wildbits MAME: the game and its sign-off. On both disk
images (with the 8,192 driver).

## Hardware: the cleaned build with the 8,192 driver (user, 2026-09-24)

`a1930b6` on the K2: **3,707 game frames, 15,263 passes in 254 s: 14.6 game frames and 60.1 passes
a second; 9,563 line calls, 0 short** (4.1 passes and 2.6 calls a game frame). Between the cached
89 s run (17.9; 3.4 and 2.0) and `tempest w`'s 196 s (12.9; 4.7 and 2.9): **play runs of different
lengths reach different levels, so they cannot rank builds.** Proposed from now on: **an attract-mode
benchmark** (start, no coin, 2 minutes, `q`), the same sequence every time, beside play for the feel.

## The stick only when used; BUDPAS 12,600; RECUS stays (2026-09-24, host and MAME)

User: "1 and 2" (the stick; re-tune `RECUS`). **`input.a`**: stick 0 (`SS.Joy`, ~400 µs a call)
is read every pass only once it has shown a direction or a button (`JOYON`); until then, one look
every `JOYLOOK` = 30 passes (half a second: a stick player's first push is noticed within that).
`osrun.py`: GetStat calls 3,560 -> 1,825 in 30 s. **The time it frees goes to the drawing's budget:
`BUDPAS` 12,300 -> 12,600.** The sweep (`osrun.py` 60 s each):

| `BUDPAS` / `RECUS` | 12,300/150 | **12,600/150** | 12,300/140 | 12,600/140 | 12,300/130 | 12,600/130 |
|---|---:|---:|---:|---:|---:|---:|
| Game frames a second | 16.5 | **17.1** | 16.7 | 17.0 | 16.4 | 16.8 |
| Ticks lost of 3,600 | 43 | **75** | 125 | 136 | 256 | 351 |

**`RECUS` stays at 150**: lower only loses ticks now. With the well out of the loop the records
left are the costly ones (dots, shapes, enemies), so 150 µs is about their real cost, not a margin.
The model has always lost more ticks than the K2 (1.2% there, none on the hardware). Module 39,773
bytes. On both disk images; the Wildbits MAME: the game and its sign-off (keyboard only there: the
stick path waits for the K2). Two changes in one run, at the user's asking.

## The attract baseline on the K2; the logo's drawings dropped (2026-09-24)

**The attract benchmark on the K2** (`d975bb5`, the stick only when used, `BUDPAS` 12,600): **2
minutes of attract (125 s by the sign-off): 1,780 game frames, 7,345 passes: 14.2 game frames and
58.8 passes a second (~155 ticks lost, 2%); 4,572 line calls (2.6 a game frame), 0 short.** The
baseline for later builds.

**The logo** (user: "the Tempest marquee on the title screen draws really slow"): the zoom draws
**19 copies of the logo** (its trail), six ROM pieces 19 times each, **646 records a drawing** for
~10 s of the arcade's zoom; ~47 ms of interpreting alone, 5-6 passes a drawing, while its logic is
one pass, and the game waits for each drawing. **A drawing that took `SKIPT` = 5 passes or more
drops the next game frame's drawing** (its logic runs; the well's cache is forgotten, since the
well may be rebuilt twice unseen). Play's drawings take 2-3 passes, so play is not touched. The
user asked why the marquee is several `SS.BmLine` calls, not one: each call is a pass's worth
(the budget), and the driver takes 255 records a call at most; one call would mean the whole
logo interpreted first (~47 ms, three ticks without yielding), and the calls are ~3.6 ms of a
~70 ms drawing. **`GFRAMS` now counts the game's frames** (its logic), drawn or dropped, and the
sign-off's second line says the drawings dropped.

`osrun.py`, 200 s of attract (no keys): **each logo zoom 1,081 ticks (18 s) before, 707 (11.8 s)
now: 1.5x faster**, 55 drawings instead of 110; all of attract 12.5 -> 13.6 game frames a second;
every check right. (The model's attract loses ~1,800 ticks in 200 s either way, against 2% on the
K2: it charges the text screens more than the hardware costs.) The arcade's zoom is ~4 s:
dropping two of three drawings when a drawing is very long would go further, choppier. Module
39,851 bytes; on both disk images; the Wildbits MAME: the game and the new sign-off.

## The SOL clock: lost ticks caught up (2026-09-24, host and MAME) — untested on hardware

User: "Why do we care if it loses that tick?" (a lost pass is game time lost: timers, sound
tempo, the frame pace), then "Then we can hook up the sol driver and get a signal for each tick?"
and "you can mute the signal during a game pause". **This reverses 2026-09-23's choice** (section
6.3 of the plan: SOLdrv weighed and not taken). SOLdrv and `/fSOL` are in the boot file; `scfg`
uses them the same way.

- **`platform.a` `SolOn`**: `/fSOL`, `SS.SOLIRQ` ($C3) with line 0 (the frame's first line, the
  tick) and signal `SIGTK` = $A2; `Icpt` counts `TICKS`. **`frame.a` `MainLoop`**: the ticks since
  the last pass (`TKMAX` 8 at most) run their virtual IRQs and go to `InFram`; none yet: `F$Sleep`
  0 until a signal. So **a pass that runs long is caught up, not lost**, as the arcade's IRQ keeps
  real time whatever the AVG does. No `/fSOL` (or an error): one pass a tick, as before.
  **`PausWt`** mutes it (`SS.SOLMUTE` $C4) and, coming back, takes the ticks from then. `SolOff` on
  every exit.
- **`osrun.py` models SOLdrv**: `/fSOL`, the two calls, a signal a tick taken at the next os9 call
  (150 µs guessed), `F$Sleep` 0 to the next tick. Every check right; **virtual IRQs 245.9 a
  second** (the arcade's 246.1) whatever the passes do.
- **The budget, swept with the clock in** (`osrun.py` 90 s): 11,000 16.0 game frames a second,
  11,800 15.8, **12,600 17.7**, 13,400 17.4, 14,200 16.4, 15,000 16.0, **30,000 (no split) 19.5**
  (longest pass 162 ms: the logo). Game time holds (245.8-245.9) in all. So the budget no longer
  guards the clock: **it is a trade of smoothness** (sound, controls and the game's IRQs every tick)
  against frames (+10% with no split).
- **Both on the disk images, for the user to judge by feel**: `tempest` (the SOL clock, `BUDPAS`
  12,600, 40,068 bytes) and **`tempnb`** (the same with `BUDPAS` 30,000 and the module name
  `tempnb`: `make EXTRA="-DMODNB -DBUDPAS=30000"`). The Wildbits MAME delivers the signal:
  **572 game frames in 29 s against ~414 before** (the slow clock seen there in the first session
  was lost ticks), `tempnb` 586 with 733 line calls against 1,379. If `tempnb` feels as good, the
  budget trackers (`Spend`, `RECUS`, `WCBUS`, the batch sizing) can go, and their space with them.

## Hardware: the SOL clock, `tempest` (user, 2026-09-24)

`cb0ed48` `tempest` (the SOL clock, `BUDPAS` 12,600) on the K2: **2,882 game frames, 10,640 passes
in 178 s: 16.2 game frames and 59.8 passes a second; 6,391 line calls (2.2 a game frame), 0 short,
214 drawings dropped** (7% of game frames: the logo, or play's heaviest). Passes under 60 no
longer mean lost time. `tempnb` not yet reported.

## No split: the budget machinery removed (2026-09-24, host and MAME)

**`tempnb` on the K2 (user): "significantly better". 5,608 game frames, 16,360 passes in 276 s:
20.3 game frames a second; 7,574 line calls (1.35 a game frame), 0 short, 7 dropped**, against
`tempest`'s 16.2 in 178 s. So **a game frame is now two passes: the logic, then the drawing whole**
(`frame.a`: `DRPEND` says a frame's logic ran; the next pass, a tick on, draws it, so the clear
armed in the logic pass has run). **Removed**: the drawing coroutine and its 384-byte stack
(`DrwBeg`, `DrwRes`, `DRWSTK`), `Spend`, `WORK`, `BUDPAS`, `BUDLOG`, `NxtBat` (batches are 255 again),
`WlSend`, `TxSpnd`, and every estimate (`RECUS`, `WCBUS`, `WELUS`, `CALLUS`, `GLYUS`, `ROWUS`,
`TXMUS`, `FLIPUS`, `MINBUS`, `MINREC`, `RECK`). The drop rule counts ticks now (`SKIPT` 5 ticks of
drawing drop the next); `TKMAX` 32 (a superzapper blast is one pass of up to ~250 ms: 350-1,062
records). avg.a is unchanged (its `AV.WCB` room still counts the well's records against their
batch: harmless at 255). **Module 39,826 bytes (366 free).**

`osrun.py` 85 s: **20.1 game frames a second, virtual IRQs 245.8 a second**, every check right;
`sndtest.py` (now checking at either sleep) game 1,990 and tsnd 2,699 passes, 0 wrong; the Wildbits
MAME: 589 game frames in 29 s, 696 line calls. **On both disk images as `tempest`; `tempnb` removed
from them.**

## Hardware: no split, the cleaned build (user, 2026-09-24)

`0496149` on the K2: **4,230 game frames, 11,601 passes in 214 s: 19.8 game frames a second**
(54.2 passes a second: long drawings are one pass now, their ticks caught up); **5,263 line calls
(1.24 a game frame), 0 short, 5 dropped.** As `tempnb` (20.3 in 276 s), within play's spread.

**The title zoom** (`osrun.py`, 200 s of attract): **550 ticks (9.2 s) a zoom, 103 of its 110
frames drawn** (a logo drawing is now one pass of ~4-5 ticks and seldom reaches `SKIPT`), against
707 (11.8 s, 55 drawn) with the split and drops, and 1,081 (18.0 s) at first: **~2x the original**;
all of attract 17.8 game frames a second (13.6). The arcade's is ~4 s; a lower `SKIPT` would go
faster, choppier, and would drop in play's heaviest moments too.

## The logo's trail thinned (2026-09-24, host and MAME) — untested on hardware

User: "Logo looks faster, but it would be nice to make it even faster. What if we removed every
third TEMPEST or every fourth one". The trail is the list at `$101`: per copy a `SCAL`, a colour,
and **`JSRL $FA7`**, the whole logo in ROM, which **starts with a `CNTR`**; after the last copy the
list does its own `CNTR` and `SCAL`. So a copy skipped leaves the rest untouched. **`avg.a`
`LOGSKP`**: every `LOGSKP`-th call to `$FA7` in a frame is not run (a counter in the page, `AV.LGK`,
reset by `AvgRun`); **`frame.a` sets 4** (15 of 19 copies drawn). `PortAVG(logskip=N)` specifies
it; `avgtest.py --logskip 4`: attract 2,801 frames exact, fuzz 2,000 (lists call `$FA7` too)
clean; the worst attract frame 48.7 -> 39.1 ms. Records a logo frame 646 -> 510 (every 3rd: 442).
Pictures side by side: the trail still reads as one, a little sparser.

`osrun.py` 200 s of attract, **per logo frame: 5.3 ticks (all copies), 4.4 (every 4th skipped,
17% faster), 4.1 (every 3rd, 24%)**; a whole zoom ~9.8 s -> ~8.2 s (every 3rd ~7.4 s). The frame's
fixed costs (the logic pass, the text, the flip) keep the gain below the records cut. Every 3rd is
`LOGSKP` 3. The game (`osrun.py` 40 s): 20.1 game frames a second, every check right. Module
39,852 bytes; on both disk images; the Wildbits MAME: the game and its sign-off.

**Then `LOGSKP` 2** (user: "Let's skip every other one"): 10 of the 19 copies drawn, **306 records
a logo frame (612 whole)**; the trail sparser, some colour bands gone, still a trail.
`avgtest.py --logskip 2`: attract 2,801 frames exact, fuzz 1,000 clean. On both disk images; the
Wildbits MAME: the game and its sign-off.

## The logo's quiet end shortened (2026-09-24, host and MAME) — untested on hardware

User: the final phase is slow "as the multiple tempests merge together"; "Can we do something about
the quiet phase? The zoom looks good up to that point." Measured in the arcade capture: the zoom
ends at video frame ~2121; then **the merge** (to ~2196, 1.25 s: the trail's copies vanish one
every 2 game frames) and **a hold** (to ~2328, 2.2 s: the logo still). Atari's `LOGPRO` (ALSCO2):
the front copy steps 1 a frame to its destination (`NEARY` below `$30`), the trail's end (`FARY`)
1 a frame after it; the whole logo is `QTMPAUS` = 223 game frames (state `CPAUSE`, `PSCALE` 0: one
a frame), so on the port it stretches with the frame rate. **The port's `LOGPRO`, with
`LOGOQK` (set in `frame.a`, so the translation tests still build Atari's code)**: once the front
has arrived, the trail closes `LOGMS` = 4 a frame; once merged, `QTMPAUS` is held to `LOGHD` = 27
frames at most. The zoom itself is untouched. `osrun.py` (130 s of attract, the logo display
state `$14`): **635 ticks (10.6 s) -> 475 (7.9 s)**. `xlattest.py --src -n 40` byte-exact. Module
39,884 bytes; on both disk images; the Wildbits MAME: the game and its sign-off.

**The hold lengthened (2026-09-24, host and MAME) — untested on hardware.** User, on the K2: "That
looks a ton better. Could probably hold for about 3 seconds longer at the end." A cap could not do
it (Atari's `QTMPAUS` has only ~80 frames left at the merge), so the port now **sets** `QTMPAUS` to
`LOGHD` once, on the frame the trail closes on the arrived front (`FARY` changes to `NEARY`, below
`$30`). `LOGHD` 90: the hold runs ~21 game frames a second in the model, so 63 more frames = 3 s.
`osrun.py` logo state: **475 ticks -> 655 (10.9 s)**. Module 39,888 bytes; on both disk images; the
Wildbits MAME: the game and its sign-off.

## Open items

1. The line-engine holes (FPGA developer).
2. `tline` for stage 1, when the core is fixed: above all the per-record cost.
3. `SS.MsDelta` storage (5 bytes of vtio statics, 242 → 247 of 256), and its driver code.
4. The frame rate of the split loop (14 a second in the model); the lost tick a game frame on the
   K2 and the slow clock in MAME: the clear's wait for vertical blank, fixed and confirmed on the
   K2, 15.4 game frames a second ("Optimising").
5. The coprocessor divide's read-after-write timing, and its remainder, on hardware (D6 pilot,
   "Unchecked"; `DIVF` reads the remainder). Now also the multiplier's (`avg.a`, approved).
6. The hardware half: the module itself can now be the first picture (`make install DSK=`, the
   K2 image) once the core is fixed, photographed against `tools/osrun.py --png` and
   `avgview.py --port --png`; `avgplay` (captured frames) remains the narrower test.
7. The encoder's rate and direction on the keys, stick and mouse: by feel, against MAME.
