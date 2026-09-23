# Tempest on the Wildbits F256: the port survey

The per-game companion to `docs/port-guide.md`, which is the generic platform guide. **Read that first**;
it holds everything that is true of any port: the logical-space budget, the PIC and data-area rules, the
graphics/sound/input hardware, OS-9 citizenship, the driver work and the working method. This file holds
only what is specific to Tempest, in the shape section 14 of the guide asks for. The plan built on it is
`docs/port-plan.md`.

**Status (2026-09-22): the survey of Atari's source is done, and nothing is built or run.** Every fact
about the original below was read from `tempest_orig/src` and cited by file and line; every fact about
the platform was read from the NitrOS-9 tree, the Joust docs or the RTL. What is **unchecked** says so.
Line numbers are the source files' own (CRLF lines, as an editor shows them).

**The first version of this file (2026-09-20) was written before most of the driver work existed.** What
changed, so nobody acts on the old text:

| Old statement | Now |
|---|---|
| The line engine's registers are known only from the RTL; proving it is harness job one | **`SS.BmLine` exists and is confirmed on K2** (2026-09-21, a 16-line fan): batches of 8-byte records, a colour per record, up to 255 a call, and it stops early rather than overflow the 4,096-pixel FIFO. What is still unmeasured is **volume**: pixels drained per frame. bmtest's `F` key (255 full-width lines) has never been pressed |
| "Erasing is the part with no obvious answer" | **`SS.BmClear` answers it.** One call fills a whole bitmap on the DMA engine, 76,800 bytes in about **384 µs** 16-bit. The rc16 DMA was **fixed on 2026-09-22** and Joust uses it: wait mode 7 (`DmaWt.Poll`), synchronous, `E$DevBsy` on timeout. **An unfixed core still wedges on this path**, and `fpga-6809-cores-staging/` does not carry the fix yet |
| The DMA "stalls the CPU and runs only in a vertical-blanking window" | Still true of the fill itself as far as anyone knows, and it matters: mode 7 **returns when the fill is done, and the fill waits for the window at line 0** — the driver's own comment budgets "15 ms to line 0 plus 0.4 ms of transfer" (`grfdrv256.asm`, the `bcpoll@` note). So *when* the clear is called decides whether it costs 0.4 ms or a whole frame. **Unchecked on the fixed core**: whether a transfer still waits for the window, which is the first thing section 4.2's harness measures |
| `SS.BmLine` holds interrupts off for its whole batch, ~7 ms at 255 records | **Wrong.** `vtio`'s `CallGrfDrvGo` saves the *caller's* CC before its `orcc`, plants it in the RTI frame (`vtio.asm:480-492`), and grfdrv runs with it; only the MMU edits inside grfdrv are masked. What a long batch does hold is **grfdrv** — no other terminal's output runs until it returns. `docs/bitmap-api.md` §15 in the Joust tree still carries the old claim |
| A mouse's X delta is "the closest existing thing" to a spinner | Closer than that, but not usable as it stands: `mousedrv_ps2` **clamps X to 0-640 and draws a pointer** on every packet (section 5) |
| The Math Box is "a hardware multiplier/divider" | The game uses **exactly one** of its operations, a divide, and its result is an ordinary integer quotient (section 6.2). The coprocessor at `$FEE0` does it in one step |

`docs/port-guide.md` is stale in the same places — it still says the DMA was "never used here", that MAME
draws only text, and it names `SS.KyLive`/`SS.KyDwn`, which are now `SS.LiveKeys`. It is shared
byte-for-byte with the Joust tree, so it has been left alone here; correct it in both places together.

---

## 1. The original, in the terms the survey cares about

| Question | Tempest | Consequence |
|---|---|---|
| CPU | **6502 at 1.512 MHz** (MAME: 12.096 MHz / 8) | A **translation**, not Joust's transcription. Section 7 |
| Display | Colour **Analog Vector Generator** (AVG) executing display lists from 4K of vector RAM at `$2000` and 4K of vector ROM at `$3000` | The line engine is the matching primitive. Section 4 |
| Frame rate | **The game advances at most once per 9 IRQs**; the IRQ is 12.096 MHz / 4096 / 12 = **246.1 Hz**, so ≤ **27.3 game frames a second**, slower when a frame overruns | Not 60 Hz. The whole port's pacing follows from this. Section 3 |
| Geometry | A Math Box on the aux board; the game uses one divide from it | One 16/16 divide on the F256 coprocessor. Section 6.2 |
| Input | Spinner: an optical encoder into a **4-bit counter**, **72 counts a turn**; fire, superzapper, two starts | A per-frame **delta**. Section 5 |
| Sound | Two POKEYs, **8 channels**, **13 sounds**, all from one table interpreter | No POKEY here. Section 6.1 |
| Randomness | POKEY's `RANDOM`/`RANDO2`, read by 17 instructions in the game (`ALWELG` 15, `ALDIS2` 2) and by two anti-tamper checks | A software LFSR, stepped per read |
| Settings / high scores | EAROM (`ALEARO`) | The guide's settings-as-a-file model |
| Orientation | **Portrait** (MAME `ROT270`), but the used area is nearly **square** (MAME visible area 580 × 570 AVG units) | Fits a 240-row screen with side margins. Section 4.4 |
| Code size | **~20 KB of 6502** (`$9000`-`$DFDC`) plus **4 KB of vector ROM** | Against 40,192 bytes of module. Section 7 |

## 2. The source, file by file

Rev 2A(alt) is built from the `2` files and Rev 1 from their twins (section 8). Sizes are the object
sizes in `ALEXEC.MAP`, which is dated 27-AUG-81 and was linked from the Rev 1 names; the Rev 2A objects
differ by a handful of bytes (the diffs are tiny, section 8).

| File | Lines | Object | What it is | Port |
|---|---:|---:|---|---|
| `ALEXEC.MAC` | 602 | 865 | The executive: `MAINLN` (45), the state table `ROUTAD` and `EXSTAT` (66), credits, `NONSTA` (202), new game / life / wave preparation, score add | Translate |
| `ALWELG.MAC` | 3,559 | 6,320 | The game: wave set-up and the skill tables, `PLAY` (867), `MOVCUR` (899, reads the spinner), enemies ("nymphs" become "invaders": flippers, tankers, spikers, fuseballs, pulsars), charges, collisions, explosions | Translate |
| `ALDIS2.MAC` | 3,283 | 5,610 | **The display-list builder**: `DISPLAY` (47), `DENORM` (123), buffer control `SBCLOG`/`SBCSWI` (198), the well (`DSPWEL` 295, `BLDWEL` 2574), every object's picture, `CASCAL` (1444) and `WORSCR` (2208) — **all of the game's Math Box use** — star field, enemy lines | Translate |
| `ALSCO2.MAC` | 1,396 | 2,310 | Scores, lives, messages (`INFO` 48), high-score table and initials entry, the skill-select ("rating") screen, the logo | Translate |
| `ALVROM.MAC` | 2,498 | 326 + 4K | **Vector ROM**: the characters, every enemy/player/explosion picture as AVG subroutines, the score template, the `INVERS` table (1890) | Assemble as data |
| `ALLANG.MAC` | 291 | 1,746 | Messages, four languages | Translate (tables) |
| `ALSOUN.MAC` | 384 | 733 | **Sound**: 13 sounds as per-channel sequences, and `MODSND` (270), the interpreter the IRQ calls | Translate verbatim; new output stage |
| `ALVGUT.MAC` | 394 | 211 | Vector-list utilities: `VGJSRL` (201), `VGSTAT` (224), `VGSCAL` (285), `VGVCTR` (336), digits | Translate |
| `ALHAR2.MAC` | 186 | 222 | **The IRQ**: watchdog, **spinner read** (63), switch debounce, lamps, `MOOLAH`, `MODSND` (148), `FRTIMR` (149), VG restart (174) | Rewrite into the frame loop |
| `ALEARO.MAC` | 260 | 300 | EAROM read/write of scores and bookkeeping | Replace with a file |
| `ALCOIN.MAC` + `COIN65.MAC` | 22 + 663 | 269 | Atari's "universal" coin routine | Keep the credit logic, or simplify (Joust kept coin-op) |
| `ALTES2.MAC` | 931 | 1,532 | Self-test: RAM/ROM/Math Box/POKEY tests, test patterns | Drop |
| `ALCOMN.MAC` | 1,130 | — | Constants, RAM map, hardware addresses (`HARDWARE DEFINITIONS` 239) | The data-area layout |
| `HLL65.MAC` | 116 | — | Structured-control macros: `IFxx`/`ELSE`/`ENDIF`, `BEGIN`/`xxEND` | The translator's first job |
| `VGMC.MAC`, `ANVGAN.MAC`, `ASCVG.MAC` | | — | AVG instruction macros and the character set macros | The AVG instruction encoding |
| `ALDIAG.MAC` | 167 | — | Stand-alone VG diagnostic PROM | Not in the game |
| `MBUCOD.V05`, `MBUDOC.DOC` | | — | Math Box microcode and its documentation | Reference only |
| `STATE2.MAC` | 33 | — | The AVG's state PROM | Reference only |
| `ALDISP`, `ALSCOR`, `ALHARD`, `ALTEST` | | | The Rev 1 twins | Not used (section 8) |

### 2.1 Where the five things live

**The display-list build.** `DISPLAY` (`ALDIS2.MAC:47`) runs once per game frame. In play it calls
`DENORM` (123), which builds each object group into its own **sub-buffer** in vector RAM — cursor,
shots, invaders, explosions, nymphs, info (scores and text), the well, enemy lines, stars — each
**double-buffered** (A/B). `SBCLOG` (198) points `VGLIST` at the idle half, the group's routine writes
AVG instructions there, and `SBCSWI` appends an `RTSL` and flips a `JMPL` switch word so the next pass
of the AVG sees the new half. A master `JSRL` list at the top of vector RAM calls every group. Pictures
are **AVG subroutines in the vector ROM** (`ALVROM`), reached with `JSRL` after a `SCAL` (binary and
linear scale) and a `STAT` (colour, intensity). Much of the building is `STA NY,VGLIST` straight into
the buffer, not calls to `ALVGUT` — which is why the seam has to be the list itself (plan, D2).
**The well is only rebuilt when it moves** (`DSPWEL`, `ROTDIS`): a static well costs nothing per frame
on the arcade.

**The well geometry.** `TABLES-WELL COORDINATES(WORLD)` (`ALDIS2.MAC:1231`, `NEWLIX` at 1237): 16 wells
as 8-bit world X/Z tables per shape (circle, square, cross, …), built into screen points by `BLDWEL`
(2574) through `WORSCR`. `tempest_orig/notebooks/Render Wells.ipynb` and `well_graphs.py` already render
them on the host.

**The Math Box.** Only `ALDIS2.MAC` touches it in the game (49 references; `ALTES2` has the other 20).
Of those, the multiply and window code at 2047-2207 sits inside **`.IF NE,0`** — assembled out. What
runs is `INIMAT` (2368, zero the registers), **`CASCAL`** (1444, an object's scale from its depth) and
**`WORSCR`** (2208, world to screen, two divides per point). Section 6.2 has what they compute.

**The spinner read.** In the IRQ, `ALHAR2.MAC:63-78`: kick `POTGO`, read the low 4 bits of POKEY 1's
`ALLPOT` (the encoder's counter), subtract the previous reading, sign-extend the 4-bit difference to
-8..+7, and add it to `TBHD` (`ALCOMN.MAC:479`). `MOVCUR` (`ALWELG.MAC:899-922`) takes `TBHD` once per
game frame, **clamps it to ±31**, zeroes it, and moves the cursor. The attract-mode "press start" check
(`ALEXEC.MAC:181`) and the skill-select and initials screens (`ALSCO2`) read it too.

**The POKEY writes.** `MODSND` (`ALSOUN.MAC:270`), called from the IRQ at 246 Hz, is the only sound
output: `AUDF`/`AUDC` for 8 channels and `AUDCTL`. Everything else touching POKEY is input (`POTGO`,
`ALLPOT`, `ALLPO2` in the IRQ), randomness (`RANDOM`/`RANDO2`: 15 reads in `ALWELG`, 2 in `ALDIS2`), the two anti-tamper checks of
section 2.4, or self-test.

### 2.2 The frame, and why it is not 60 Hz

```
MAINLN (ALEXEC:45)   loop: wait until FRTIMR >= 9, FRTIMR = 0
                           EXSTAT   the state routine (ROUTAD: new game, play, drop, end wave, ...)
                           NONSTA   credits, test switch, options
                           DISPLAY  rebuild the changed sub-buffers
IRQ (ALHAR2:38)      246.1 Hz: watchdog, spinner -> TBHD, debounce switches, lamps,
                     coins, MODSND (sound), FRTIMR++, clocks, restart the VG if it halted
```

The AVG meanwhile redraws vector RAM **continuously and independently**; the game only replaces
sub-buffers. So on the arcade the picture refreshes far faster than it changes, and the game's own clock
is the 9-IRQ frame: **36.6 ms, 27.3 Hz**, stretched whenever a frame's work overruns it. On the F256 the
bitmap is only as new as the last frame drawn into it, so "refresh" and "update" become the same thing,
at the game's rate.

### 2.3 RAM

`ALCOMN` lays out **2 KB**: zero page from `$00` (`ALCOMN.MAC:391`), page 1 from `$100` (with the 6502
stack at the top — the IRQ resets if S drops below `$D0`), and `$200`-`$7FF` for the object arrays.
**Zero page is full**: `ALEARO` puts two bytes at `$BD` and `ALSOUN` puts `SINDEX` at `$BF` and four
16-byte channel arrays after it, which reach `$FF`. Plus 4 KB of vector RAM and 16 bytes of colour RAM
(`COLRAM`, `ALCOMN.MAC:427`, copied to `COLPORT` at `ALDIS2.MAC:2356`).

### 2.4 Anti-tamper code, which a port must neutralise

Tempest checks itself, and punishes a failed check. Found by name (`ZAT*`, `ZQ*`, `ZPO*`) and by the
`QT3`-`QT6` flags; **not proven to be the complete list**:

- `ZATVG2` (`ALDIS2.MAC:66`) checksums the copyright vectors into `QT3`; `ZATVG1` (157) into `QT6`.
- `ZQVAVG` (`ALWELG.MAC:3082`) acts on `QT3`/`QT6`: over 170,000 points it `INC`s a zero-page byte
  chosen by the score. **This is the Rev 1 forty-credit bug**: Rev 1's `ZATVG2` compared against `$2A`
  instead of `$29`, so the check failed on genuine boards.
- `ZPONTS` (`ALSCO2.MAC:876`) reads both POKEYs' `RANDOM` twice and expects the nibbles to match —
  **a check for real POKEY hardware** — into `QT5`, acted on by `ZQPONS` (`ALDIS2.MAC:2968`).
- `ZPOKST` (`ALSOUN.MAC:352`, inside `INISOU`) stops the POKEYs and checks that `RANDOM` keeps changing,
  into `QT4`, acted on by `ZQPOKS` (`ALDIS2.MAC:961`). A software LFSR stepped per read would pass it;
  `ZPONTS`'s nibble test it would not.
- `ZATC4V` (`ALSCO2.MAC:105`), the `ZATC3`/`ZATC4` ranges, and the `ZATLIS` sum (`ALSCO2.MAC:983`)
  verify the copyright message and the calls to it. **`ZATC4V` XORs 6502 code** (`ZATC4S`, the call
  to the ATARI message) into `QT2`, acted on by `ZQAT4C` (`ALEXEC.MAC:262`, a `SED`): on the port
  that code is 6809, so it is neutralised to its passing result (`src/alsco2.a`; found by the
  recorded-state test, 2026-09-23). `ZATLIS` sums message data, which the port holds byte for byte.

Neutralise them by making each check pass, not by deleting the flags — the guide's stubbing rule
(section 1) applies: grep every consumer first.

## 3. Pacing

The arcade's rule is "at least 9 IRQs per game frame". The F256's clock is the 60 Hz start-of-frame
tick. 9 IRQs are 2.195 ticks. Section 3 of the plan (decision D7) keeps the arcade's rule by running a
**virtual 246 Hz IRQ** counter, advanced by 246.1/60 per tick, and taking a game frame whenever 9 have
accumulated: game frames then take 2 or 3 ticks. The IRQ's other jobs — `MODSND` and the clocks — run
once per virtual IRQ, so sound envelopes and timers keep the arcade's time base.

## 4. The display

### 4.1 The seam is the display list

The AVG's instruction set is small (`VGMC.MAC`; MAME `devices/video/avgdvg.cpp`): `VCTR` (relative
move, intensity 0-7 in the long form), `SVEC` (short vector), `CNTR`, `STAT` (colour or intensity),
`SCAL` (binary scale 0-7, linear scale 0-255), `JSRL`/`RTSL` (four levels), `JMPL`, `HALT`. Keep
Atari's list-building code and replace the AVG with a **6809 interpreter** that walks vector RAM from
the master list, applies scale, colour and intensity, clips, and emits `SS.BmLine` records. Blank moves
(intensity 0) cost nothing but arithmetic.

**This is also the instrument.** The same interpreter written in Python renders a vector-RAM snapshot to
a PNG and counts its lines and pixels, and vector RAM can be captured from **stock MAME 0.276**, which is
installed and verifies the `tempest` set straight from `tempest_orig/notebooks/roms/tempest` (checked
2026-09-22), with a Lua `-autoboot_script` — MAME unmodified. That gives the line and pixel volume of
real frames before any hardware run, and a picture to compare every later frame against.

### 4.2 Lines and erase, per frame

- **Draw:** `SS.BmLine` into the bitmap no layer shows. Each record is an absolute line; the FIFO drains
  only on **odd visible lines** and only on bus cycles the CPU leaves free (`defs/wildbits.d`, the `LD_*`
  notes). The driver stops a batch when fewer than 320 entries are free and returns the count drawn.
- **Erase:** `SS.BmClear` on the other bitmap, 16-bit, one call.
- **Show:** swap with one `SS.Layer`.

**First measurement, K2, 2026-09-22: bmtest's `F` key reported "SS.BmLine flood: drew 255 of them"**, with
no error. That is 255 full-width lines, 81,600 pixels, in one call, and **the FIFO pacing never fired**:
before every record the queue had at least 320 free entries. By the test's own criterion (written before
anything was known) that is a fail, but it has two readings, and **which one is true is not yet known**:

- **The drain keeps up.** The driver's per-record loop (an estimated 25-30 µs, most of it register
  writes and the poll) is slower than the FIFO drains, so the queue never builds up. The whole batch
  then takes ~7 ms and could fall entirely inside the visible part of one frame, when the FIFO drains.
  This fits the RTL estimate of order 10⁵ pixels a frame. If it is right, pacing rarely matters and
  the plan's `SS.BmLine` changes (1) and (2) buy little.
- **The count read-back is wrong** (reads low or zero), so the check always passes and pixels past
  4,096 are **lost silently**. Then some of the 255 lines would be missing or cut short on the screen.

The screen decides it: every one of the 240 rows striped full width, rows 0-14 drawn twice, means the
first reading. Stage 1's `D` key measures the drain directly.

**The screen (user's capture, same day, after `H`/`S`): all 240 rows are striped full width** in the
15-colour cycle, so the lines were drawn, not dropped wholesale — **the first reading, provisionally.**
But the stripes carry **scattered single pixels of the wrong colour**, in loose vertical columns, all the
way down. Unexplained, and not yet attributable: they could be pixels lost from the FIFO letting earlier
content show through, pixels landing at the wrong address, or the capture path (this rig has faked
faults before). The next run separates them: `C` (clear) then `F` on a known background, photographed
directly, twice.

**Narrowed the same day, K2, DMA-fixed core — THE LINE ENGINE LOSES PIXELS.** Four bmtest runs,
photographed:

| Run | Result |
|---|---|
| `C` (DMA clear to blue) | clean |
| `R` (colour bars, CPU-written) | clean |
| `C` then `L` (16-line fan, ~3,000 pixels, under the FIFO's 4,096) | **gaps in the lines**; nothing stray off them |
| `C` then `F` (flood) | the "specks" are **blue**: the cleared background showing through |
| `C` then `L`, repeated | **the gaps move every time** |

So pixels are **dropped**, not misplaced, not lost to a FIFO overrun (the fan cannot overrun it), not
the register order (checked against the RTL: `TinyVicky_BM_Registers.v:35`, `TinyVickyCoreModule.v:447-458`)
and not the Bresenham (every line is in the right place, colour and length). Moving gaps mean **timing**,
not address. **Hypothesis, untested:** the drain writes a pixel on a cycle the memory arbiter predicts
the CPU will leave free (`Time2Draw_i`, "1 clock ahead", `LineDraw.v` `Read_FIFO`); when the prediction
is wrong the pixel leaves the FIFO and is never written. The DMA fix changed the CPU/bus arbitration,
and a bitmap-sparkle core regression has been seen before (guide section 13). Next, one change each:
the fan at normal CPU speed instead of turbo (contention should drop), and on the pre-fix core (`R`
then `L`, no `C`). **This blocks Tempest**: a vector game with dashed lines is not playable.

**A newer core (2026-09-22, same day): the DMA still works, the lines still have holes.** Drawing the
fan twice in a row fills **most** of them in: each pass drops a different random subset, which is what
the timing hypothesis predicts, and it rules out a pixel the engine never generates. Drawing twice is a
workaround for testing, not for the game: it doubles the cost and still leaves holes.

**Status: with the FPGA developer (2026-09-22).** The user's call: assume a fixed core arrives soon and
carry on; the port does not design around the holes. Re-run bmtest `C` + `L` and `C` + `F` on every new
core until the fan is solid.

What else nobody has measured, and what the plan's first hardware stage measures:

| Number | Why it decides something | Estimate, unchecked |
|---|---|---|
| Pixels drained per frame | Caps the picture | Order 10⁵ (`bmline-bmclear-plan.md` §3, from the RTL) |
| `SS.BmLine` cost per record | 400 lines × this is a large slice of a 36.6 ms frame | 25-30 µs, counted from the instruction stream |
| Lines and pixels in a real Tempest frame | The load | None yet: the MAME capture gives it |
| `SS.BmClear` wall clock, by the line it is called at | 0.4 ms or a whole frame | Driver comment: up to 15 ms waiting for line 0 on the old core |
| Whether `SS.Layer` takes effect at once or at the next frame | Tearing | None |

### 4.3 Colour and intensity fit one CLUT exactly

Tempest's colour RAM is 16 entries of 4 bits, inverted — green, blue and a two-level red
(`avg_tempest_device::handler_7`) — and the beam has 16 intensity levels. **`colour × 16 + intensity`
is a 256-entry CLUT**, so each record's colour byte carries both and the line engine needs nothing
else. Colour-RAM changes (the per-level well colours, the logo rainbow) become CLUT rewrites at the
frame commit, 16 entries per changed colour, in one `SS.ClutWrite`. Index 0 is colour 0 at intensity 0:
black, and transparent, which is what a blank bitmap should be.

This is the cheap half of "appearance-faithful". Glow and beam width are not available and are not
proposed.

### 4.4 Resolution, rotation, clipping

MAME's visible area is 580 × 570 AVG units, rotated 270° (`tempest.cpp:924`; the rotation swaps the
axes, `avgdvg.cpp` `handler_7`). Onto 240 rows that is about **2.4 units a pixel**, a ~236 × 240 square
centred in the 320-pixel width. The far rim of a well and a distant enemy become a few pixels; that is
the cost of 240 rows. **Clipping is required**: the line engine silently drops a line with an endpoint
off the bitmap, and the drop sequence at the end of a wave flies the well past every edge of the screen.

### 4.5 Driving the line engine directly (from the first version, corrected)

The option was a program on the live terminal writing `$C0:$1080-$1087` itself instead of calling
`SS.BmLine`. **The arithmetic still says no, now more firmly.** The per-record work is the same seven
writes and a poll either way; direct access saves one 474 µs call per batch, and nothing else. The first
version's stronger argument — the batch runs with interrupts masked — was **wrong** (see the table at the
top). The remaining objections stand: the control registers are carried per terminal from the driver's
mirror, never read back, so direct writes are invisible to a terminal switch; a program cannot test "am
I live?" and write atomically; and a program writing hardware the driver also writes is the second-writer
shape this project removed from the sprite calls. If the batch count ever matters, **fewer calls** —
the `WAIT` flag in the plan's `SS.BmLine` proposal — is the answer, and it keeps one owner.

One statement from the first version is **doubtful and unchecked**: that `$FFC0-$FFCF` "lives in
`$FD00-$FFFF`, which is in no Level 2 process's address space". Joust writes the VS1053 at `$FF50`
directly from a user process, and `fm` writes the coprocessor at `$FEE0`; both are in that page. Whether
`$FFC0`-`$FFCF` is reachable is therefore a policy question (the driver owns it), not an addressing one.
Nothing in this plan depends on the answer.

## 5. The spinner

**The arcade:** an optical encoder counted in hardware into a 4-bit up/down counter on POKEY 1's pot
port; **72 counts a turn** (MAME `PORT_FULL_TURN_COUNT(72)`). The IRQ turns it into a delta at 246 Hz;
the game consumes it once a game frame, clamped to ±31. So the platform contract is exactly "signed
counts since the last frame", and the game already clamps.

**On the F256 there is no rotary input and no call that reads one.** What exists:

- **The PS/2 mouse.** `mousedrv_ps2` (loaded by the L2 recipe) takes 3-byte packets at 40 samples a
  second, 4 counts/mm, and **adds each delta to an absolute pointer clamped to 0-640 and 0-480**, then
  sets `MS_MEN` = 1 so the pointer shows (`level1/wildbits/modules/mousedrv_ps2.asm`, `IRQMSvc`). `GetStat
  SS.Mouse` returns that absolute position. At an edge the deltas are lost, and the pointer would appear
  over the game whenever the control moved. **So a mouse — or any spinner that presents itself as a
  PS/2 mouse — needs a delta call.** The plan proposes `SS.MsDelta`.
- **A raw arcade spinner** (quadrature) on a joystick header would need an interrupt-rate decoder in a
  driver: at 60 Hz a quadrature signal aliases after one step per sample. Only worth building if that is
  the hardware.
- **Keys or a stick**, with the program ramping the rate while held. Needs no new call, and is the
  fallback whatever else is chosen.

**Decided (2026-09-22): no spinner; keyboard, mouse and joystick** (plan, D4). The mouse needs
`SS.MsDelta`, approved.

## 6. Sound and maths

### 6.1 Sound: one interpreter, eight channels, a register image

`ALSOUN` is small and regular. Each of 13 sounds (`PNTRS`, `ALSOUN.MAC:87`: cursor move, enemy
explosion, player fire, pulsation, bonus, player dies, thrust in tube, thrust in space, enemy shot, enemy
line destruction, slam, 3-second warning, pulsar off) names up to 8 channel sequences, an `F` (frequency,
`AUDF`) and an `A` (distortion and volume, `AUDC`) per POKEY channel. A sequence is 4-byte steps: start
value, IRQs per change, change, number of changes; `0,0` ends and `x,0` loops. `MODSND` steps every
active channel once per IRQ and writes the result to the POKEYs.

So **the seam is a POKEY register image**: 8 × (`AUDF`, `AUDC`) plus `AUDCTL`, rewritten by `MODSND` at
the virtual IRQ rate. Keep `ALSOUN` verbatim, write the image instead of the chips, and let an output
stage turn the image into sound once per frame. The output stage is the decision (plan, D5); every
option consumes the same image, so it stays reversible. The `AUDC` values Tempest uses mix pure tones
(`$Ax`) with polynomial-noise forms (`$0x`, `$2x`, `$6x`, `$8x`), so whatever plays them needs noise
at a controllable rate as well as square waves.

The first version's warning still holds: if the VS1053 is ever used as a geometry processor it is not
available for sound. An output stage on the SIDs or PSGs keeps it free.

### 6.2 Maths: the Math Box is one divide

Read against the Math Box documentation (`MBUDOC.DOC`, the register table) and MAME's microcode model
(`mathbox.cpp`, case `0x14`), then checked on the host by running MAME's algorithm against the formula
over every input Tempest can produce:

- **`WORSCR`** (world to screen), twice per point: `SZXD` with N = 15 and a dividend of `Δz·256` returns
  **`floor(|Δz| × 128 / Δy)`**, exactly, for all Δz < 256 and Δy < 1024 (checked exhaustively). The sign
  is applied by the 6502 afterwards, then the screen centre is added.
- **`CASCAL`** (an object's scale from its depth), once per object: `SZXD` with N = 24 returns the low
  16 bits of **`floor(YDEUNI × 65536 / Δy)`** — a 16-bit fraction.

The F256's integer coprocessor at `$FEE0` (16/16 unsigned divide, quotient and remainder; guide section
7a) does `WORSCR`'s divide in one step and `CASCAL`'s in two. A 6809 software divide is 300-400 cycles.
Using the coprocessor needs an **approved absolute-address exception** like the VS1053's, and it is
shared: **`fm` already writes `$FEE0`** (`level2/wildbits/cmds/fm.asm:3372`), so two programs on two
terminals can collide (plan, D8).

## 7. 6502 to 6809

Joust was a transcription; this is a translation, and the safety net of "compare against the listing"
has to be rebuilt. What the source says about the job:

- **~20 KB of 6502** in the ROM, of which self-test is 1.5 KB. How much 6809 that becomes is the
  number to get from a pilot, not to guess; the budget is 40,192 bytes of module (guide section 3).
- **HLL65's structured macros are everywhere** (`IFEQ`/`IFCS`/`ELSE`/`ENDIF`, `BEGIN`/`CSEND`/`MIEND`/
  `EQEND`/…) and translate mechanically.
- **MAC65 syntax** is its own: `LDA I,0F` (immediate), `LDA X,TAB` (absolute,X), `STA NY,VGLIST`
  ((zp),Y), `.BYTE`, radix 16 by default with a trailing `.` for decimal. A translator reads it once.
- **Zero page is full** (section 2.3). On the 6809 it maps naturally onto DP, page for page — but then
  DP has no room for `DBASE` or for pseudo-registers, and something must move to page 1. The 6502 stack
  area at the top of page 1 (`$1D0`-`$1FF`) is free on the 6809.
- **The 6502 index registers are the hard part.** `LDA TAB,X` with an 8-bit X over a table in the data
  area has no one-instruction 6809 form under the PIC rules: `B,X` offsets are **signed**, and the table
  is data-area-relative. The register model — which 6809 register holds 6502 X and Y, and the idiom for
  each addressing mode — has to be decided once, on a pilot, before the first file (plan, D6).
- **Self-modifying code, page-crossing tricks, `JMP (ind)`, the stack-based dispatch** (`EXSTAT` pushes
  an address and `RTS`es) each need a written form.
- **The original binary is a test oracle.** The ROMs rebuild byte-identical from this source, so a host
  6502 emulator running Atari's own routine is the reference for the translated one: same inputs, same
  outputs. That replaces Joust's "compare against the listing" with something stronger.

## 8. Which revision

**Rev 2A(alt), which is MAME's `tempest` — "rev 3", the final release.** `ALEXEC.LDA` is its linked
binary, and mwenge's notebooks rebuild it byte-identical from these sources and run it in MAME with no
checksum errors (`notebooks/Build Tempest Sources for Version 2A(Alt).ipynb`, `Reconstruct ROMs from
Object FIles in the Tempest Source Dump.ipynb`). Rev 1 is `TEMPST.LDA`, MAME's `tempest1`.

The differences (`notebooks/Differences Between Rev1 and Rev2A(Alt).ipynb`) are three: the anti-tamper
constant in `ZATVG2` (`$2A` → `$29`, **the forty-credit bug**), a `JMP INFO` → `JMP HACKER` in `ALSCO2`
that skips part of the credits display, and self-test changes plus ROM checksums. None of them touches
gameplay, and the port drops the anti-tamper code and the self-test anyway — so the choice is about
which reference to compare against. Rev 3 is the version on the ROM set MAME treats as the parent, the
version most cabinets run, and the one the installed MAME verifies from this tree. There is no reason to
port a version with a known bug in order to remove it.

## 9. What carries over from Joust untouched

- Guide sections 3-5: logical space and the module budget, `F$AllRAM` assets, the PIC rules, the
  DP/`DBASE` data-area convention, the static checker (`tools/piccheck.py`).
- Guide section 10 as *code*: `SS.WSig` pause, terminal lockdown, clean exit on every path, in Joust's
  `src/platform.a`.
- The settings-and-high-scores file, with an operator program (`docs/joustadm.md`).
- `SS.BmClear` exactly as Joust calls it (`src/gfx.a BmClrDma`), and `SS.ClutWrite` for colour changes.
- Guide section 13: the working method and every tooling pothole.

## 10. Unchecked, in one place

- Everything in section 4.2's table.
- Whether the fixed core's DMA still waits for the vertical-blanking window.
- Whether `SS.Layer` flips at once or at the next frame.
- The Jr2, for `SS.BmLine` and `SS.BmClear` both.
- That section 2.4 lists every anti-tamper check.
- The screen mapping in section 4.4 (derived from MAME's visible area, not from captured frames).
- How big the 6809 translation is.
- Whether the soft SIDs honour a sustain-level change mid-note (matters for D5).
- `$FFC0-$FFCF` reachability (section 4.5).
