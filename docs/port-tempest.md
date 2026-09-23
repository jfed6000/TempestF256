# Tempest on the Wildbits F256: the port survey

The per-game companion to `docs/port-guide.md`, which is the generic platform guide. **Read that first**;
it holds everything that is true of any port — the logical-space budget, the PIC and data-area rules, the
graphics/sound/input hardware, OS-9 citizenship, the driver work and the working method. This file holds
only what is specific to Tempest, in the shape section 14 of the guide asks for.

Status: **nothing is started**, and nothing here has been checked on hardware. Every number about the
original should be re-checked against whatever source listing the port is made from before it is relied
on.

## 1. The original, in the terms the survey cares about

| Question | Tempest | Consequence |
|---|---|---|
| CPU | 6502 | A **translation**, not a transcription like Joust's 6809 source. See §5 |
| Display | Colour vector (XY) monitor driven by an analog vector generator from a display list | No sprites, no framebuffer to map. §2 |
| Geometry | A hardware "Math Box" doing the multiplies and divides for the tube projection | The F256 integer math coprocessor is its direct analogue. §4 |
| Input | Spinner (rotary encoder), fire, superzapper, start buttons | A per-frame **delta**, not a level. §3 |
| Sound | Two POKEYs | No POKEY on the F256. §4 |
| Settings / high scores | EAROM | The guide's settings-as-a-file model answers this unchanged |

## 2. The display is the whole problem

There is no framebuffer of moving objects to map onto sprites. There is a display list of line segments
with colour and intensity, rebuilt every frame. So:

- **Proving the line-draw engine is the first piece of work**, before the interface document is finished
  and long before any game logic. Guide section 7 now has its registers and behaviour **read from the FPGA
  source** (2026-09-18): the write and read maps differ, the status bit is *complete* rather than *busy*,
  an out-of-range endpoint is silently dropped, the stride is hard-wired to 320, and pixels queue into a
  4096-entry FIFO that **silently loses anything past 4096** and drains in a per-scanline slot. What the
  RTL cannot tell us is the number this port's design rests on: **pixels drained per frame**, and from it
  lines per frame at 60 Hz. The FIFO count registers measure it directly — that is harness job one.
- **Erasing is the part with no obvious answer.** 320×240 at 8bpp is 76,800 bytes; a CPU clear through 8K
  windows is ten block maps and 76,800 stores, which will not fit in a frame. In rough order of promise:
  **a 2D DMA fill** — which the RTL says reaches all of RAM but runs only inside a vertical-blanking
  window and stalls the CPU while it does (guide 6a), so the question is how many bytes one vblank moves;
  draw into one bitmap while showing the other and clear the hidden one incrementally; clear only the
  bounding boxes of what was drawn; or re-draw the previous frame's lines in colour 0, which is exact and
  cheap *if* the engine is fast — and which is also bounded by the same FIFO budget as drawing them.
  Measure before choosing.
- **Keep the original's display-list build and replace only its emission.** The seam is "list of
  transformed line segments with colour" — a better seam than Joust's, because the hardware primitive
  actually matches what the game asks for.
- **The vector monitor's look does not exist on this hardware**: no glow, no beam-intensity line weight, no
  infinite resolution. Decide early and write it down: geometry-faithful, or appearance-faithful with
  tricks. This decision drives the CLUT design, since intensity has to become colour.
- **Text is vector-drawn on the original.** Whether to draw it with the line engine or as a glyph mask
  into a bitmap (the guide's section 6 routine, already written for Joust) is a measurement from step 1,
  not a preference.

## 2a. Driving the line engine directly, and what it would cost

**An option with terms, not a decision** (user's observation, 2026-09-20).  The question was whether a
program on the *live* terminal could write the graphics registers itself, pausing when backgrounded via
`SS.WSig`, and let `PushBuf`/`PullBuf` keep everything in step.  The answer is "partly, and not the way
that sentence assumes", and the parts are worth having written down before Tempest starts, because this
is the one place in the port where the temptation is real.

### What is reachable, and what is not

**Reachable.**  Block `$C0` holds the bitmap, tile, sprite and **line-engine** registers, and `F$MapBlk`
maps device pages — a confirmed capability this project already relies on.  So a user process can write
`$C0+$1080`-`$1087` and drive the line engine itself.

**Not reachable.**  `$FFC0`-`$FFCF` — the master control register, the layer control, the border, and
**`$FFCA`, the line engine's real enable** — lives in `$FD00`-`$FFFF`, which is in *no* Level 2
process's address space.  That is the memory map, not a policy.  So "turn the bitmap engine on", "which
layer shows which bitmap" and "enable line drawing" remain driver calls whatever else is decided.

### `PushBuf`/`PullBuf` will **not** carry direct writes, and that is deliberate

**Corrected 2026-09-20** — the first version of this section overstated it.  `PushBuf` *does* read back
Vicky **memory**: CLUTs 0-3 and font bank 0 (`TermSaveCLUT` / `TermSaveFont0`, both `equ 1` and both
confirmed on hardware), plus the text screen and colour planes.  A program poking CLUT entries directly
**would** survive a switch.  What it does not capture is the **control registers** — the bitmap
registers, the tile registers and `$FFC0-$FFCF`.  That capture was removed because on real hardware it
was actively harmful — `grfdrv256.asm`'s own comment:

> a background image loaded on `/vt1` displayed correctly, survived being switched away from, and came
> back as pure static — `PushBuf` had overwritten `V.BM2Blk` with whatever reading `$3011` produced and
> `PullBuf` pointed the display at it.  **MAME models the whole `$C0` page as plain RAM, so the round
> trip is perfect there and the failure never appears.**

So for the control registers the switch path is **mirror → hardware, never back**: direct writes to them
are invisible to it and are overwritten from the driver's mirror on the way back in.  The same source
anticipates the question outright: *"A program that poked `$C0+$1000` behind the driver's back would no
longer have its bitmap carried per terminal."*

**But that is a fixable state of affairs, not a hardware limit** — see the parked item in
`docs/status.md`.  The bitmap registers read back fine; the **read map is the write map reversed**, and
the old capture stored them in write order, which is what produced the static.  With a byte swap the
capture could work, and then direct writes *would* be carried per terminal.  Only the **tile** registers
are genuinely write-only (`assign DataOut_Tile_MAP_o = 8'h33;`).  Untested, and deliberately not
changed.

### None of this applies to the line engine anyway

Worth saying plainly, because it is the case Tempest actually cares about: **the line engine holds no
state that needs carrying across a terminal switch.**  Every line is self-contained — write the
endpoints, raise GO, poll, lower GO — and queued FIFO pixels carry **absolute 24-bit addresses baked in
at enqueue**, so they land correctly whatever happens to the registers afterwards.  The only
per-terminal state is `$FFCA` bit 0, which is already in `V.BordBack` and already restored by
`PullCore`.

So the push/pull objection above, which is real for bitmap addressing and configuration, **does not
bear on driving the line engine directly**.  What remains is the liveness race below, plus a very narrow
window in which a switch landing inside a 3.2 µs Bresenham walk could split one line across two base
addresses.

### Pausing on `S$WinBg` does not close the gap

Two independent reasons:

- **Ordering.**  The switch happens inside the driver at AltISR time.  `PushBuf` *and* `PullBuf` both
  run before the program is ever scheduled to see the signal.  A program can restore state on the way
  **in**; it can never save it on the way **out**.
- **No atomic "am I live?".**  A user process cannot test its liveness and write a register without a
  window between the two.  Check, get preempted, a switch happens, write — and the *foreground*
  terminal's bitmap now points at your memory, and stays wrong until its next `PullBuf`, i.e. the next
  switch.  Switches are human-initiated so this is rare, but it is silent and persistent when it lands.

**What would actually work** is the program keeping its own authoritative copy and reprogramming
everything on `S$WinFg`, accepting a flash while `PullBuf` paints the stale mirror first.  That is
exactly `SS.SprReg`'s design with the program doing the restore — and this project **deleted `SS.SprSet`
for precisely "a second writer the driver could not reproduce on a switch"**
(`docs/sprite-registration-plan.md`).  Reintroducing that shape is a decision to make with open eyes,
not a shortcut.

### The honest arithmetic — and it is not the transport

The tempting version of this argument is "direct writes replace a 474 µs call".  **That is wrong once
the call is batched**, and `SS.BmLine` is batched.  The real comparison, per frame:

| | transport | per record | interrupts |
|---|---|---|---|
| `SS.BmLine` batch | 474 µs, **once** | ~200-250 cycles ≈ **25-30 µs** at 8 MHz | **masked throughout** |
| direct from the program | none | the same instructions, so the same ~25-30 µs | enabled |

The per-record cost is the same work either way — the same seven register writes, the same `COMPLETE`
poll.  So direct access saves the **474 µs once per batch**, about 2.8% of a frame, plus another 474 µs
for each extra batch the FIFO pacing forces.  Useful, not transformative.

**The real difference is interrupt latency.**  `vtio`'s `CallGrfDrvGo` does `orcc #IntMasks` before the
flip and grfdrv runs masked for the whole call — the source notes "a driver cannot be preempted
mid-call".  So a batch of 100 lines holds interrupts off for **~2.5-3 ms**, and `SS.BmLine`'s maximum of
255 records would hold them off for **~7 ms, nearly half a frame**.  For a game pumping VS1053 samples
and counting 60 Hz ticks that is the number that matters, and it is an argument the transport figure
hides completely.

> **Per-record figures above are counted from the instruction stream, not measured.**  `ssbench` should
> measure `SS.BmLine` at several batch sizes early, because the slope matters more than the intercept —
> and the slope is what decides this whole question.

### If it is taken, what the driver needs

Not a free-for-all: a **"give me the line engine" call**, so the driver knows to stop using it and can
refuse `SS.BmLine` while the program holds it, and so `$FFCA` gets enabled once by the only code that
can reach it.  Handing it back on exit, and on `GF.TermGone`, is the same lifetime problem the tile and
sprite assets already have (`docs/next-session-prompt.md` item c) — which is an argument for settling
that rule first.

### Recommendation

**Measure before deciding, and do not design for this yet.**  Build Tempest on `SS.BmLine` as it
stands; harness job one already measures pixels drained per frame, and it should measure the batch slope
at the same time.  Reach for direct access only if the masked-interrupt window turns out to be what
breaks the frame — and if it does, the first thing to try is a **smaller batch**, which costs one extra
474 µs call and fixes the latency without giving up the ownership rule at all.

## 3. The spinner

A rotary encoder read as relative motion, plus fire, superzapper and start buttons. **Nothing in this
project has read a rotary control yet**, so this is the second bring-up harness.

- Establish what the intended physical control actually is — a real spinner, a mouse, or a joystick
  pretending to be one — and what the F256 offers for it: the joystick headers and the VIA lines behind
  them, NES/SNES at `$FF80`, the mouse interface at `$FEA0`. A mouse's X delta is the closest existing
  thing.
- **The platform contract is different from Joust's.** Joust needed a truthful *level* ("is this key down
  now?") because the game builds its own edge detector. Tempest needs an accumulated *delta* per frame,
  where a dropped count is a visible glitch and a missed sample is lost motion — not a stuck control.
  Sample it every frame in the frame loop, accumulate, and hand the game the count.
- A new `SS.*` call is warranted only if a driver has to do the counting (an interrupt-rate quadrature
  decode). If a 60 Hz read from the application is enough, do that and add no driver surface.
- Check direction, resolution (counts per revolution) and wrap behaviour in the harness, and decide the
  sensitivity mapping against the real machine — this is the control the whole game feels like.

## 4. Sound and maths

**Sound: two POKEYs, which the F256 does not have.** The options are guide section 8's, and the choice is
between them:

- **Sampled PCM through the VS1053**, exactly as Joust does — the whole of section 8 then applies
  unchanged, including the metered feed and the per-machine codec input. Samples captured from MAME's
  emulation with a host tool, MAME unmodified.
- **Synthesised on the PSGs, SIDs, OPL3 or the SAM2695** in page `$C4` — new work and new risk, but no
  absolute-address exception and a far smaller per-frame cost. Tempest's continuous tones and the
  zapper sweep suit a synth better than they suit short samples, and a per-sound **loop flag** is the
  minimum either way (Joust needed one for its transporter).

**Settle the chip before the output stage is built.** If this port ever uses the VS1053 as a 3D graphics
processor (guide section 8), it is not available for audio at all.

**Maths: Tempest's Math Box is a hardware multiplier/divider**, and the F256's integer math coprocessor
(guide section 7a, `$FEE0-$FEFF`) is the direct analogue: 16×16 unsigned multiply, 16/16 divide with
remainder, 32-bit add. If the projection maths turns out to be the frame's second cost after the lines,
that is where to look before hand-writing 6809 multiply routines — subject to 7a's two cautions
(it needs its own approved absolute-address exception, and nothing arbitrates the unit between processes).

## 5. 6502 to 6809

Joust's conversion was a transcription: same CPU, so arcade labels, order and comments survived intact and
every bug hunt was "compare against the listing". Tempest is a translation, which weakens that safety net
exactly where it was most useful. Compensations:

- Keep the original's labels, routine order and comments anyway, even where the instructions change
  completely. The docs cite line numbers into the original listing; that only works if the structure
  matches.
- Keep a **per-routine checklist** against the original listing — the equivalent of Joust's
  `tools/utilcheck.py`, which compared a harness's output against a model of the arcade routines and
  caught real errors before any of it ran on hardware.
- 6502 idioms that do not survive: zero-page as a general register file (the 6809's DP is one page and is
  already spoken for by the data-area convention — guide section 5), self-modifying code, and
  page-boundary-sensitive indexing. Each needs a decided form, once, written down before the first file.

## 6. Suggested order

This is guide section 14's **graphics first** principle applied to a game with no sprite sheets: what
Joust proved with an asset viewer, Tempest proves with the line engine and a captured display list on
screen. Same purpose — every primitive confirmed against a photograph before any game code exists, and an
instrument in hand for every bug after that.

1. **Line-draw harness** on hardware: one line, a box, a fan, a full frame's worth. Lines per frame; the
   go/busy protocol; what happens when the FIFO is overrun; erase strategy. *Everything else waits on
   this.*
1a. **A captured display list on screen**, replayed from a file by a standalone viewer — the first real
   picture, and the proof that the host-side capture and the geometry are right before any of the game
   runs.
2. **Spinner harness**: read it, print counts, confirm direction and resolution at 60 Hz.
3. **The two interface documents** (display list → line engine; sound events → sequencer) written from the
   original listing, with the numbers from steps 1-2 in them.
4. **Program skeleton**: data area, asset blocks, display set-up, frame loop, `SS.WSig` pause, terminal
   lockdown, clean exit — ported from `src/platform.a`, not rewritten.
5. **Graphics section** against a harness that replays a captured display list.
6. **Sound section** against a harness that fires every sound.
7. **Game logic**, in parts, each part confirmed on hardware before the next one starts.

## 7. What carries over from Joust untouched

- Guide sections 3-5 in their entirety: logical space and the module budget, `F$AllRAM` assets, the PIC
  rules, the DP/`DBASE` data-area convention, the static checker.
- Guide section 10 as *code*: pause on `SS.WSig`, terminal lockdown, clean exit on every path are built
  and proven in `src/platform.a`.
- Guide section 12's frame loop, and the per-frame request pool if the display list is built the same way.
- Guide section 13 wholesale — the working method and every tooling pothole.
- The settings-and-high-scores-as-a-file model, with an operator program editing the same file
  (`docs/joustadm.md` is the worked example).
