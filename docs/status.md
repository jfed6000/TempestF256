# Tempest for NitrOS-9 Level 2 on Wildbits F256: status

**2026-09-22.** Survey (`docs/port-tempest.md`) and plan (`docs/port-plan.md`) written. Stage 0 has
begun: the capture and the host AVG interpreter work and match MAME. No 6809 code exists.

## Decisions so far

- **D1 revision:** Rev 3 ("2A(alt)").
- **D4 controls (user):** no spinner. Keyboard (← → constant rate, Shift fire, `z` superzapper),
  mouse (proportional, via `SS.MsDelta`), joystick (constant rate, buttons 0/1).
- **D8 (user):** the math coprocessor at `$FEE0` is approved.
- **`SS.MsDelta` $D0 (user):** layout approved (plan 6.1). Not coded.
- **The rest (D2, D3, D5, D6, D7, D9, D10):** the plan's recommendations stand unless the user says
  otherwise; D3 is now reopened by the numbers below.

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

**Not yet done in stage 0:** a played game (only attract so far, whose demo is play-like), the 6502
busy fraction, POKEY write logging, `tools/m65parse.py`.

## Open items

1. The line-engine holes (FPGA developer).
2. `tline` for stage 1, when the core is fixed: above all the per-record cost.
3. The rest of stage 0 (above), then the D6 pilot.
4. `SS.MsDelta` storage (5 bytes of vtio statics, 242 → 247 of 256).
