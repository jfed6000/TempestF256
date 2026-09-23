# Plan: Tempest on NitrOS-9 Level 2, Wildbits F256 (K2 and Jr2)

*Written 2026-09-22, after the survey in `docs/port-tempest.md`. For review: **nothing is built, and no
game code is written until this plan is approved.** Decisions marked **(yours)** need an answer; each has
a recommendation. New and changed `SS` call layouts are in section 6, proposed and not coded.*

## What the port is, in one paragraph

Atari's Tempest, Rev 3 (the source's "2A(alt)"), translated from 6502 to position-independent 6809 as
one OS-9 program module. **The game logic and Atari's own display-list building stay**, translated
routine by routine with their labels. **The Analog Vector Generator is replaced by a 6809 interpreter**
that walks the display list once per game frame and hands the visible vectors to the rc16's line engine
through `SS.BmLine`, drawing into a hidden bitmap that is cleared by `SS.BmClear` and shown by
`SS.Layer`. **The Math Box's one divide goes to the integer coprocessor.** **The POKEYs are replaced by
a register image** that Atari's sound interpreter writes and an output stage plays. **The spinner is a
signed count per game frame**, from whatever the control turns out to be. The game runs at the arcade's
own pace, a frame per nine 246 Hz IRQs, emulated on the 60 Hz tick.

## 1. Architecture

Joust's three sections, unchanged in shape (guide section 1):

| Section | Contents | Source |
|---|---|---|
| Program module | Game logic (`ALEXEC`, `ALWELG`, `ALSCO2`, `ALLANG`, `ALCOIN`) and the platform layer (start-up, frame loop, input, pause, lockdown, exit, settings file) | Translated; `platform.a` ported from Joust |
| Graphics | Display-list build (`ALDIS2`, `ALVGUT`, `ALVROM`) → **AVG interpreter** → line records → `SS.BmLine`; clear, flip, CLUT | Build translated; interpreter new |
| Sound | `ALSOUN` → POKEY register image → output stage | Interpreter translated verbatim; output stage new |

**The three seams**, which `docs/interfaces.md` will write down with every call site (stage 5):

1. **Display: the AVG display list.** The game writes AVG instructions into "vector RAM" exactly as it
   does on the arcade; everything downstream of the list is ours. Chosen over intercepting the
   `ALVGUT` calls because much of `ALDIS2` stores straight into the list (`STA NY,VGLIST`), and because
   the list can be captured from MAME and rendered on the host by the same interpreter — the instrument
   (section 4, stage 0).
2. **Sound: the POKEY register image**, 8 × (`AUDF`, `AUDC`) + `AUDCTL`, written by `MODSND`.
3. **Input: `TBHD`** (signed spinner counts, added to, consumed and zeroed by `MOVCUR`) and the switch
   bytes `SWSTAT`/`SWFINA`, filled by the platform layer where the IRQ filled them.

## 2. The frame loop

```
F$Sleep X=2            wait for the 60 Hz tick
VirtIRQ                add 246.1/60 to the virtual IRQ count (Bresenham, no division);
                       for each whole virtual IRQ: MODSND, FRTIMR++, the clocks
Input                  one SS.LiveKeys (+ spinner read) -> TBHD, switch bytes
if FRTIMR >= 9:        FRTIMR = 0  (the arcade's MAINLN rule, ALEXEC:45)
    EXSTAT, NONSTA     one game frame
    DISPLAY            rebuild the changed sub-lists
    AvgRun             interpret the list -> line records
    Draw               SS.BmClear hidden, SS.BmLine records -> hidden, SS.Layer flip
SndOut                 register image -> sound chip(s)
CLUT commit            SS.ClutWrite if colour RAM changed
```

Game frames take 2 or 3 ticks (36.6 ms target); a frame whose work overruns simply takes longer, as on
the arcade. The clear sits right after the tick so it arms inside the blanking window — **if**
measurement confirms the fill still waits for that window (port-tempest 4.2). The order of clear, draw
and flip within a game frame, and whether a third bitmap is needed, is decision D9.

## 3. Memory

**Logical space** (guide section 3): eight 8K blocks, shared by the module, the data area and windows.

| Use | Blocks | Held |
|---|---:|---|
| Data area: arcade RAM (2K, page for page), platform variables, record buffer, stack | 1 | always |
| Window A: "vector RAM" (4K) and the line-record buffer | 1 | always — the game writes it every frame, and a map/unmap pair is 436 µs |
| Window B: the sound page `$C4`, if D5 picks a `$C4` chip | 1 | always, for the same reason |
| **Module** | **5** | 40,192 bytes, Joust's budget |

Vector ROM (4K of pictures and characters) goes **in the module**: the interpreter reads it on every
`JSRL`, and PC-relative data costs no window. If the module outgrows the budget, the fallback is to put
the ROM image in window A's block beside vector RAM (4K + 4K fills it) and move the record buffer into
the data area, which leaves room for about 500 records. The pilot's size ratio decides (D6).

**Addresses in the list are the arcade's.** `JSRL`/`JMPL` targets are AVG word addresses into
`$2000`-`$3FFF`; the interpreter maps `$2xxx` to window A and `$3xxx` to the module's copy of the ROM. On
the CPU side, the handful of tables that hold `$2xxx` pointers (`BUFASL`/`BUFBSL`/`BUFSWL` and kin, next
to `SBCLOG`) are relocated once at start-up, Joust's `reloc.a` way.

**Physical memory:** two bitmaps of ten blocks each (three, if D9 says so) from one `SS.GfxAlloc`, and
one block for window A.

## 4. Stages

Each stage ends with a number or a photograph, written into `docs/status.md`. Hardware stages list
exactly what to run.

### Stage 0 — host tooling and the load (no hardware)

- **`tools/m65parse.py`**: read MAC65 + HLL65 (sections, labels, macros, `.IF` fences) into a symbol and
  line model. The translator (D6) and every checker build on it.
- **`tools/avgcap.lua`**: a Lua `-autoboot_script` for stock MAME (0.276, installed, unmodified), running
  `tempest` from `tempest_orig/notebooks/roms`: on each game frame dump vector RAM (`$2000`-`$2FFF`) and
  colour RAM; log POKEY writes with their IRQ number; log `TBHD` per frame.
- **`tools/avgview.py`**: the **host AVG interpreter**. Renders a capture to a 320×240 PNG through the
  same mapping, clipping and CLUT the 6809 version will use; reports lines, pixels and the longest line
  per frame. It is the executable specification of the 6809 interpreter, and its output is what every
  hardware photograph is compared with.
- **The numbers:** lines and pixels per frame over attract mode and a played game — the load that stage 1
  must carry. Also the 6502's busy fraction per game frame (how long `MAINLN` waits on `FRTIMR`), which
  bounds the translated game's CPU time.
- Put the rendered frames next to MAME's own screenshots of the same moments. **Check this stage's
  mapping (port-tempest 4.4) here**, before anything depends on it.

### Stage 1 — the line engine and the clear, on hardware

First, **bmtest's `F` key on the K2** (the flood case: 255 full-width lines; the pass is a drawn count
below 255 with no error). Then a Tempest harness, **`tline`**, in this repo, each key one measurement:

| Key | Measures |
|---|---|
| `D` | **Drain rate**: queue ~4,000 pixels, then read `GetStat SS.BmLine` back to back; pixels per call interval |
| `V` | **Volume**: draw stage 0's worst captured frame (as records, from a file) every game frame for 600 frames; frames that did not finish |
| `S` | **Slope**: `SS.BmLine` at 1, 16, 64, 255 short records, ssbench-style; µs fixed + µs a record |
| `C` | **Clear timing**: `SS.BmClear` mode 7 at arming lines spread over the frame (`R$A` reports the line it got); wall clock per call |
| `F` | **Flip**: alternate two bitmaps with `SS.Layer` every tick under a moving bar; tearing or not |

Then the same on the **Jr2** once it has the fixed core. These five numbers decide D9 and whether the
`SS.BmLine` changes in section 6 are worth making.

### Stage 2 — the interpreter on the machine: `avgplay`

The 6809 AVG interpreter, playing stage 0's captured frames from a file at the game's rate. The first
real picture, checked against `avgview`'s PNG of the same frame; then timed. Proves the interpreter,
the mapping, the CLUT, the clipping and the draw path before any game code exists.

### Stage 3 — the spinner: `tspin`

Depends on D4. Prints counts per frame, direction, and counts per turn; confirms nothing is lost at 60 Hz
and nothing sticks at an edge. The keyboard/stick fallback is tested here too.

### Stage 4 — sound: `tsnd`

`ALSOUN` translated and driving the register image; the chosen output stage (D5). Fires each of the 13
sounds and the combinations the game makes (fire over thrust, pulsation over explosions). Compared by ear
with `mame -wavwrite` recordings of the same sounds. **Settle D5 here**, before the game depends on it.

### Stage 5 — `docs/interfaces.md`

The three seams, every call site, with stage 1-4's numbers in them.

### Stage 6 — the skeleton

Data area, window A, bitmaps, CLUT, the frame loop of section 2, `SS.WSig` pause, lockdown, clean exit —
ported from Joust's `src/platform.a`. Build targets from day one: `budget`, `pic` (Joust's
`tools/piccheck.py`), the case-folded duplicate-label scan.

### Stage 7 — the game, in parts

Each part is confirmed against MAME before the next begins; each has a screen to compare.

| Part | Files | Checked against |
|---|---|---|
| a. Executive, list utilities, text | `ALEXEC`, `ALVGUT`, `ALLANG`, `INFO` in `ALSCO2` | Attract: the high-score ladder and credits screens |
| b. The well and projection | `ALDIS2` well, `CASCAL`, `WORSCR`, colours | Attract: the level-select and the well fly-in |
| c. Player | `MOVCUR`, charges, superzapper | Play: the claw moving round each well shape |
| d. Enemies | `ALWELG` nymphs/invaders, cam tables | Play, wave by wave |
| e. Explosions, death, drop mode, star field | `ALWELG`, `ALDIS2` | The end-of-wave drop (the clipping test) |
| f. Scoring, bonuses, high-score entry, settings file | `ALSCO2`, `ALEARO` replacement, coin | A whole game, twice in a row |

Every translated routine gets the **differential test** of D6 before it goes on a card.

## 5. Decisions

**D1. Which revision — Rev 3 ("2A(alt)").** Mine to make, and made (port-tempest section 8): it is the
final release, MAME's parent set, verified here, and it differs from Rev 1 only in the forty-credit bug,
a credits-display jump and the self-test — none of which the port keeps. Say if you want otherwise.

**D2. Geometry-faithful or appearance-faithful (yours).** Recommendation: **geometry-faithful, with the
free part of appearance** — execute Atari's display list exactly, scale it onto 240 rows, and carry
colour and beam intensity through the CLUT (`colour × 16 + intensity` is exactly 256 entries,
port-tempest 4.3). No glow, no thick lines, no tricks. What it costs: nothing extra per line. What it
gives up: the vector monitor's bloom. Revisit after stage 2's photograph, if at all.

**D3. Text — DECIDED (user, 2026-09-22): glyph masks on a text bitmap.**

- **Why:** characters are ~226 of ~473 line records in a play frame and nearly all on text screens
  (`docs/status.md`), and every character costs the driver 4-8 records.
- **The font:** Tempest's text uses exactly two scales (0 and 1; `docs/status.md`). A host tool
  (`tools/glyphs.py`, stage 0) renders every character subroutine of the vector ROM (`$3000`-`$31E3`)
  at both scales with `avgview`'s mapping and Bresenham, so a glyph is pixel for pixel what the line
  engine would have drawn. About 40 glyphs × 2 sizes, one bit a pixel, drawn in any CLUT colour.
- **The interpreter:** a `JSRL` into `$3000`-`$31E3` is not executed. It appends (character, beam
  position, scale, colour, intensity) to a text list and advances the beam by the character's own
  displacement, which the same tool records per glyph and scale.
- **The text bitmap:** a third bitmap on the front layer, single-buffered, **redrawn only when the text
  list differs from the last one drawn** (a score ticking, a message appearing, a blink). The rows
  touched are cleared and redrawn through window A's spare block or a service mapping; a whole-bitmap
  clear is `SS.BmClear`. Joust's `text.a`/`draw.a` are the model.
- **Costs:** all three bitmaps are in use (lines ×2, text ×1), so D9's triple buffer is out. A text
  change can tear for one frame. 30 more blocks of graphics memory in all.
- **To check:** a character that overlaps the well (none seen in attract) would now sit in front of
  it; and text drawn in play at a depth scale (none found in the source).

**D4. The controls — DECIDED (user, 2026-09-22).** No spinner is expected. **Keyboard, mouse and
joystick**, all three, feeding the same `TBHD` counts:

| Control | Rotate | Fire | Superzapper | Source |
|---|---|---|---|---|
| Keyboard | ← → at a **constant rate** | **Shift** | **`z`** (lower case: `SS.LiveKeys` returns unshifted codes) | one `SS.LiveKeys` a frame: arrows and Shift are sense bits, `z` a held key |
| Mouse | X motion, **proportional** | left button | right button | `SS.MsDelta` (approved, section 6.1) |
| Joystick | left/right at a constant rate | button 0 | button 1 | `SS.Joy` mode 2 |

This is MAME's model too: the knob is an `IPT_DIAL` with `PORT_KEYDELTA(20)` (`tempest.cpp:612`), so
keys and a digital stick turn it at a fixed rate while held, and a mouse drives it proportionally
(`PORT_SENSITIVITY(100)`). How MAME scales 20 into encoder counts per frame is unchecked; the port's
rate and the mouse's counts-per-turn scaling go in the settings file, tuned by feel against MAME.

The options as first written, kept for the record:

| | Hardware | Driver work | Recommendation |
|---|---|---|---|
| a | A PS/2 mouse, or a spinner that presents as one | **`SS.MsDelta`** (section 6.1): an unclamped delta, pointer off | **Yes**, if you have or will get such a device |
| b | A raw quadrature spinner on a joystick header | An interrupt-rate decoder in a driver, plus a call | Only if that is the hardware |
| c | Keys / a stick with rate ramping | None | **Always**, as the fallback and for testing |

The counts-per-turn scaling goes in the settings file, so the feel is tuned without a rebuild.

**D5. POKEY sound (yours).** The seam is the register image (port-tempest 6.1). Output stages:

| | How | CPU a frame | New work / risk |
|---|---|---|---|
| a | **SID mapping**: one SID voice per POKEY channel (3 SIDs = 9 voices ≥ 8); `AUDF` → frequency, pure tone → pulse, noise forms → noise waveform, volume via the sustain level | Tiny: register writes when the image changes | Unexercised chips; whether the soft SIDs honour a sustain change mid-note is unchecked; POKEY's polynomial noise only approximated |
| b | **PSG mapping**: 4-bit POKEY volume maps onto the PSG's 4-bit attenuation directly; tones exact; one noise channel per PSG, clocked from a tone channel | Tiny | Only one noise voice per chip; noise character differs |
| c | **VS1053, samples**: Joust's path, recordings from `mame -wavwrite`, mixed in software | ~1 ms mixing several voices | Tempest's sounds are continuous and overlap (thrust, pulsation) and vary with play: a sample per sound loses that |
| d | **VS1053, POKEY synthesised in software** to PCM | ~10% of the CPU at 6 kHz; more for fewer artefacts | Exact behaviour, costly; high tones alias at 6 kHz |

Recommendation: **(a) first**, because it keeps Atari's sequencing exact at almost no CPU cost, needs no
sample assets and no new address exception (the `$C4` page is reached with `F$MapBlk`), and leaves the
VS1053 free. Stage 4 judges it by ear against MAME; **(b)** is the fallback on the same chips, and
**(d)** if neither is close enough. Note the `$C4` page then holds window B for the whole run (section 3).

**D6. The 6502-to-6809 translation method (yours).** Recommendation: **mechanical first draft, hand
finish, differential test.**

1. `tools/m65to09.py` translates each file mechanically: every label, comment and routine order kept,
   the original line number on every emitted line, HLL65 structures expanded, and a fixed idiom per
   6502 addressing mode.
2. I finish each routine by hand, keeping a per-routine checklist (Joust's `utilcheck.py` role).
3. **Differential test**: a host 6502 emulator runs Atari's routine from the rebuilt ROM, the 6809
   routine runs on the machine (or a host 6809 emulator, if one proves reliable), same inputs, compared
   outputs. The original binary is the oracle.

*Pilot done 2026-09-22 (host only): `docs/status.md`, "D6 pilot". **Model B approved (user,
2026-09-22).** The pilot puts the pseudo-registers in unallocated zero-page bytes ($B8-$BB) instead of page 1, and
gives a code ratio of about 1.33.  **Step 1 done 2026-09-23** (`tools/m65to09.py`, draft in `xlat/`,
ratio 1.35; `docs/status.md`, "D6 step 1"): reviewed 2026-09-23; hand work in `src/` next, in the
approved order, plus a test on recorded game states.*

**Before step 1, a pilot** on three routines chosen to stress it — `WORSCR` (arithmetic and the divide),
`MODSND` (table-driven, X and Y both live) and a list builder with `STA NY,VGLIST` — translated under
two register models, measured for size and cycles:

- **Model A**: 6502 A → A, X → B (tables through `ABX`, since `B,X` is signed), Y → a byte in page 1.
- **Model B**: A → A, X and Y → bytes in page 1, loaded as needed.

DP holds the arcade's zero page page-for-page, which is full; `DBASE` and any pseudo-registers go in the
free top of page 1 (the 6502 stack area), so a few zero-page variables will have to move there too —
the pilot picks which. The pilot's size ratio also answers whether vector ROM fits in the module
(section 3).

**D7. Pacing (yours).** Recommendation: **the arcade's rule on a virtual 246 Hz IRQ** (section 2) —
game frames of 2 or 3 ticks, averaging the arcade's 27.3 Hz, with `MODSND` and the clocks on the virtual
IRQ. Alternative: a fixed 30 Hz, simpler and even, **10% fast**. The virtual IRQ is one routine, and 30 Hz
is one constant, so stage 7a can show both.

**D8. The integer coprocessor at `$FEE0` — APPROVED (user, 2026-09-22)** as a second named
absolute-address exception, beside the VS1053. It is the Math Box's one divide in one step
against 300-400 cycles in software, twice a projected point. Two conditions: `tools/piccheck` learns the
range; and the divide runs with interrupts masked for its few instructions, because the unit is global
and **`fm` already uses `$FEE0`** — another program on another terminal can interleave. A software
divide stays in the source behind a build flag, for comparison and in case you say no.

**D9. Erase and flip order (after stage 1).** Two shapes:

- **Double buffer, synchronous clear**: after the tick, `SS.BmClear` (mode 7) on the hidden bitmap, draw
  into it, `SS.Layer` it at the next game frame. Simplest; costs the clear's wait if the call misses the
  window.
- **Triple buffer, asynchronous clear**: shown, drawing, clearing rotate; `SS.BmClear` mode 0 arms the
  clear for the next window and returns at once. Nothing waits; costs ten more blocks. Needs the fixed
  core's "CPU may run while a transfer is pending", which is its whole point.

Recommendation: **the double buffer.** The triple buffer is no longer available: D3 puts text on the
third bitmap.

**D10. Scope (yours).** Recommendation: **drop** the self-test (`ALTES2`) and the anti-tamper checks
(port-tempest 2.4, made to pass); **keep** the coin/credit logic (Joust did, with a coin key), the
options as a settings file with an operator program in the `joustadm` mould, and the four languages
(they are tables). **One player at a time on one spinner**; the two-player alternating game works, the
cocktail flip does not.

## 6. New and changed SS calls, for review — not to be coded before approval

### 6.1 `$D0 SS.MsDelta` — mouse motion as counts (new; GetStat and SetStat) — APPROVED 2026-09-22

`$D0` is free (it was `SS.KyDwn`), in the input group's neighbourhood with `SS.LiveKeys` `$C6`.

**GetStat — the motion since the last call.**

| Register | Exit |
|---|---|
| **R$X** | ΔX, signed 16-bit, counts since the last call; right is positive |
| **R$Y** | ΔY, signed 16-bit; up is positive (the PS/2 convention; the pointer's Y is the reverse) |
| **R$A** | buttons: bit 0 left, bit 1 right, bit 2 middle, 1 = pressed |
| **R$B** | bit 0 = a mouse was found at start-up; bit 7 = an accumulator saturated since the last call |

Reading **clears** both accumulators, in the driver with interrupts masked for the read-and-clear. The
accumulators saturate at ±32,767 rather than wrap. A terminal that is **not live reads zero motion** and
clears nothing, so a background program cannot steal the foreground's motion.

**SetStat — pointer or counts.**

| Register | Entry |
|---|---|
| **R$X** | **0** pointer mode (today's behaviour, the default); **1** counts mode |

In counts mode the interrupt routine **only accumulates**: it does not move the pointer, and it does not
set `MS_MEN` (today it turns the pointer on at every packet, `IRQMSvc`). The mode belongs to the terminal
that set it and is applied only while that terminal is live, so a switch back to the shell brings the
pointer back. Closing the path returns the terminal to pointer mode.

**Driver changes:** `mousedrv_ps2`'s `IRQMSvc` adds the packet's 9-bit deltas (sign from byte 0) to two
16-bit accumulators before the existing pointer code, which it skips in counts mode; it also honours the
packet's overflow bits by saturating. The handlers go in `grfdrv256` beside `GSMouse` (GetStat) and in
vtio for the SetStat, whichever owns the storage. **Storage is the one open question:** 5 bytes (two
accumulators, the mode). The mouse fields already live in vtio's device statics, which are at 242 of a
hard 256 (Joust's open item j); 247 fits, and it is the last easy 5 bytes.

**Why not extend `SS.Mouse`:** its GetStat returns an absolute, clamped pointer, and CoCo code uses the
same code with a different packet. A new code costs nothing and breaks nobody.

### 6.2 `$E7 SS.BmLine` — changes to an existing call

**It is already a batch call.** One `SS.BmLine` draws up to 255 lines from the caller's array; nothing
in this plan calls it per line. What can still multiply the calls in a frame is (a) the FIFO filling,
which makes the driver return short, and (b) a frame of more than 255 lines. (1) and (2) answer (a);
(3) answers (b). The aim is **one call per frame**.

**(1) Exact room, no layout change.** Today the driver stops a batch when fewer than **320** FIFO
entries are free (`LD.Room`), the length of the longest possible line. Tempest's lines are mostly short,
so it stops far earlier than it needs to. Proposed: stop when the free entries are fewer than **this
record's own length**, `max(|x1-x0|, |y1-y0|) + 1`. About 20 cycles a record; never an overrun, since
the walk enqueues exactly that many pixels. A caller sees only that more records are drawn per call.

**(2) A `WAIT` flag, in `R$Y`'s high byte.**

| Register | Entry |
|---|---|
| **R$Y** low | bitmap # (0-2), as today |
| **R$Y** high | **bit 0 WAIT**: when the FIFO lacks room, poll its count until there is room, instead of returning short. Bits 7-1 reserved, must be 0 |

Today any non-zero high byte is `E$IllArg` (`SSBmLine` compares all of `R$Y` against 2), so every existing
caller already passes 0 and keeps today's behaviour. With `WAIT`, a whole frame's lines go in **one
call** — one 474 µs transport instead of one per FIFO-full — while the driver waits for the drain it
would otherwise have handed back to the caller. The wait is bounded (about two frames of polls, like
`SS.BmClear`'s mode 7); if it expires the call returns short with carry clear, exactly as today, so a
caller's resume loop is still correct. grfdrv runs with the caller's interrupt mask, so the wait blocks
no interrupts; it does hold grfdrv, which is synchronous by design.

**(3) More than 255 records a call.** `R$U` is 16 bits but today anything above 255 is `E$IllArg`
(`tsta; lbne`). Proposed: accept up to 1,024. The array is then up to 8K and can span three blocks of
the caller's map, so the driver's buffer mapping (`MapCallBuf`, block plus the next) must advance a
block as the record pointer crosses one — the main cost of this change. Old callers pass ≤ 255 and see
no difference. Only if stage 0 shows frames above 255 visible lines.

*Stage 0 (2026-09-22): frames need 473 records (median, play) to 696 (max) but only ~3K-15K
pixels. So (3) is justified by the numbers, and (1)/(2) probably are not.*

**Worth building only if stage 1 says so**: `D` and `V` show how often a Tempest frame fills the FIFO,
and `S` shows what a call costs. If a frame's lines rarely exceed 4,096 pixels, neither change buys
much.

**Considered and not proposed:** a polyline record (move-to/line-to). It shrinks the caller's buffer
but not the driver's work — every line is still seven register writes and a poll — and the slope in
stage 1 is what would justify it.

## 7. What only you can supply

- **Stage 1's hardware runs**, starting with bmtest's `F` key on the K2; then `tline`.
- **Whether you have, or will get, a spinner, and what kind** (D4).
- Answers to D2-D10, and the approval of section 6's layouts.
- The **coprocessor exception** (D8).
- The Jr2 with the fixed core, when the Jr2 runs start.
- Whether a real Tempest cabinet is available for reference, as your Joust machine was. If not, stock
  MAME is the reference, which is weaker for colour and brightness than for geometry.

## 8. Risks

- **The line volume.** If a busy frame drains too slowly, the picture tears or the game slows. Stage 0
  gives the load and stage 1 the capacity before anything else is built on them.
- **CPU time.** Game logic that took the 6502 up to 36.6 ms of 1.5 MHz, translated, plus the
  interpreter, plus a per-record driver cost × a few hundred lines, must fit a 36.6 ms frame at 8 MHz.
  Estimated to fit, not measured; stage 0's busy fraction and stage 1's slope make it arithmetic.
- **Translation fidelity.** A translation loses "compare against the listing". The differential test
  against Atari's own binary is the compensation, and it has to be built before the game is, not after.
- **Module size** against 40,192 bytes with vector ROM inside it. The pilot measures it.
- **The spinner** might not exist as hardware for a while; the fallback keeps the port testable.
- **Unfixed cores wedge on `SS.BmClear`**, and nothing tells a program which core it is on.

## 9. Out of scope, deliberately

- Driving the line-engine registers from the program (port-tempest 4.5).
- The VS1053 as a geometry coprocessor (Joust's parked item; it would also take the chip D5 might want).
- Cocktail mode, the self-test, Tempest Tubes and other ROM hacks.
- Any change to MAME. Captures use stock MAME with a Lua script.
