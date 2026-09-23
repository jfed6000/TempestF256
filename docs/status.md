# Tempest for NitrOS-9 Level 2 on Wildbits F256: status

**2026-09-22.** Survey (`docs/port-tempest.md`) and plan (`docs/port-plan.md`) written. Stage 0 has
begun: the capture and the host AVG interpreter work and match MAME. No 6809 code exists.

## Decisions so far

- **D1 revision:** Rev 3 ("2A(alt)").
- **D4 controls (user):** no spinner. Keyboard (← → constant rate, Shift fire, `z` superzapper),
  mouse (proportional, via `SS.MsDelta`), joystick (constant rate, buttons 0/1).
- **D8 (user):** the math coprocessor at `$FEE0` is approved.
- **`SS.MsDelta` $D0 (user):** layout approved (plan 6.1). Not coded.
- **D3 text (user):** glyph masks on a third, front bitmap, redrawn only when the text changes;
  two sizes rendered on the host from the vector ROM (plan D3).
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

**Not yet done in stage 0:** `tools/m65parse.py`.

## Open items

1. The line-engine holes (FPGA developer).
2. `tline` for stage 1, when the core is fixed: above all the per-record cost.
3. The rest of stage 0 (above), then the D6 pilot.
4. `SS.MsDelta` storage (5 bytes of vtio statics, 242 → 247 of 256).
