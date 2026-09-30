# Porting an arcade game to NitrOS-9 Level 2 on the Wildbits F256

**The generic guide: what is true of any game.** Everything here was paid for once already, on the Joust
port (a 6809 original, sprites and tiles) and then the Tempest port (a 6502 original, a vector display on
the line engine); none of it needs rediscovering.

Read it as: **sections 1-3** before deciding anything, **4-7a** while designing, **8-12** while building,
**13** before every hardware run. **Section 14 is how to start a new port** — the survey each game needs,
which goes in its own companion file — and **14a is the method when the original's CPU is not a 6809**.

**Per-game companions** (this guide stays generic; nothing game-specific belongs in it):

| File | Game |
|---|---|
| Tempest repo: `docs/port-tempest.md`, `docs/port-plan.md`, `docs/status.md` | Tempest — the survey, the translation from 6502, the line-engine display, the SIDs, the SOL clock; the worked example of section 14a |
| Joust repo: `docs/port-plan.md`, `docs/interfaces.md`, `docs/game-logic.md`, `docs/data-area.md` | Joust — the worked example of every convention here |

Source of the lessons: each repo's `docs/status.md` (hardware findings), Joust's `docs/interfaces.md`,
`docs/data-area.md`, `docs/game-logic.md`, `docs/grfdrv256-api.md`, and the two trees themselves. Where
this guide states a hardware fact it is one that was confirmed on a K2, unless it says otherwise. The games
are cited throughout as the evidence, not as the subject.

*This file is kept identical in the Joust and Tempest repos until it has a home of its own; edit both.*

---

## 1. The shape of the job

**It is a rewrite, not a port.** The arcade original (and any 8-bit home conversion of it) does its video
and sound in software on bare hardware: software blitters, compiled sprites, interrupt-time DACs, direct
MMU writes. On the F256 the hardware does that work, and the program is an ordinary OS-9 process. What
carries over is **the game logic and its data**, not its drawing.

The split that worked:

| Keep | Replace |
|---|---|
| Process scheduler, naps, per-object state | Blitter, framebuffer, sprite compiler |
| Physics, AI, waves, scoring, collision tables | Palette/interrupt plumbing |
| The display *request* seam (what to draw, where) | Everything on the far side of that seam |
| The sound *script* seam (priority, code, duration) | The sample player |
| Operator settings/high-score data model | The arcade operator screens, ROM/RAM tests, power-up screen |

**Find the two seams first and write them down before writing any code.** In Joust these were the DMA
request records (game logic → graphics) and `VSND` with a script pointer (game logic → sound).
`docs/interfaces.md` is that document; it took a day and saved weeks, because once it existed the graphics
and sound sections could be built and proven against harnesses *before* any game logic was converted.

**Rule that came out of stubbing things at the seam:** a seam routine may be stubbed only when nothing
reads back what it would have written. Joust's `CLIPER` clipped sprites, which the hardware now does — but
one call site read the clipped height back as its only "the bird is in the lava" signal, and stubbing it
made the lava death unreachable. Grep every field the stubbed routine writes.

## 2. Project layout that worked

```
docs/            interfaces.md (the seams), port-plan.md (architecture), data-area.md,
                 game-logic.md (conversion rules + per-part notes), status.md (living state,
                 hardware findings, open items), next-session-prompt.md
src/             one OS-9 program module: <game>.asm includes data.a, platform.a, and one
                 source file per arcade area, converted in place with arcade labels intact
tools/           host converter (assets -> .bin + generated .a tables), static checkers
assets/          converter output; loaded at run time from the SD card
nitros9_complete/nitros9   vendored NitrOS-9 tree; driver work lives here
```

Conventions worth repeating:

- **One program module, several test builds.** The same sources build `joust` and the harnesses
  (`jstgfx`, `jstsnd`, `jstexec`, `jstutil`, `jstbord`) via `-DGfxTest=1` etc. A harness that shares the
  platform layer tests the real code, not a copy of it.
- **Convert each arcade file in place**, keeping the original labels, order and comments, and cite line
  numbers of the source listing in the docs. Every later bug hunt is "compare against the listing", and
  that is only cheap if the labels still match.
- **The host converter owns all art and data transformation.** It emits both binary assets and
  assembler include files (header tables, glyph widths, message tables, tile alternates). Generated
  tables are byte-compared against the original build's tables where possible — Joust's message tables
  matched the CoCo build byte for byte, which retired a whole class of doubt.
- **One generated defs file is the contract between converter and assembler.** Joust's `jstassets.d`
  carries sizes, offsets, counts and the sound rate, so the module never hard-codes a number the
  converter decided. Change the art, rebuild, and the code follows — or fails to assemble, which is the
  point.
- **Assets share blocks at fixed offsets, and the makefile checks they still fit.** Several files live in
  one 8K block (`glyph57` at 0, `glyph35` at `$0E00`, icons at `$1C00`), so a `sizes` target that fails
  when any of them outgrows its slot is worth writing on the first day. Silent overlap is otherwise a
  hardware-only bug with no symptom near its cause.
- **Have the converter render previews** (Joust writes PNGs). Checking art on the host is free; checking
  it on the machine costs a card write and a photograph.
- **Make the machine-checkable rules makefile targets, not intentions:** the module size budget, the
  static PIC check, the asset slot sizes. A rule nobody can forget to run is worth three in a document.
- **`docs/status.md` is the handoff.** Sessions end and context is lost; the doc is what survives.

## 3. Level 2 is the environment, and its limit is logical space

**The machine, as of 2026-09-30** (re-check on every new core; section 13, "Which source to believe"):

| | Now | Before |
|---|---|---|
| CPU | 6809 at **12 MHz**, K2 and Jr2 (the K2 since 2026-09-27) | 8 MHz. Every µs figure in this guide was measured at 8 MHz unless it says otherwise; CPU-bound costs scale by 2/3, driver-call costs roughly so, and anything tied to the frame (the 60 Hz tick, a DMA fill's vblank wait) not at all |
| RAM | **1,792K** (224 blocks of 8K): `$00-$3F`, `$40-$9F`, `$A0-$BF`, `$D0-$EF` | 1 MB (128 blocks): `$40-$9F` was the flash window and expansion space |
| How | The kernel (`krnp2`, 2026-09-27) sets `FLASHDIS` when `MMU_IO_CTRL` bit 7 says the core has it, and maps `$40-$9F` as RAM; the block map covers all 256 blocks on both machines. **Confirmed working on hardware** (2026-09-30) | An older core, or an older kernel, still gives 1 MB — so treat an `F$AllRAM` failure as a real outcome, and don't design an asset set that needs the 1,792K without saying so |

What the extra speed and memory do **not** change: the eight-block logical space (below) is the same, so
the module budget, the window rule and `E$MemFul` are exactly as they were; more RAM means more assets
and bigger buffers outside the 64K, not a bigger program. And a faster CPU does not make a game faster by
itself — Tempest gained nothing from 8 → 12 MHz until a frame gate that quantised to ticks was fixed
(section 12.2).

- **Level 2 only.** Level 1 has no place in this; don't design for it.
- A process owns the full 64K except `$FD00-$FFFF`, in **eight 8K blocks**. Everything competes for those
  eight: the module, the data area, and every mapped window.
- **`E$MemFul` (error 207) from `F$MapBlk` means the eight blocks are full — not that RAM is exhausted.**
  It is reported with megabytes free. This was the single most confusing early failure.
- The budget that follows: with an 8K data area and **two 1-block windows** live at once, the module gets
  5 blocks less 768 bytes = **40,192 bytes**. Put that number in the makefile as a failing target on day
  one (`budget:`), and add a note when the module crosses 32,768. **Expect to hit it.** Tempest ended at
  40,191 of 40,192 bytes. What won the space back: test modes and diagnostics behind build flags
  (`make EXTRA="-DTSND"`, `-DDIAG`: the shipping build carries neither), and deleting machinery that a
  later design made unnecessary rather than leaving it switched off. Dropping to four blocks to free a
  window was costed (6,800 bytes out) and declined.
- **Never hold more than the two 1-block service windows at any moment, start-up included.** Joust once
  used two 2-block windows during start-up; that fits a 3-block module and not a 4-block one, so the
  failure appeared only when the module grew past 24,576 bytes — far below its real limit and nowhere
  near the code that caused it.
- **Assets live outside the 64K.** `F$AllRAM` blocks anywhere in the 1,792K (1 MB on an older core); map one in with `F$MapBlk`,
  read the file into it, `F$ClrBlk`. (**Known wart:** `F$AllRAM`/`F$DelRAM` from an application is
  technically a system call. The answer now exists in grfdrv256 — **`SS.GfxAlloc` `$D4` / `SS.GfxFree`
  `$D5`**, N consecutive blocks the program owns, confirmed on the K2 2026-09-20 — but neither Joust nor
  Tempest has moved to it; both still call `F$AllRAM`. A new port should use the SS calls.)
- **`F$AllRAM` searches the block map from the bottom up; `F$AlHRAM` from the top down.** Same allocator,
  opposite direction, and the convention is that graphics go high. **`F$AlHRAM` is system-state only** —
  registered `F$AlHRAM+SysState` in the Level 2 kernel's `svctab` — so an application cannot call it and a
  driver can, which is the other half of the allocation todo above. There is no addressing reason to prefer
  either end: VICKY and the DMA engine reach **all** of RAM on the rc16 (section 6a), so the choice is about
  keeping the low, contiguous space free for process and module loads, not about what the hardware can see. Only code, variables and address tables count against the budget.
  Relief when the module gets tight: move rarely-read tables into an asset block read through the same
  window as the graphics.
- **Never touch the MMU.** `F$MapBlk` / `F$ClrBlk` only, and always use the address returned in U —
  not an address you assumed.
- `F$AllRAM`, `F$DelRAM`, `F$MapBlk`, `F$ClrBlk` are user-callable on the max-RAM kernel; `F$AlHRAM` is
  system state.
- **`F$Sleep` X = 1 only yields the time slice.** A 60 Hz frame wait is `ldx #2`. X = n sleeps n−1 ticks.
  The 60 Hz tick is the VICKY start-of-frame interrupt. A loop built only on `F$Sleep` loses game time
  whenever a pass overruns its tick; section 12.2 is the answer.

## 4. Position-independent code

An OS-9 module is loaded where the system chooses. Joust's rule was: **no ORG, no forced address, no
absolute anything** (one approved exception: the VS1053's fixed-decode registers at `$FF50-$FF57`).

The conversion rules, which held for ~28 KB of 6809 arcade code:

1. `JSR`/`JMP label` → `LBSR`/`LBRA`. Calls through a vector table call the routine directly.
2. `LDX #label` → `LEAX label,PCR`. **LEA sets only Z** (and LEAU sets nothing) — check the branch after
   every site you touch.
3. **Addresses stored in RAM stay run-time addresses.** The module does not move while the game runs, so
   a pointer computed with `LEAX ...,PCR` and stored in a process block is fine, and `JMP [PPC,U]` stays
   as it is. Only the *sources* of those values change.
4. **Assembled tables holding addresses** go one of two ways:
   - **(a) offsets** — `fdb label-Tbl`, read as `LEAX Tbl,PCR` / `LDD n,X` / `LEAX D,X`. Use where the
     reader has a spare register.
   - **(b) relocated once at start-up** into the data area, where the arcade reads through the table with
     every register busy. Keep a **kind per word** in the fix-up list: module address, data-area address,
     constant, and 0 stays 0 (0 usually means "none"). Joust's `reloc.a` does this with a layout string
     per table (`M`/`D`/`K`/`B`).
5. **Data access goes through a base register held in direct page**, see section 5.
6. **Write the static checker early.** `tools/piccheck.py` reads the lwasm listing, classifies every
   symbol as code/data/constant and reports extended operands, immediates holding addresses, code labels
   in direct mode, `fdb` of an address, and indexed misuse. `make pic` must stay at 0 reports across
   *every* build, and a reviewed exception carries `pic:ok` in its comment. Give the checker a test file
   containing one fault of each class, so you know it still detects them.

## 5. The data area and base-register convention

OS-9 gives the process a data area and sets DP to its first page. That page is the scarce resource.

- **The module header's data-size field is what asks for the area**, and it must cover every variable,
  every relocated table *and* the stack, which OS-9 sets at the top. Joust asks for `$2000` — one block,
  with 1 KB of it stack. The original's `LDS #STACK` goes. Have a harness report the deepest stack use it
  ever saw (Joust's `jstexec` prints it): a scheduler with nested process calls is exactly where that
  number stops being guessable.
- **DP = page 0 of the data area, never changed.** Arcade base-page variables keep their names and stay in
  direct mode — unchanged source. Put all data definitions *before* any code so lwasm picks direct mode.
- **`DBASE` (2 bytes in page 0) holds the data area address**, stored from U at start-up. It is the only
  base register; the game logic has no second register to spare.
- **Near vs far:** a variable is near (page 0) if anything reaches it while U is *not* the data base —
  game logic and the services it calls. Everything else is far, at a fixed offset.
- Far access patterns: `LDX <DBASE` then `LDD var,X`; and a `LEAD reg,label` macro (load `DBASE`, then
  `LEA`) for taking an address. `PSHS`/`PULS` around a site is safe because pushes don't touch CC.
- **Coordinate-indexed RAM tables** are the awkward case: `LDX coord` / `LDA TBL,X` becomes
  `LDD coord` / `ADDD <precomputed_table_pointer>` / `TFR D,X` / `LDA ,X`. Precompute the pointer in page 0.
  Every such site must be checked by hand, because the code after it can no longer use X as the coordinate.
- **The platform layer runs with U = data base** and enters the game's scheduler with `PSHS U` /
  `LBSR` / `PULS U`, so its own variables can be far at no cost.
- **Signal intercept gets U = data base** and the handler does nothing but `STB SIGCODE,U` / `RTI`.
  It must not rely on DP.
- Settings/high scores: Joust kept the arcade's CMOS addresses and made the storage a **file**
  (`cmos.dat`, one byte per nibble address), opened for update at start-up, read/written through the two
  arcade access routines with a seek. No RAM copy, so the data area stayed free — and an operator program
  (`joustadm`) edits the same file. Keep *all* file access behind those two routines; then moving the
  storage later is a two-routine change.

## 6. Graphics: let the hardware do it

Three layers, and that is the hard budget: **`SS.PScrn` codes 0-2 are bitmaps, 4-6 are tile maps; layer 0
is in front.** Sprites sit on their own sprite layer, selected per sprite (CTRL bits 4:3), and interleave
with those layers.

Joust's arrangement, which reproduced arcade behaviour including its clipping:

| Front → back | Contents |
|---|---|
| bitmap 0 (layer 0) | opaque "floor band" below the clip line — this is what cuts sprites, doing in hardware what the arcade did in software |
| sprite layer 1 | every moving object |
| bitmap 1 (layer 1) | text, scores, effects, one-colour silhouettes |
| tile map 0 (layer 2) | the static background |

Hardware facts (confirmed on rc16 unless marked):

- **Sprites:** 128 records of 8 bytes at `$C0:$1300 + 8n` — CTRL (bit 0 enable, 2:1 CLUT, 4:3 layer,
  6:5 size 00=32 01=24 10=16 11=8), 24-bit address, X and Y as 16-bit. **The visible screen starts at
  (32,32)**, and **sprite 0 draws on top**.
- **Tile sets:** 4 bytes at `$C0:$1180 + 4n` — CFG, then address hi/mid/lo. *The manual's address-first
  table is wrong for these registers.* **CFG's SQUARE flag is bit 3, not bit 7** — the core takes CFG from
  the low nibble of that byte and reads bit 3; bits 7:4 are wired to nothing. Every program in this project
  writes `$80` and gets a linear sheet because bit 3 is clear, which is what they wanted. *Square sheets are
  unproven on hardware.* Linear pixels are one tile after another: tile n at n×64 (8×8) or n×256 (16×16).
- **Tile maps:** 12 bytes at `$C0:$1100 + 12n` — CTRL (bit 0 enable, bit 4 TILE_SIZE 1 = 8×8), address
  hi/mid/lo, SIZE_X, SIZE_Y, X, Y (16-bit, high byte first). **SIZE_X/Y are 10-bit — up to 1024 tiles.**
  Map entries are tile number, then an attribute byte: **tile set in bits 2:0, CLUT in bits 5:3**, collision
  enable in bit 6. **Three tile maps, not four** — the core has a fourth set of registers but no way to
  display it. To turn a map off, clear CTRL bit 0 and re-send; don't zero the record, or you throw away the
  address and size too.
- **Bitmaps:** control at `$C0:$1000` (+8 per bitmap), 24-bit start address at +1..+3; 320×240 8bpp,
  one byte per pixel, `start + y*320 + x`.
- **CLUTs** at `$C1:$1000 + $400·n`, entries **B, G, R, A**. Index 0 is transparent in sprites and
  bitmaps, so "erase" means writing 0 — and an opaque black needs a second entry set equal to entry 0.
- **The tile layer draws 8 px left of the bitmap layers at zero scroll** on rc16. Real, measured; Joust
  compensates in the converter (`--tile-dx`). Check it again on new hardware rather than assuming.
- 320×240 with a 304-px arcade playfield centred by an 8-px offset looks like clipping in a photograph and
  is not. Measure against the assets before "fixing" an edge.

**Every call `grfdrv256` answers**, from its own dispatch tables (`GetSttTbl`, `SetSttTbl`, 2026-09-30).
`docs/grfdrv256-api.md` (Joust repo) has the register layouts, and `docs/tile-api.md` is a standalone
reference for the tile calls. **The dispatch tables are the authority**: the API doc still lists `$D0` as
`SS.KyDwn`, which is gone.

The calls the projects added (the ones used: **J** Joust, **T** Tempest):

| Code | Call | Get/Set | What it does | Used |
|---|---|---|---|---|
| `$C6` | `SS.LiveKeys` | Get | key sense bits, the six ordinary keys held down; empties the input buffer | J T |
| `$CF` | `SS.ClutWrite` | Set | CLUT entries from a buffer | J T |
| `$D1` | `SS.SprPush` | Set | put a range of the registered sprite table on screen | J |
| `$D3` | `SS.SprReg` | Set | register this terminal's sprite table, or give it up | J |
| `$D4` | `SS.GfxAlloc` | Set | N consecutive RAM blocks, owned by the program (section 3) | — |
| `$D5` | `SS.GfxFree` | Set | give them back; refuses a driver-owned bitmap's blocks | — |
| `$E3` | `SS.BmAlloc` | Set | allocate a bitmap and define it; the driver owns the blocks | — |
| `$E4` | `SS.BmBlk` | Get | a bitmap's first block and control byte | J T |
| `$E5` | `SS.BmClear` | Set | fill a bitmap on the DMA engine, asynchronously (section 6a) | T |
| `$E5` | `SS.BmClear` | Get | busy or idle; also R$Y:R$U = the DMA's destination (below) | — |
| `$E6` | `SS.BmDef` | Set | point a bitmap at a block + offset the program owns | — |
| `$E7` | `SS.BmLine` | Set | draw a batch of up to 255 line records on the line engine (section 7) | T |
| `$E7` | `SS.BmLine` | Get | pixels still queued in the line engine's FIFO (built, never exercised) | — |
| `$EA` | `SS.BmKill` | Set | undefine a bitmap; free its blocks only if the driver allocated them | — |
| `$ED` | `SS.BmCfg` | Set | a bitmap's enable, CLUT, HIRES4 (640×240 4-bit) and palette group; `$FF` = leave alone | T |
| `$EE` | `SS.TsSet` | Set | define a tile set | J |
| `$F4` | `SS.TmSet` | Set | define a tile map | J |
| `$F8` | `SS.TmScrl` | Set | scroll a tile map | — |
| `$13` | `SS.Joy` | Get | modes 2-6 added: both sticks in one call; NES and SNES pads (section 9) | J T |

The older calls it keeps (CoCo and early-Wildbits codes, by name): **Get** `SS.ScSiz`, `SS.ScTyp`,
`SS.KySns`, `SS.Mouse`, `SS.DScrn`/`SS.MCR`, `SS.FntChar`, `SS.Palet`, `SS.FBRgs`, `SS.DfPal`; **Set**
`SS.AScrn` (both games get their bitmaps this way), `SS.DScrn`/`SS.MCR`, `SS.PScrn`/`SS.Layer`, `SS.FScrn`,
`SS.Palet`, `SS.DfPal`, `SS.FntChar`, `SS.TermSel`.

Not grfdrv256's, though a game calls them on the same path: **`SS.WSig` (`$E1`) and `SS.Relea` are
vtio's** (grfdrv256 stages the switch, vtio sends the signal: section 11); `SS.Opt` and `SS.Ready` are
SCF's; **SOLdrv** (`/fSOL`, `SS.SOLIRQ` and `SS.SOLMUTE`) is a separate driver (section 12.2).

Everything else in the code space is reserved and returns `E$UnkSvc`. `$D0` is free (it was `SS.KyDwn`,
folded into `SS.LiveKeys`) and is the approved code for `SS.MsDelta`, mouse motion as counts, which is not
in the driver yet (Tempest asks for it and runs without). **Reserved names without handlers:**
`SS.ClutLoad`/`ClutCopy`/`ClutRead` `$CC-$CE`, `SS.TsAlloc` `$F0`, `SS.TsKill` `$F3`, `SS.TmAlloc` `$F6`,
`SS.TmKill` `$FD`. **Spare:** `$D6-$E0` (the per-sprite codes the registered table made unnecessary),
`$E8`, `$E9`, `$EB`, `$EC`, `$EF`, `$F1`, `$F2`, `$F5`, `$F7`, `$F9-$FC`, `$FE`, `$FF`. Taken by others in the same range: `$C7-$CB` VRN,
`$D2` sc16550's `SS.DvrID`, `$E2` DriveWire's `SS.Fuji`.

**Read what a call hands back, not only what it takes.** `GetStat SS.BmClear` also returns the DMA's
destination in R$Y and R$U, a diagnostic; a program that kept its data base in U across the call did not
start at all, and the host model had passed it because it left U alone. Grep the driver for its `R$`
writes in the call's routine, save what you need across the `os9`, and make the host model do the same.

**Two older codes have names that describe nothing they do here**, because they were adopted from the CoCo:
`SS.PScrn` is **`SS.Layer`** (which source feeds one display layer) and `SS.DScrn` is **`SS.MCR`** (the VICKY
master control register, Get and Set). Both spellings work — the CoCo names stay valid because the CoCo3 tree
uses those codes with their CoCo meanings — but write the new ones.


Patterns that fell out of it:

- **The application owns tile map, tile set and bitmap memory** (`F$AllRAM`). VICKY reads it live, so edits
  are plain writes into a mapped block and need no call at all. Only *register* changes need a call.
- **Register your sprite table, then push only what changed.** The program keeps the only copy of its
  8-byte records; `SS.SprReg` tells the driver which blocks it lies in, and `SS.SprPush` sends a range of it.
  There is no driver-side copy, so a terminal switch restores the screen out of your own memory. Joust marks
  the lowest and highest record each frame writes and sends that one range — measured on hardware at
  **2.5 records changed a frame over a span of 6.4, sent as 9.0**, which costs 547 µs against 1,074 µs for an
  unconditional 128-record send. A call costs ~480 µs before it moves a byte and ~7.4 µs a record (8 MHz), so **one
  call over a range beats one call per group of changes** until the groups are very far apart.
- **Registration is required and there is no other way in.** A call that pushed records from a caller's
  buffer would be a second writer the driver cannot reproduce on a switch, which is why it was removed. One
  source of truth, or none.
- **Slot assignment by object index** (process block index × 2) rather than an allocator. Stacking order
  then follows slot number, which is as arbitrary as the arcade's paint order — accept the difference and
  write it down.
- **Kill the slot when the object dies.** Games often rely on a screen clear to remove stale images.
- **A hidden terminal needs no sprite call at all** — write your own table and the switch back will show it.
  (The old 32-record background limit is gone with the driver's shadow.)
- **Know what survives a terminal switch.** The driver reprograms the bitmap, tile map and tile set registers
  from per-terminal mirrors, restores the graphics CLUTs from its 16K switch buffer, and fills the sprite
  registers from the incoming terminal's **registered table**. A terminal that has registered nothing and set
  no tile map gets zeros, which read as "off" — so your graphics cannot appear over someone else's shell.
  You re-send nothing after a switch. *A display that is correct until you Alt-arrow away and back used to be
  this; it should not be any more, so treat it as a bug and say so.*
- **Switch it off before you free it.** VICKY reads your tile pixels, map cells, sprite records and bitmap
  pixels **continuously, by physical address**, and has no idea your program exited. Before freeing a block a
  register points at: `SS.TmSet` with CTRL bit 0 clear, `SS.TsSet` with address 0, `SS.SprReg` with R$U = 0,
  `SS.FScrn` for a bitmap. Otherwise the screen draws whatever the next owner of that block writes. Joust
  makes `Q` the only exit for exactly this reason (section 10). **A program killed by an untrappable signal
  will leave its registers live — there is no guard against that today.**
- Draw text/effects as **one colour through a mask** into a bitmap; the same routine does glyphs,
  silhouettes and debris.
- **Palette model:** keep the original's palette RAM in its own format, and convert only the changed
  entries at the frame commit into one `SS.ClutWrite`. Joust uses MAME's resistor-weighted levels for the
  original board, which is why the photographs match.

Two drawing bugs that are worth knowing by name, because both classes recur:

- **Sizing an erase box from the wrong object.** The clear box was sized from the cliff art, but the thing
  drawn was the cliff *plus a one-pixel-shifted copy*, and the debris that followed was wider still. Rule:
  size the erase from the union of everything that was drawn there, and measure it from the assets.
- **A stack-frame offset that ignored the return address** (`3,s` reached by `LBSR` instead of a fall-through)
  put every filled box at a wrong position — one bug, three unrelated-looking symptoms across the screen.

## 6a. The DMA engine (read from the RTL 2026-09-18; used by Tempest through `SS.BmClear`)

A block fill/copy engine at `$FEC0-$FED7` — fixed decode, so the same absolute-address question as the
VS1053 applies (section 7a). Control at `$FEC0` (bit 7 START, bit 3 INT_EN, bit 2 FILL, bit 1 2D, bit 0
ENABLE), fill byte and a BUSY status bit at `$FEC1`, a source and a destination address, a byte count for
1D, and for 2D a width, a height and **separate source and destination strides** — so a 2D fill clears a
rectangle inside a 320-wide bitmap without touching the rest of the line, and a 2D copy blits a sub-image
between two bitmaps of different widths.

That makes it the obvious tool for clearing a bitmap, blitting a background or scrolling. Three facts
decide whether it can be used in a frame loop, and all three are now read from the FPGA source rather than
guessed:

- **It reaches all of RAM.** Source and destination are **24-bit** (`source/TinyVKY_DMA_Reg_Block.v:18-19`),
  confirming the FPGA developer directly (user, 2026-09-18) and `docs/port-plan.md`'s background facts. The
  F256 manual's 19-bit SA/DA fields and its "first 512 KB" rule describe the base machine, **not this one**
  — the source-authority rule in section 13, and the live example of why it exists.
- **It runs only in a window inside vertical blanking.** The transfer waits on
  `VDMA_Transfer_Time_Available`, which the video timing generator defines as a vertical-blanking window
  (`source/VideoTimingGenerator.v:274-279`), with a late-retrigger path that the controller's own comment
  bounds at "end of line 42" (`source/TinyVKY_DMA_Controller.v:583-597`). A transfer asked for mid-frame
  **waits for the next vblank**; it does not start when you write START.
- **It stalls the CPU while it runs.** The controller goes through a `CPU_STOPPED` state and drives the
  6809's ready line from the transfer window (`TinyVKY_DMA_Controller.v:311, 597`). So the cost is not
  "free background copying" — it is CPU time you do not get, taken inside the vblank.

**What that means in practice:** the DMA is a good fit for a whole-screen clear or a large blit *once per
frame, sized to fit the vblank window*, and a bad fit for many small transfers scattered through a frame.
Measure how many bytes one vblank actually moves before designing around it. Joust does all of its bitmap
work with the CPU through a mapped window until 2026-09-22, when the FPGA developer fixed the DMA
handshake; since then it clears with one `SS.BmClear` call, wait mode 7, which suits a game that clears at
a point where waiting costs nothing. **Joust keeps the pattern that bit Tempest** — any `SS.BmClear`
failure latches its CPU fallback for the run — and is safe only because it waits for each fill, so it
never arms a second while one is pending.

**Tempest is the worked example: `SS.BmClear` clears the hidden 76,800-byte line bitmap once per game
frame**, 16-bit, halting the CPU about 384 µs (the DMA's time, not the CPU's: unchanged at 12 MHz). What it cost to learn:

- **Arm it, don't wait for it.** The fill starts at once only if armed before line 42; armed later, it
  waits for the next line 0. Wait mode 7 (poll until done) called mid-frame therefore slept most of a
  frame and **lost a tick every game frame** (10.9 frames a second on the K2; 15.4 once fixed). Arm with
  wait mode 0 in the logic pass and draw a tick later: the fill has run by then, because it halts the CPU
  until it is done, so no "is it finished?" call is needed either (Tempest removed its `BmWait`).
- **`E$DevBsy` means a fill is still pending, not that the engine is dead.** Tempest fell back to a CPU
  clear on any error and latched the fallback for the run. Two logic passes in one frame (a dropped drawing
  plus a caught-up clock) made the second arm answer `E$DevBsy`, and from then on every frame cleared 80K
  with the CPU: the game fell to a third of its speed "after a few games", intermittently, and a restart
  cured it. **Take `E$DevBsy` as success when it is the same bitmap; latch a fallback only for a real
  failure; and count every fallback where the diagnostics can print it** (section 13).
- The host model has to model the timing too (armed after line 42 → next tick; the CPU halt; busy until
  run). While it had the fill instant, it predicted none of the above.

## 7. The hardware line-draw engine (read from the RTL 2026-09-18; Tempest draws everything with it)

Joust never needed it. Any game that draws lines does — a vector game entirely, but also borders, wire
frames, radar, starfields and score frames that would otherwise be hand-plotted pixels.

### 7.0 As used: `SS.BmLine`, and what changed since the RTL reading

**Applications do not drive the registers below.** `SS.BmLine` (`$E7`) takes a batch of 8-byte records
(X0, X1, Y0, Y1, colour; 16-bit X) — up to 255 a call, R$U the count in and the count drawn out — and does
the GO/COMPLETE handshake, the range check and the FIFO pacing in the driver. A call costs ~450 µs (8 MHz) before
its first record, so **records per call is the number to maximise**: Tempest sends 1.2-2 calls a game frame
of ~110-160 records each. The call returns short when the FIFO nears full; count short returns in the
diagnostics (Tempest's stayed at 0 over thousands of calls, which is what said a bigger FIFO would buy
nothing).

What the cores have changed since the reading below — **re-read the RTL for the core you have**:

- **Early cores dropped pixels** (gaps that moved each run; DMA and CPU writes clean). Fixed by the FPGA
  developer; a clear-then-fan harness (Tempest's `bmtest` `C`+`L`) is the check to repeat on every new core.
- **The FIFO is 8,192 pixels, and its full flag is now connected**: the walk stalls instead of losing
  pixels. The driver's `LD.Depth` must match the core, or it uses half the FIFO.
- **HIRES4: 640×240 at 4 bits a pixel**, per bitmap (control byte bit 4; bits 7:5 a palette GROUP, so a
  pixel's CLUT entry is GROUP×16 + nibble, nibble 0 transparent), set with `SS.BmCfg`. Same 76,800 bytes
  and stride as 320×240 8-bit, so memory and clears are unchanged. The engine takes X to 639 and each
  pixel becomes a read-modify-write of its nibble. **15 colours a plane** is the design constraint. Tempest
  runs lines and text on 640 planes ("looks better", and the lines look more like a vector monitor); its
  text glyphs had to be re-rendered at 640 with 1-dot strokes and placed in 640ths, or they looked thick
  and ran together.
- Some things are **resolution, not faults**: Tempest's logo is 19 outlines a row or two apart, which at
  240 rows merge into a smear. The host renderer at the same resolution reproduced the photograph exactly,
  which settled it before anyone went looking for a bug.

### 7.1 The RTL reading (2026-09-18)

**Everything below is read from the FPGA source** (`fpga-6809-cores-staging/`, read-only: `source/LineDraw.v`,
`source/TinyVicky_BM_Registers.v`, `source/TinyVickyCoreModule.v:444-473`, and the FIFO's `.xci`), for the
cores then in use — K2 `Core2X_B0C` and Jr2 `Core2X`, before the changes in 7.0. The RTL is authoritative
about what the hardware does; a harness is still what tells you how fast it does it.

#### Registers, `$C0:$1080-$1087`

**Writing** (`TinyVicky_BM_Registers.v:100`, register index = address bits 2:0; field slicing from the
64-bit block at `:35` and `TinyVickyCoreModule.v:447-458`):

| Offset | Write |
|---|---|
| `$1080` | control: bit 0 enable, **bit 1 GO**, bits 3:2 target bitmap (00 = BM0, 01 = BM1, 10 = BM2), bit 4 reset FIFO |
| `$1081` | colour — the 8-bit CLUT index written to each pixel |
| `$1082` / `$1083` | X0 **high** (2 bits used) / X0 **low** |
| `$1084` / `$1085` | X1 high / X1 low |
| `$1086` | Y0 (8 bits — there is no high byte) |
| `$1087` | Y1 |

**Reading is not the same map** (`:136-143`), and this is a trap:

| Offset | Read |
|---|---|
| `$1080` | bit 7 = **status** (below), bits 6:0 = the control byte as written |
| `$1081` | colour |
| `$1082` / `$1083` | **pixels still queued in the FIFO**, high (5 bits) / low — 0-4096 |
| `$1084` / `$1085` | X1 low / X1 high — *swapped* against the write map |
| `$1086` / `$1087` | the Y pair, also swapped: reading `$1086` returns what was written to `$1087` |

So the coordinate read-backs are not a way to check what you set, and the two bytes at `$1082`/`$1083`
are a **pixel counter, not the X0 you wrote**.

#### Behaviour

- **Bit 7 of `$1080` is COMPLETE, not BUSY.** The core wires the register's status bit to the module's
  `Complete_o`, which is `state == DONE`, and leaves `Busy_o` unconnected (`TinyVickyCoreModule.v:451-452`).
  DONE is held **until GO returns to 0** (`LineDraw.v` FSM). So the sequence is: set the endpoints and
  colour, raise GO, **poll until bit 7 is set**, then clear GO — which returns the engine to IDLE and
  clears bit 7. Polling "until busy clears" is the wrong test and would pass immediately, before the line
  was drawn.
- **GO is level-sensitive through the FSM, so it must go back to 0 between lines.** DONE → IDLE is the only
  path back, and it is gated on GO being low.
- **Endpoints are range-checked in hardware and an out-of-range line is silently dropped.** The FSM leaves
  IDLE only if `x0`, `x1` are in `[0,320)` and `y0`, `y1` are in `[0,240)` (`LineDraw.v:76-80, 90`). No
  error, no pixels, no status bit — nothing happens at all. Clip in software.
- **Bresenham, one pixel per 100 MHz clock**, into a **4096-entry FIFO** of {colour, 24-bit address}
  (depth from `LINEDRAW_AddyPixel_FIFO.xci`). Generating pixels is essentially free; getting them into
  memory is the part that costs.
- **The address is `bitmap_start + y*320 + x`** (`LineDraw.v:147-150`), so the **stride is hard-wired to
  320** and the target bitmap's own start address register supplies the base. A bitmap of any other width
  cannot be drawn into.
- **The FIFO's `full` flag is not connected and writes into it are unconditional** (`LineDraw.v:168-176`).
  Queue more than 4096 pixels before they drain and the excess is **silently lost**. The count at
  `$1082`/`$1083` is how software stays under that, and it is the one number worth reading every frame.
  *(Superseded on later cores: 8,192 deep, full flag connected, the walk stalls — 7.0.)*
- **The FIFO drains to memory in a per-scanline slot**, not immediately: the core turns the line-draw
  effect on in its slot rotation and off again at the end of the line window
  (`TinyVickyCoreModule.v:895-915`). So pixels land over the following scanlines, and **the real
  throughput question is drain rate per frame** — which the count registers measure directly, with no
  scope and no guesswork.

#### So the bring-up harness was

1. One line at known endpoints; photograph it. Then a box, then a fan.
2. Watch `$1082`/`$1083` fall after a line is queued: that gives **pixels drained per frame**, the number
   the whole design rests on.
3. Queue deliberately more than 4096 pixels and confirm what is lost, so the budget is known rather than
   assumed.
4. Check an out-of-range endpoint really does nothing, and that the GO-low step is required.
5. Only then decide whether the engine belongs behind a new `SS.*` call or is driven from the application.
   It is in the mapped device page `$C0`, reached through `F$MapBlk` like every other VICKY register —
   **no absolute-address exception is needed**, and none should be asked for.

## 7a. The other coprocessors

Two more accelerators exist on the board. They are worth knowing about before writing a maths routine by
hand, especially for a game with rotation, projection or scaling. **Tempest uses the integer unit** — the
divide for its perspective (it replaces the arcade's Math Box) and the multiply in its vector interpreter —
as an approved absolute-address exception, with interrupts masked around each use. The floating-point
registers are still unused.

- **Integer math coprocessor**, fixed decode at `$FEE0-$FEFF` (F256 manual chapter 19, and the rc16 memory
  map lists the same range). Three independent units, each "write both operands, read the result":
  - **16×16 unsigned multiply** — operands `$FEE0-$FEE3`, 32-bit product at `$FEF0-$FEF3`;
  - **16/16 unsigned divide** — denominator `$FEE4`, numerator `$FEE6`, quotient at `$FEF4-$FEF5`,
    remainder at `$FEF6-$FEF7`;
  - **32-bit adder** — operands `$FEE8-$FEEF`, sum at `$FEF8-$FEFB`.

  All big-endian byte pairs, so a 6809 `STD`/`LDD` at the high byte moves a 16-bit value in one
  instruction. The 6809 has an 8×8 `MUL` and no divide at all, so a 16-bit multiply or any division is
  where this pays: Tempest's software divide was ~900 cycles against the coprocessor's handful, and the
  multiply took its interpreter from 21 to 17.5 ms a frame.
  - **Divide by zero is undefined** anywhere in the documentation: test for it and supply the original's
    answer yourself. The remainder is right from rc14 on (`JR_Math_Block.v`). Reading the quotient one
    instruction after writing the dividend is what NitrOS-9's own `wild.asm` does; nobody has proved the
    latency on hardware, so keep a software fallback behind a build flag (Tempest's `SOFTDIV`, `AVGSWM`).
  - An original's special-purpose maths hardware (Tempest's Math Box) is best matched **exhaustively on
    the host**: every input it can see, run in C against MAME's model, including its overflow behaviour.
    Tempest found a 16-bit overflow region the game really reaches (objects near the eye) and kept MAME's
    exact slow path for it.
- **Floating-point registers** at `$FFE0-$FFEF` per the rc16 memory map. Nothing in this project has read
  them and the layout is not in the F256 manual — look it up on the Wildbits site and prove it with a
  harness, as with the line-draw engine.

Two cautions:

- **These are fixed-decode absolute addresses**, the same class as the VS1053 at `$FF50-$FF57`. Using them
  means asking for another named exception to the no-absolute-I/O rule and teaching the static PIC checker
  about it (Tempest's `piccheck.py` knows `$FEE0-$FEFF`). Ask before building on them; don't assume the
  VS1053 precedent covers everything.
- **They are global, not per-process.** Nothing arbitrates them: an interrupt or another process that used
  the same unit between your write and your read would corrupt the result. Before relying on one in a
  frame loop, establish whether anything else on the system touches it, and whether the sequence needs
  protecting. Tempest masks interrupts per use, and its host test model fails any coprocessor access made
  with interrupts unmasked, so a missed mask cannot slip through.

## 8. Sound

Joust's answer was **one continuous PCM stream through the VS1053**, its registers at `$FF50-$FF57`
written directly. That is the project's single approved absolute-I/O exception, granted because the decode
is fixed and no MMU is involved.

**The VS1053 is not the only option, and it may not even be free.** The others (Tempest plays on the SIDs,
section 8.4; the rest are unexercised):

- **SAM2695 (Dream)** — a General MIDI synthesiser: notes and instruments over a MIDI stream rather than
  samples, so it costs almost no CPU per frame and no sample assets at all. The natural fit for music, and
  for sound effects that can be expressed as notes.
- **OPL3 (YMF262)** at `$C4:$0180-$0183` — FM synthesis, **write-only, no status or IRQ**, so the driver
  must keep its own shadow of every register and respect the chip's write timing itself.
- **SID ×2** at `$C4:$0000` (left) and `$0100` (right); `$0080` ("mono") is not a third chip but writes
  both at once (`SID_OPL3_Interface.v`: two `sid6581` instances, `wren` = left|mono and right|mono), so six
  voices in all — soft SIDs in the FPGA. Best where a
  sound is a waveform-and-envelope description rather than a recording.
- **PSG ×3** at `$C4:$0200-$0217` — square waves and noise, the cheapest of the lot, and a close match for
  arcade hardware of that generation.

On the older cores all four live in the mapped device page `$C4`, reached with `F$MapBlk` like the VICKY
registers. **Newer cores add a fixed-decode sound block at `$FF90`** — `$FF91-$FF93` the PSGs (left, both,
right), `$FF94-$FF97` the OPL3's two address/data pairs, `$FF98` a SID selector and `$FF99` SID data
(section 8.4) — which is an absolute-address exception like the VS1053, but a far cheaper one to use than
a mapped page (8.4 says why). Which of the two your core has is an RTL question.

**Why this matters beyond taste:** someone has worked out how to use the VS1053 as a **3D graphics
processor** (how is not known here). If a port ever wants that, the VS1053 stops being available for
audio and the sound design has to move to one of the chips above. That is a reason to keep the sound
section behind the script/sequencer seam (below) and free of VS1053 assumptions: the sequencer, the
priority rules and the per-frame tick are the same whatever is on the far side, and only the output stage
changes. If a port is considering the 3D trick, settle the sound chip **before** building the output
stage, not after.

### 8.1 The sequencer, whatever the chip

- **Keep the original's sound *sequencer* exactly**: priority byte, (code, duration) pairs, continuation
  bit, one-frame start delay, one sound at a time. Run it **once per frame before the game pass**, where
  the arcade ran it; running it after the pass silently loses the start delay — a real bug, found by
  reading the arcade's frame order after the fact.
- Keep the arcade's accept rules with it: a high-priority band that always gets through, a low band
  dropped while the game is over, and a new sound of lower priority than the one still timing dropped
  outright.
- The sequencer names a **sound code**; the output stage turns a code into audio. Keep that boundary
  clean and the chip choice stays reversible (section 8's opening).

### 8.2 Driving the VS1053 (`src/snd.a`, the worked example)

The bridge is eight fixed-decode registers at `$FF50`: control (`b0` SCI start, `b1` read, `b2` fast,
`b3` reset, `b7` busy), SCI register number, two SCI data bytes **high byte first**, a FIFO status byte
(`b7` empty, `b6` full, `b2:0` count bits 10-8), a FIFO count low byte, and the **SDI FIFO data port —
2,048 bytes**, drained to the chip as its DREQ allows.

**The SCI protocol has one trap:** START is **edge-triggered**. Write the register number and data, then
write 0 to control, *then* the start bit — going straight to the start bit does nothing. Then wait for
`b7` busy to clear. Joust's wait is a **short spin (4096 tries) and then one look per 60 Hz tick for up to
two seconds**, returning `E$NotRdy` on timeout, so a missing or wedged chip degrades to a silent game
instead of a hang.

**Start-up, in order** (each step's failure must leave the program running silent, not dead):

1. **Reset**: set the reset bit, sleep ~2 ticks, clear it, sleep ~3 ticks. The chip needs real time here;
   this is not a busy-wait.
2. **Detect how the chip booted.** Read GPIO_IDATA (`$C018`) through the SCI WRAM window (write
   `WRAMADDR`, read `WRAM`). `GPIO & 3 = 2` — GPIO1 high, GPIO0 low — means it came up as a **MIDI
   synth**, which is what the Jr2 does.
3. **If so, load the switcher plug-in** (the table from Roger Taylor's `vs.asm`, a run-length register
   script) over SCI, sleep ~6 ticks for the restart, then **verify**: `AUDATA` must read `$1F40`, the idle
   decoder. **The plug-in is lost on every reset**, so this runs after every reset, not once per boot.
4. **Decoder set-up**: `MODE` = `$0800` (SM_SDINEW), `STATUS` = `$0040` (analog drivers on), `CLOCKF` =
   `$6000` (3.0×), a ~6-tick sleep for the new clock, then `VOL`.
5. **Push a 44-byte WAV header into the FIFO** with **`$FFFFFFFF` in both length fields** — an endless
   stream. Everything after it is raw sample data for ever; the chip is never told a sound ended.
   One header per supported format (Joust keeps a table of five: 8-bit mono, 16-bit mono, 16-bit stereo,
   and two double-rate variants), selected by a variable so the format can be changed for a test without
   rebuilding the idea.

**The pump, once per frame — the part that took the longest to get right:**

- **Meter it: send exactly one frame's worth of samples, whatever the FIFO reports.** Do *not* top the
  FIFO up to a target. Topping up feeds the chip as fast as it will take it, which fills the VS1053's
  *own* internal buffer behind the bridge FIFO, and the delay from `VSND` to sound goes to **about a
  second**. Metered feeding fixed it outright: no clicks, clean loops, and a response you cannot fault
  by ear.
- **Carry the fractional part; never divide per frame.** Joust keeps a budget: add the sample rate
  (6006) each frame, subtract 60 while the budget is ≥ 60, counting one byte per subtraction. That sends
  100 or 101 bytes a frame and is exact over any span — 6006 samples per 60 frames with no rounding drift
  and no 32-bit arithmetic.
- **Add a one-time cushion after a start** (Joust: 128 bytes) so the very first frames cannot underrun,
  then never top up again.
- **Silence is a sound.** When nothing is playing the pump sends the same metered count of silence bytes,
  so the stream never stops and the chip never re-syncs. Code `$00` switches to silence; the "no change"
  code changes nothing.
- **Per-sound loop flag** in the sample table, for sounds the game expects to continue (Joust's
  transporter). A looping sample restarts inside the same frame's fill.
- The sample data lives in an `F$AllRAM` block, mapped through the *one* service window (section 3), and
  a fill splits at the block boundary. Format conversion (8→16-bit, mono→stereo) happens on the way out,
  which is what makes a format a variable rather than a rebuild.
- **Instrument it:** record the **lowest FIFO count ever seen** and **how many frames found the FIFO
  empty**. Those two numbers are the whole health check of the feed, and they cost two comparisons a
  frame. Joust prints them from its harness.

**Exit:** reset the chip. **Only one program can own the VS1053 at a time** — nothing enforces it.

### 8.3 What the timing tests actually showed

Days went into this; the results are the reason 8.2 is shaped the way it is.

- **Metered vs top-up** is the headline: top-up = ~1 s of latency, metered = immediate, no clicks, no
  drift. Test both on a new machine before assuming.
- **The clocks agree.** A **230-second drift measurement** showed the 60 Hz tick and the chip's own clock
  stay together, so the meter never needs correcting and no resync logic is warranted. Measure this once
  per machine; it is what licenses the whole open-loop design.
- **8-bit unsigned mono at ~6 kHz sounded best.** 16-bit mono plays. 12 kHz 16-bit clicked at small FIFO
  targets. Test the formats through a switchable variable rather than arguing about them.
- **SCI registers read back correctly only while the chip's buffer has room.** In top-up play they return
  garbage, and `positionMsec` (WRAM `$1E27`) is not available for WAV at all — so **do not build a
  diagnostic on chip readback**. The FIFO count and your own byte counter are the instruments that work.
- **The codec input is per-machine and it is silent when wrong.** The K2 needed AIN4 selected in WM8776
  register 21 (`$01F`) from `grfdrv256`'s `PSGInit`, or the VS1053 decoded to nothing at all — no sound,
  no error, nothing to see. There is one table per machine (`ifne jr2` / `else`). On a new machine, **"no
  sound at all" is this before it is anything else.**
- Expect the first cut to be wrong in a way that is inaudible in a harness and obvious in a game: test
  with the real script mix, including a high-priority sound interrupting a long one.

**Samples:** start from whatever set exists (Joust used the CoCo 6006 Hz set: 8-bit unsigned, full-scale,
several cut short), and plan to replace them with full-length recordings captured from MAME's emulation of
the original sound board **with MAME unmodified**, via a host tool.

### 8.4 A synth original on the SIDs (`src/sound.a` in Tempest, the worked example)

When the original makes its sound with a synth chip (Tempest's two POKEYs) rather than samples, **keep the
original's own sound code and give it a register image**: the game writes its chip registers into a shadow
in the data area, and once a pass the output stage turns the *changes* into the target chip's writes. The
sequencer stays byte-exact against the ROM, and only the translation is new.

- **Log the original's register writes first** (a stock-MAME Lua script over a played game). Tempest's
  showed the whole problem at once: only `AUDF`/`AUDC` change in play, never more than five channels sound
  together (six never), and only a few `AUDC` forms occur. That is what says six voices suffice and which
  approximations matter.
- **Two SIDs, six voices** — not three chips: `$C4:$0080` "mono" writes both. The SID clock is 14.318 MHz /
  15 = 954,545 Hz; the sound chips are mixed in the FPGA and sent to the codec over I2S, so there is **no
  codec input to select** for them (unlike the VS1053, section 8.3).
- **The mapping Tempest uses:** a POKEY pure tone → a 50% pulse at the same pitch; every polynomial form →
  SID noise stepped at the POKEY's sampling rate (one coprocessor divide); the volume → the sustain level
  with attack, decay and release 0. A SID envelope does not climb to a raised sustain, so a louder volume
  or a new waveform re-gates the voice. Hand voices out as channels start sounding.
- **The access path is a measured cost, not a detail.** Reaching `$C4` with `F$MapBlk` through the service
  window, shared with the text drawing, lost **2.7% of the K2's ticks** where the host model predicted
  nothing; the same code writing the MMU slot directly (interrupts masked, an exception at `$FFA0-$FFAF`)
  lost none measurable. The `$FF98`/`$FF99` block then made both unnecessary: the selector's bits 6-5 pick
  left `00`, right `01`, both `10` or off `11`, bits 4-0 the register, and it holds between data writes.
  **An `F$MapBlk` a pass is expensive on hardware** — more than any model here charged.
- **Test it without ears on the host** (Tempest's `tools/sndtest.py`: after every pass, each sounding
  channel has exactly one gated voice with the right waveform, frequency and sustain, and no stray voice),
  and keep a **reference recording** of the original playing the same sequence from stock MAME, and a
  sound-test mode (`tempest s`: keys start each sound) behind a build flag. The Wildbits MAME is silent, so
  the hardware is the only listener.
- Silence the SIDs when paused and on every exit, and start them again on the way back from a pause.

## 9. Input

- **Joysticks:** `SS.Joy $13`, fixed in this project. R$X = joystick # (0 = header 0 = VIA0 port B,
  1 = port A); returns X and Y as 0/128/255 and buttons 0-2 in A, always all three set; a non-live
  terminal reads centred. The switches read **0 when closed**.
- **Only one stick button exists on the current cores.** The FPGA ties VIA0 bits 5 and 6 to 1
  (`TinyVKY2K2_IO_Page0_Devices.v`: only five lines a port come from the connector, on the K2 and the
  Jr2), so **buttons 1 and 2 never read pressed, whatever stick is plugged in**. And many Atari-style
  sticks wire both of their buttons to pin 6 anyway. A game with a second action needs the keys or a pad
  for it. **Paddles are impossible** for the same reason: DB9 pins 5 and 9 do not reach the FPGA, and
  there is no analog path.
- **SNES pads** (`SS.Joy` mode 4 and up) give a second and third button. The driver keeps the low byte
  stick-compatible, so one decode serves both. **Guard it:** the program cannot tell whether a pad is
  plugged in, the first reading is empty, and an absent pad or an NES pad read in SNES mode shows buttons
  held. Tempest skips the first reading and takes the pad only after it has once read all-zero, at rest.
  *(Tempest's pad support is untested on a real pad: the bit order is read from the RTL.)*
- **A call costs ~400-500 µs (8 MHz), so read a device only once it has been used.** Tempest looks at the stick
  every 30 passes until it has shown a direction or a button, then every pass; that halved its GetStat
  calls and the time went back to the drawing.
- **Modifier/arrow keys and ordinary keys held:** `SS.LiveKeys $C6` returns the driver's live `D.KySns`
  bits in R$A — Shift, Ctrl, Alt, four arrows, space (bit 7 set on the Jr2 and never on the K2: a latent
  driver inconsistency, do not design against it) — and up to six ordinary key codes held down in
  R$X/R$Y/R$U, no caller buffer. (The key codes were once a separate call, `SS.KyDwn $D0`; that code is now
  free.) This exists because NitrOS-9 has nothing else that reports a non-modifier key as *held*: the press
  makes a character and the release is computed and thrown away.
- **Codes are the UNSHIFTED table entry, which for letters is LOWER CASE.** A caller comparing against
  upper case matches nothing and its keys silently do nothing — that was a whole hardware run.
- **Give the game a level, not an event stream.** Arcade code samples a switch byte every pass and builds
  its own edge detector from the previous frame's state. So the platform layer's only job is to be
  truthful about "down now", and a release must be visible within one frame. A hold-timer fallback (keep
  the bit set for N frames after the last repeat) is *not* good enough: it holds a released key for up to
  10 frames and only the newest key gets topped up by auto-repeat.
- **Rebuild the held-key set wholesale wherever you can.** The K2 driver rebuilds from the full matrix on
  every key event and cannot strand a key. The PS/2 driver has to maintain it incrementally, which brings
  four separate hazards, all of them real: typematic repeat resends makes with no break (skip a code
  already present); the shift-selected lookup table must **not** be used to identify a break (look the code
  up in the unshifted map explicitly, or a key pressed with Shift and released without removes the wrong
  entry); keys with a special break handler need the delete call added there too (space, in Joust —
  and space was player 1's second flap); and the array must be cleared on init and on the keyboard's `$AA`
  self-test byte after a reset or hot-plug. **A stranded key is not cosmetic**: with an edge-detected
  control, the player loses that action for the rest of the game.
- When inserting into a driver, remember `a,x` is a **signed** 8-bit offset: a 128-byte table indexed by a
  scan code ≥ `$80` (F7 is `$83`; the Pause key sends `$E1`) reads *before* the table.
- **A rotary control (spinner, trackball) is a delta, not a level.** With no spinner on the machine,
  Tempest feeds its encoder from keys and stick at a fixed number of counts **a tick** — a rate in real
  time, so it does not change when the game's frame rate does — and from the mouse as counts
  (`SS.MsDelta`, when the driver has it). The rate is a feel judgement on hardware: Tempest went 2 → 3 → 4
  counts a tick, one run each. Clamp to what the original's own reader takes in one of its reads.
- **Which way is "right" depends on where the thing is on screen.** On a well whose rim runs along the
  bottom, the original's clockwise moved the claw left, so the port swapped the directions. That reversed
  the menus that read the same counts (the rating ladder, the initials), which then had to be swapped back
  by game state — in the platform layer, leaving the translated game untouched. After changing a control's
  sense, check every screen that reads it.

## 10. Being a good OS-9 citizen

This is the part an arcade port forgets, and it is what makes the difference between a program and a
program people can use.

- **Pause when your terminal is hidden.** Nothing in NitrOS-9 tells a process its window went background —
  so the project added `SS.WSig $E1`: register two signal codes (background, foreground) and the driver
  signals the registered process on each transition. Confirmed on the K2, and Joust pauses and resumes on
  it. Design notes that matter:
  - **Install the intercept before registering.** An unintercepted signal kills the process.
  - **Use codes above `$80`** (the project's defaults are `S$WinBg $81` / `S$WinFg $82`). The system owns
    ≤ `$80`; `$05` is `S$Alarm` and must never be used. Anything below `S$Window $04` aborts a blocked
    read instead of leaving it blocked.
  - Never register code 0 — that is `S$Kill`, non-interceptable.
  - One registrant per terminal; `SS.Relea` releases it.
- **Lock the terminal down while the game runs and restore it on every exit path**: echo off, no editing,
  one defined quit key, and the original options restored afterwards. Confirmed: with the lockdown in
  place, CTRL+C, BREAK and ESC are inert during a game.
- **Exit cleanly from every path, signals included**: silence the sound, disable sprites and tiles,
  `SS.FScrn`, restore the text mode and options, `F$DelRAM` every asset block, then `F$Exit`. Verify by
  running the game twice in a row and by switching terminals away and back.
- Say something on exit. A one-line sign-off (and a clear message when the program is started from the
  wrong directory) costs nothing and answers "did it crash?".
- **Decide, per resource, whether absence is fatal or degraded — and write the decision next to the
  code.** Joust: a missing asset file or a missing settings file ends the program with a message, because
  the game cannot be itself without them; a VS1053 that does not answer leaves `SNDON` clear and the game
  **runs silent**. Both are better than a hang, and the difference is a judgement someone has to make
  deliberately rather than discover on the hardware.
- **A program that owns the screen owns the user's way out.** One documented quit key, and it must work
  from every state the game can be in — including paused, including mid-attract. Check it after every
  change to the input path.

## 11. Driver work in the NitrOS-9 tree

- `export NITROS9DIR=...` on **every** command — shell state does not persist between tool calls.
  Build in `recipes/wildbits/l2` with `PLATFORM=k2` or `PLATFORM=jr2` (which also selects the keyboard
  driver). `.mods` is **shared between platforms**: building for one replaces the other's modules.
- **No generic rule makes a module depend on a defs file.** The recipe makefile carries an explicit list;
  a module missing from it silently keeps its old `.mods` file after a defs edit. When in doubt
  `rm -f .mods/<module>`.
- **vtio is a BOOT module**: changing it means rebuilding the image, not copying a file. vtio and
  grfdrv256 must be rebuilt together whenever a shared layout changes.
- **Where new terminal state lives** — the rule that came out of the DSS running out of room:
  *the device static storage holds what the driver authors; a shadow block holds what the hardware owns.*
  Applied in order: does vtio touch it (then it stays in the DSS, whatever else is true)? is it a verbatim
  register image (then it belongs where the copy happens)? does it fit (the DSS is capped at 256 bytes and
  was at 246)? A field that is both `CpyBlk`'d verbatim *and* read by vtio is the smell.
- **grfdrv256 makes no OS-9 calls**, so it cannot send a signal or do file I/O. Anything that needs the
  kernel is staged in shared memory and done by vtio (Joust's `SS.WSig` stages the id/code and vtio's
  AltISR sends it). Clear a staged id *before* the send, so a dead process cannot leave a request pending
  for ever.
- Caller buffers are read through the caller's DAT image, mapping the buffer's block plus the next one —
  factor that once and share it between calls.
- **Write a tiny test command for each new call** (`wsigtst` for `SS.WSig`) and put it in the recipe's
  `CMDS_EXTRA`. It is how you tell a driver bug from an application bug on the first hardware run.
- **Pushed is not tested.** Say which commits have actually run, on which machine, and keep saying it.

### There is more than one machine

The K2 and the Jr2 are one platform in the docs and two machines in practice, and the difference is never
where you expect it: a different keyboard driver (matrix scan vs PS/2), a different codec input register,
a VS1053 that boots as a MIDI synth on one and not the other, a live key-sense bit that one driver sets
and the other never does.

- **The recipe builds for one machine at a time (`PLATFORM=`), and `.mods` is shared**, so building for
  one replaces the other's modules. Snapshot `.mods` first if you will want both images in the same
  session.
- **Design the per-machine difference as a table, not an `ifne` in the middle of a routine.** The codec
  set-up is one register table per machine; that is the shape to copy.
- **Write down which machine each claim was tested on**, every time. Half of this project's open items are
  "works on the K2, never run on the Jr2", and that is only visible because the docs say so.
- Prefer a mechanism that cannot drift between machines (the K2's wholesale key-matrix rebuild) over one
  that has to be maintained identically in two drivers (the PS/2 incremental list, section 9). Where you
  cannot, expect the incremental one to be where the bugs live.

## 12. Frame architecture

The arcade scheduler is worth keeping verbatim — cooperative processes with nap counts, a primary list and
secondary processes, create/kill/suicide. It is small, it is what all the game code is written against,
and it makes the port a transcription rather than a redesign. Only the stack setup changes (`LDS #STACK`
becomes the saved OS-9 stack pointer), and the kill paths gain one call each to release graphics slots.

The frame loop that worked:

```
F$Sleep X=2          wait for the next 60 Hz tick (Tempest: sleep until a SOL signal, section 12.2)
Input                joysticks + held keys -> the game's switch bytes
DmaReset             empty the per-frame display-request pool
SndSeq               the sound sequencer (before the pass, as the arcade has it)
ExecPass             one pass of the game's own scheduler
SndPump              feed the metered samples
GfxCommit            sprite table, CLUT deltas, tile registers
```

Everything the game logic asks for during the pass goes into a **per-frame pool of request records**,
applied at the commit. Keep the pool sequential and contiguous: Joust's transporter effect walks
*backwards* over three consecutive records, which only works because they come from one pool in order.
A full pool handing back a scratch record is a real edge case — decide what it does before it happens.

### 12.1 How much of the display to send each frame

A driver call costs about **400 µs before it moves a byte**, and about **8.4 µs a sprite record** after that
(measured at 8 MHz, `docs/driver-performance.md` in the Joust repo; re-measure at 12 MHz).  Put those two numbers together and one call is worth about **48
records**: it is cheaper to send 48 records you did not need to than to make a second call that skips them.
That ratio, not the byte count, is what a commit should be designed around, and it is worth re-measuring on
any machine before trusting it.

What follows from it:

- **Send one contiguous range** - the lowest to the highest record the frame wrote - in one call, and make
  **no call at all** when the frame wrote none.  In Joust that is 1,070 µs down to about 410.
- **A second call, or a scatter list of record numbers, only pays when the changes are spread over more than
  about 48 records.**  Joust's changed records span 8 on average, so a scatter form of the call would have
  bought 37 µs for a new register layout.  Measure before proposing one.
- **The range is only tight if the indices are.**  Joust's are because the scheduler's free list is LIFO
  (`sched.a`: a dead process's block goes to the *front*), so live objects keep re-occupying the same few
  blocks, and sprite slots are 2i / 2i+1 of the block index.  A game that hands out sprite indices by object
  type, or spreads them over the whole table, gets no range worth sending: **renumber so that live objects are
  dense** before reaching for a new driver call.
- **Measure first, in the game.**  Build the measuring version of the program itself (Joust's is `jstspr`),
  play a real game, and count what changes.  Attract modes and harnesses are not the load.

The same arithmetic applies to any per-frame table: CLUT entries, tile cells, a sprite's position.  Joust's
palette commit already sends first-changed to last-changed for the same reason.

### 12.2 Keeping time when a pass can overrun (the SOL clock)

Joust's loop is **one pass a tick** (`F$Sleep X=2`), which keeps perfect time only while no pass runs past
its tick. Tempest's could not promise that — a game frame is ~35 ms of logic and drawing — and every lost
tick is game time lost: timers, the sound's tempo and the game's pace all slow together. What was tried, in
order, and what stayed:

1. **A per-pass "read the tick count" call** (`SS.Tick`) — withdrawn: a system call every pass is too slow,
   and copying kernel globals with `F$CpyMem` was rejected on the same grounds.
2. **Splitting the frame** — logic in one pass, the drawing as a coroutine on its own stack spread over
   later passes, each step charged against a per-pass budget of *estimated* µs. It kept the clock, but the
   estimates had to be set high to lose no ticks, so passes ended with time unused: 14 game frames a second.
   Days went into tuning the estimates.
3. **The SOL clock, which stayed.** SOLdrv (`/fSOL`, in the boot file) signals the process at a raster
   line: `SS.SOLIRQ` with **line 0**, the frame's first line, is a signal every tick. The intercept only
   counts ticks; each pass runs the game's timer work **once for every tick since the last pass** (capped:
   Tempest's `TKMAX` 32, for a superzapper blast of ~250 ms), and sleeps (`F$Sleep` 0, woken by the next
   signal) when none has arrived. A long pass is caught up instead of lost. Mute it while paused
   (`SS.SOLMUTE`) and take the ticks from the moment of return; release it on every exit path. Without
   `/fSOL`, fall back to one pass a tick.
4. **Then the budget machinery went.** With the clock safe, a game frame became two passes — the logic,
   then the whole drawing in the next — and the coroutine, its stack, the budget and every estimate were
   deleted: **20.3 game frames a second against 16.2**, less code, and nothing left to tune. The only rule
   kept: a drawing that took `SKIPT` ticks or more drops the next frame's drawing (its logic still runs).

**An original that is not a 60 Hz machine runs on a virtual interrupt.** Tempest's IRQ is 246.09375 Hz,
exactly 525/128 of the tick: each tick adds 525 to an accumulator and each 128 is one run of the arcade's
own IRQ code (coins, sound sequencer, frame timer). Find the exact ratio; then the game's clock is exact
too, and the host model can check it (Tempest's measures 245.9 against the arcade's 246.1).

**A frame gate must carry its surplus.** The arcade runs a game frame when its IRQ counter reaches 9 and
clears it — harmless there, because it polls continuously. The port only looks once a pass, by which time
the counter holds up to 13, and clearing threw the extra away: every frame took three ticks, **capping the
game at 20 frames a second however fast the CPU** (moving the K2 from 8 to 12 MHz gained nothing). Subtract
9 instead and keep a bounded carry (Tempest's `FRCARY` 4): 26.9 frames a second on the K2, the arcade's
27.1. **When a faster machine does not make the game faster, look for a gate that quantises to ticks.**
(The carry also made two logic passes in one frame possible, which exposed the `E$DevBsy` bug of section
6a: a timing change moves which rare paths are reachable.)

### 12.3 What paid, measured on the K2

Each of these was one hardware run with the sign-off's numbers before and after (section 13). In order of
what they bought Tempest:

- **Don't re-run what the original only changes sometimes, and use the original's own signal for "it
  changed".** Tempest's well is 48 line records a frame, but Atari rebuilds it only when its shape changes,
  into a spare buffer, and then switches a jump to it — so that jump's target changing *is* the well
  changing: no checksum, no comparison. The port draws the well once into the back layer and skips its
  sub-list entirely while the jump and its colour are unchanged: **~35-40% more game frames**. The first
  version cached only the drawing and still interpreted the well every frame, and its off-colour records
  went in a call of their own — it measured *slower*. Cache the work, not just the output, and never add a
  call to save records (section 12.1).
- **Simplify what cannot be seen.** A 16-45-stroke enemy deep in the tube rounds onto 2-3 pixels; drawn
  as a small block in its last stroke's colour it is indistinguishable, and play sent 129 records a frame
  instead of 161. Prototype the threshold on the host (1 px saved nothing, 3 px showed) and show the user
  side-by-side pictures before building it.
- **Redraw only the text that changed, and match lists by content, not index.** One line alternating
  between an 11- and an 8-character message shifted every entry after it, so a comparison by index redrew
  all 293 glyphs of the high-score screen every two seconds. A match with an 8-entry look-ahead each way
  cut it to 20.
- **Trade picture for speed only where the user says so.** Tempest's title logo draws 19 copies of itself;
  skipping every other copy, and shortening the hold after the zoom, were each the user's call made on
  hardware against the photograph — port simplifications, recorded as such, behind build switches, with
  the translated game code untouched.
- **Layer order is free.** Moving the text bitmap behind the lines cost nothing and made the well cache
  possible, since the back layer could hold both.

## 13. Working method (the expensive lessons)

**Testing**

- **The hardware is the test.** The Wildbits MAME (`wbjr2`) emulates less than the machine, and what it
  covers changes with its build. The build of **2026-09-30 (commit `8779b61`, the v8_rc20 baseline)**
  renders the **bitmap, tile map and sprite layers** with their CLUTs (tile-map attributes as section 6
  has them, from `028632e`), the MemText text engine, **draws with the line engine**
  (Tempest's rating-screen wells appear), returns the live raster row at `$FFDA/$FFDB`, and has the
  sound chips — the SIDs at `$FF98/$FF99`, the OPL3, the PSGs, the VS1053 — though no port's sound has
  been heard through it yet. Its **DMA is instant**: the whole fill runs inside the register write and
  never halts the CPU, so no DMA timing, wait-mode or arming-line result means anything there (the
  2026-09-21 build also filled 16-bit clears with the wrong value; not re-checked). **Check a new build's
  colours against a photograph**: `34a1205` read CLUT entries as R, G, B, A and swapped red and blue
  everywhere; `0f1d5dd` put it back to the hardware's **B, G, R, A** (the RTL's 8-bit-write, 32-bit-read
  CLUT RAM puts byte 0 in bits 7:0, which `TinyVickyCoreModule.v` wires to blue). Older builds:
  `6ed0ed0` (2026-09-21) had no line engine and no sound; the Sep 6 one, and `~/projects/grok/mame`,
  draw text only. It is good for proving a *program* works — crashes, hangs,
  OS-9 error codes, what is on screen — for a static utility harness that prints numbers, and for
  **counting calls** (call counts are logic, not timing). **Its timing is no evidence.** **Do not modify
  MAME.**
- **MAME trails the FPGA core.** It models a particular core, and a new core can change registers under it
  (the `$FF90` sound block, a bigger line FIFO, HIRES4). When the machine has a newer core than MAME,
  a clean MAME run proves only the parts that did not change; say which core each MAME claim was made
  against, as for the machines (section 11).
- **Run every build in MAME before it goes to the hardware**: start, coin, start, quit, the sign-off. It
  catches the build that does not start at all, which otherwise costs a whole hardware round trip.
- **Driving MAME: use a Lua `-autoboot_script`, which does reach a running program.** Characters from
  `-autoboot_command` (or typed) after the program starts are lost — Joust measured that — but
  `manager.machine.natkeyboard:post("...")` from a script reaches `SS.LiveKeys` (Tempest: `5`, `1`, `q` all
  arrive). Take pictures with `manager.machine.video:snapshot()` from `emu.add_machine_frame_notifier`,
  and **keep that subscription in a global**: a local is garbage-collected after one frame and nothing
  more happens. The script replaces `-autoboot_command`.

**Running the Wildbits MAME** (checked 2026-09-30 with Tempest on the Jr2 image):

- **The binary** is **`~/projects/wild/mame/mame`**, machine **`wbjr2`** (the only Wildbits machine it has;
  it runs the **Jr2** image, not the K2's). The directory is its own git clone
  (`github.com/rlucente-retro/mame`), shared by every project; it moved out of the NitrOS-9 tree on
  2026-09-30, and `$NITROS9DIR/mame` is a symlink to it for old command lines. Pull and build it there:

      cd ~/projects/wild/mame && git pull --ff-only
      make SOURCES=src/mame/wildbits/wildbits_jr2.cpp NOWERROR=1 REGENIE=1 -j$(nproc)

  `NOWERROR=1` because MAME builds with warnings as errors and an upstream commit can leave a warning in
  (`34a1205` did: an unused function, still there at `8779b61`); `REGENIE=1` because the option only takes effect when the
  generated makefiles are regenerated. Keep the previous binary (`cp -p mame mame-<commit>`) until the
  new one has run a program, and check `make`'s exit status, not the tail of its log. Its source is also where
  MAME's drivers for arcade hardware can be read (for Tempest: `src/mame/atari/tempest.cpp`,
  `src/devices/video/avgdvg.cpp`, `src/mame/atari/mathbox.cpp`) — read, never edited. The **stock** MAME
  (`/usr/games/mame`) is the other one: it runs the *arcade* original, for the captures of section 14a.
- **`-bios turbo`** (~8.8 MHz) is what the projects use; `stock` is 6.29 MHz.
- **Mount a copy of the image**, not the recipe's own file: MAME writes into the image it mounts, and a
  run that crashes mid-write leaves it that way. Mind the size rule (below).
- **Interactive**:

      ~/projects/wild/mame/mame wbjr2 -window -skip_gameinfo -bios turbo \
          -hard $NITROS9DIR/recipes/wildbits/l2/l2_wildbitsjr2.dsk

- **Headless and scripted**, the form for checks before a hardware run:

      ~/projects/wild/mame/mame wbjr2 -bios turbo -hard /path/to/copy.dsk -skip_gameinfo \
          -video none -sound none -nothrottle \
          -autoboot_script drive.lua -snapshot_directory snap

  Snapshots still work with `-video none`. MAME prints the kernel's last state (LUT, `D.Proc`, the code at
  PC) on exit; that is normal. With `-autoboot_command` instead of a script, a newline is the
  two-character escape `\n`, and `-seconds_to_run N` ends the run.
- **A driving script** (`drive.lua`: type the program's name at the shell, then coin, start and quit; a
  snapshot in play and one of the sign-off; then exit). Frame numbers are MAME's 60 Hz frames, so leave
  the boot ~10 s:

      local steps = {
        { 600,  "tempest\n" },   -- frame, text to post
        { 1200, "5" },           -- coin
        { 1300, "1" },           -- start
        { 1800, "q" },           -- quit
      }
      local n = 1
      frames = 0                 -- globals: a local subscription is collected after one frame
      sub = emu.add_machine_frame_notifier(function()
        frames = frames + 1
        local s = steps[n]
        if s and frames == s[1] then manager.machine.natkeyboard:post(s[2]); n = n + 1 end
        if frames == 1700 or frames == 2100 then manager.machine.video:snapshot() end
        if frames == 2200 then manager.machine:exit() end
      end)

  On 2026-09-30 this gave the rating screen (coin and start arrived) and "Tempest over." with the closing
  line and the prompt (`q` arrived) in 36 s of wall time.
- **Build a host model of the whole machine, and make it the everyday test.** Tempest's `tools/osrun.py`
  runs the real module on a host 6809 with every `os9` call answered by a script — bitmaps in "physical"
  blocks, the line engine, CLUTs, layers, DMA timing, SOLdrv, the coprocessor, the MMU, keys and pads from
  a script — and **checks the whole display after every game frame** (the text bitmap against its list
  drawn from scratch, the CLUT against the original's colour RAM, the line bitmap against that frame's
  records). It found most bugs before MAME or the K2 saw them. Its rules:
  - **Model every register a call hands back**, including diagnostics (section 6).
  - **Model the hardware's timing wherever the program waits on it** (the DMA, section 6a), and make the
    CPU clock a parameter, so "what if the machine is faster" is a run, not a guess.
  - **Make the model fail loudly on anything the hardware would punish silently:** a coprocessor access
    or MMU write with interrupts unmasked, an `os9` call while a window holds a foreign block, a line drawn
    into a bitmap before its clear has run.
  - **Its costs are guesses and they were wrong both ways** — the K2 drew faster than the model charged,
    and `F$MapBlk` cost far more. Use the model to rank changes and prove correctness; take the numbers
    from the hardware.
- **Reproduce intermittent faults with a harness that forces the rare path.** Tempest's "slows down after
  a few games" survived seven simulated minutes of back-to-back games in the model; the same harness with
  the high-score table zeroed — so every game ended in initials and the start ladder — reproduced it at
  once, and a **profile by routine** (where the time went, every 10 s) named the cause in one look. When a
  fault depends on what the player did, script the unusual thing.
- Its SD image sizes are constrained (`block count = odd × 2^n`, n ≥ 2), so a recipe image may need
  padding to a power of two before MAME will mount it. **Pad upward only.** A disk image declares its
  sector count in LSN0 and the file on disk holds only the sectors written so far; truncating it to a
  smaller "pad" silently cuts the tail off the filesystem, and every program that opens a file whose
  descriptor was cut fails with **`ERROR #214`, no permission** — the descriptor reads back as zeros, so
  its attribute byte is 0. An hour went into bisecting that as a firmware fault before it turned out to be
  the test harness.
- **Or drive MAME from the image's own `startup` file, not `-autoboot_command`.** Typed characters are
  dropped unpredictably; a script on the image is deterministic (so is the Lua script above, which is
  easier to change). To tell whether a program is still
  running at the end of a timed run, put a marker command after it in `startup` (`echo X >SOMEFILE`) and
  look for the file afterwards — MAME's writes persist into the image.
- Compare screens against photographs of the real machine, and measure the photograph against the assets
  before calling something a bug. Three "obviously wrong" things in the first wave were all correct.
- **One change per hardware run.** When a fix does not work, compare against the last *good* build rather
  than re-reading the suspect code — several days were lost to a confident wrong diagnosis that survived
  three rereads.
- **When a fault is intermittent, suspect the test rig before the code — including the peripherals.**
  A dying PS/2 keyboard once produced a stream of one character until lockup, appearing immediately after
  a driver change. Reverting the change "fixed" it; a later, unrelated change "broke" it again; the
  opposite correlation then looked equally convincing. Two causes were written down as confirmed and both
  were wrong. A new keyboard ended it. The tells, in hindsight: **the symptom survived a power cycle and a
  reflash**, it **never correlated with the same change twice**, and each "confirmation" rested on a
  single trial plus a revert. On a flaky rig, one trial and a revert is not evidence — insist on two
  clean trials each way before writing a cause into the docs, and swap the hardware early when nothing
  explains the pattern.
- **The FPGA core is a version too, and it can regress.** A Jr2 once showed scattered stray pixels over
  everything the bitmap layer touched. Two stock commands bisected it in minutes — one that uses sprites
  only was clean, one that allocates and displays a bitmap was not — which proved no application code was
  involved, and **flashing the previous core cured it**. Keep a known-good bitstream, know how to go back
  to it, and when a *stock* program misbehaves, try that before looking in your own code at all.
- **`dcheck` the disk image before blaming the disk image.** When an image has been patched in place
  repeatedly, filesystem corruption is a reasonable suspicion — and a cheap one to test rather than to
  act on. Here it came back intact on both the patched and the freshly built image, which retired the
  theory in seconds.
- **Give the program a numbers sign-off, behind a build flag.** On quit, Tempest's diagnostic build prints
  game frames, passes, seconds, line calls, short returns, dropped drawings, SOL ticks, pauses, and a line a
  game (its frames, ticks and passes). Those lines turned every hardware run into a measurement, told a lost
  tick from a slow pass, and made the intermittent slowdown visible (game 2 at 11.6 frames a second while
  the ticks still arrived at 59.4). **Count every silent fallback there too** — a latched fallback is a bug
  that looks like "slow". Keep it behind a flag (`make EXTRA="-DDIAG"`) so the shipping module has the
  space, and so it prints one clean line.
- **Rank builds with a fixed benchmark, not with play.** Play runs of different lengths reach different
  levels with different loads, so 12.3 against 17.9 frames a second said nothing about the builds. Tempest's
  benchmark: start, no coin, two minutes of attract, quit — the same sequence every time — with play kept
  for the feel.
- **A trace file is how you see inside a run.** A tiny module that appends bytes to a file, opened at
  start-up and closed at exit, read back off the card afterwards. Keep it until the last untested machine
  has run; it is the only instrument on a machine with no debugger. Two properties decide whether it is
  worth anything: it is **only complete if the program exits the clean way**, so a crash loses the tail
  you most wanted; and a buffered writer costs one file write per flush, which is affordable in a frame
  loop only if the trace is small and deliberate. Trace *decisions and values*, not progress.

**The loop that gets work onto the machine and evidence back off it**

This is mechanical, and every step of it has cost a session at least once:

1. `make` — all programs, in the background if it takes minutes; confirm it finished before editing a
   source it is reading.
2. `make install DSK=<absolute path>` — **absolute**. A relative path silently writes nothing, because
   make runs in the source directory.
3. **Check the installed module is byte-identical to the built one** and record its size. A stale copy on
   the card is indistinguishable from a fix that did not work.
4. Write the card (`dd`), after checking with `lsblk` which device the reader actually is this time.
5. Run it on the machine. Photograph what matters.
6. Read the card back into a file (`dd` with an explicit byte count) and pull the trace out of the image
   with the OS-9 tools. Lines written by an OS-9 program end in CR.
7. Remember that a recipe's image target may **reformat** the disk, so re-install the program and assets
   after rebuilding an image.

**Which source to believe**

Addresses and register behaviour have several sources here and they do not agree. In order of authority:

1. **The RTL** — a read-only clone of the FPGA core repo sits at `fpga-6809-cores-staging/`
   (`wildbitscomputing/fpga-6809-cores-staging`). It is the hardware, so it settles anything the documents
   disagree about — register decode, field widths, what a read-back really returns. **Reference only:
   never modify, never commit, never push anything inside it**; it is in `.gitignore` for that reason.
2. **The rc16 memory map and the Wildbits site** — this machine, and the documentation for anything the
   FPGA adds (the line-draw engine, the extended addressing, the bridge registers).
3. **The NitrOS-9 tree** — `defs/wildbits.d`, the drivers, the kernel. Authoritative for what the software
   currently does and assumes, which is not always the same as what the hardware allows.
4. **The F256 manual** — structure and concepts only: what a stride is, what a tile set is, how a DMA fill
   is set up. **Its numbers describe the base machine.** The rc16 changes some of them.
5. **The person who wrote the FPGA**, when it matters enough to ask. That outranks everything, and it is how
   the DMA addressing question above was settled in one message after two documents disagreed.

Live examples of the trap, all of them caught the hard way: the tile set register order (manual wrong for
these registers), the DMA's addressable range (manual says 19 bits and the first 512 KB; the rc16 reaches
all of RAM), and a web summary that got a neighbouring register table wrong while getting the line-draw
engine plausibly right. **When two sources disagree, say so in the doc and mark which one you acted on.**

**Writing it down**

- **Never record an untested diagnosis as confirmed.** Label it untested until the hardware shows it. The
  docs are the handoff; a wrong "fixed" line costs a whole session later.
- Record what *was* measured — table sizes, pixel columns, byte counts — not conclusions alone.

**Tooling potholes** (all of these bit, all are cheap to avoid)

- `lwasm` is built here with `nosymbolcase`: `ObjTab` and `OBJTAB` are the same symbol, and so are
  `PAUSED` and `Paused`. Scan every source case-folded for duplicate labels after adding any. **The silent
  variant:** a game label that only the defs also define is not a duplicate but a *use* — Tempest's table
  `LEVEL` assembled without error as the defs' `Level` (= 2), an address of 2. Scan the game's operands
  against the defs' names too, and a routine named like a build flag becomes the flag (`Tsnd` was `TSND`).
- `lwasm`'s `opt c` cycle counts are **6309** counts unless `--6809` is given.
- It is also built with `undefextern` and `condundefzero`: **an undefined equate assembles as 0 instead of
  erroring.** After adding any new SS code or defs symbol, check the `.map` that it resolved to the value
  you expect.
- **An 8-bit indexed offset is signed**: a static field above `$7F` needs the 16-bit form
  (`ldb V.WSigID,u` will not assemble as written).
- A far label used in direct mode is truncated to page 0 silently — give the static checker a class for it.
- **A new `src/*.a` must be added to the makefile's `SOURCES`** or make silently reuses the old listings.
- `grep` fails silently on very large source files in this sandbox (it exits 1 and prints nothing past
  ~line 6,600, even through a pipe). Use `awk`, and note `NR` is cumulative across files — use `FNR`.
- Some tools refuse `.a` files as binary; read them with `sed`/`awk` and edit them with scripts.
- **Scripted edits are all-or-nothing:** a failed anchor discards the whole script silently. Anchor on
  short unique text, assert the match count, and read the file back. Never include a label in an anchor —
  it breaks as soon as a neighbouring line moves.
- **When inserting 6809 code, check the flags as well as the registers.** `PSHS` does not touch CC, so a
  test you did not write yourself is the *caller's* last compare; `CLR` always sets Z. Both bit.
- Several arcade routines are entered by **falling through from the code above**. Never insert a helper
  there.
- A full build of every program takes minutes: run it in the background and confirm it finished before
  editing a source it is reading. (Don't wait on a `grep` for the assembler's name — the pattern matches
  the waiting shell's own command line.) The same trap kills: `pkill -f pattern` from a shell whose own
  command line contains the pattern kills that shell. Select processes by program and argument instead.
- Rebuilding a recipe's disk image **formats it**: everything the recipe does not install (the game, its
  assets, its tools) is gone. Back the image up first and copy the rest back, compared. The recipe also
  rebuilds `.mods` for one machine at a time (section 11), so empty it before each platform's build.

## 14. Starting a new port: the survey

Everything above is the platform. What changes per game is small, and it is worth finding out *before*
any design work, because two or three answers decide the whole shape of the port. Write the answers into
`docs/port-<game>.md` — a companion to this guide, not a copy of it. `docs/port-tempest.md` is the
worked example.

**The survey**

| Question | Why it decides something |
|---|---|
| What CPU is the source? | 6809 is a transcription with the arcade labels intact; anything else is a translation, and the per-routine checking that replaces "compare against the listing" has to be planned: section 14a |
| What does the display *actually* consist of? | Moving objects → sprites; static background → tile map; text, effects and anything hand-plotted → bitmaps; lines → the line engine (section 7). Most games are a mixture, and the mixture is the design |
| Does it redraw the screen wholesale each frame? | If yes, erasing is a first-class problem with no free answer at 76,800 bytes a frame — settle it before anything else: a DMA clear of a double-buffered bitmap, armed a tick ahead (section 6a) |
| How many distinct moving objects at once? | 128 sprite records exist, and all of them survive a terminal switch through the registered table (section 6) |
| What is the original's frame rate and interrupt rate? | Rarely 60 Hz. Its IRQ becomes a virtual interrupt on an exact ratio of the tick, and its frame gate needs a carry (section 12.2). Measure its own per-frame work in MAME: that is the budget the port has to beat |
| Does it check its own hardware or code? | Anti-tamper checksums of code, and probes for a real sound chip, fail on a port — sometimes long after, by sabotaging something else. Find them by name and by their flags, make each **pass**, and grep every consumer (section 1's stubbing rule) |
| What does its special hardware do, exactly? | A maths unit, a vector generator, a synth chip: each becomes a register image or shadow the platform fills, and each needs an exact host model (MAME's is the usual reference) before its replacement can be tested |
| How many colours, and does the game animate the palette? | One CLUT per layer, entry 0 transparent; palette cycling is cheap through `SS.ClutWrite` at the frame commit |
| What is the input? | A level (a held switch) and a delta (a spinner or trackball) are different platform contracts — section 9. Count the buttons: a stick gives one (section 9) |
| What makes the sound? | Samples → VS1053 (section 8); a synth voice model → the SIDs, PSGs or OPL3 behind a register image (section 8.4). Log the original's chip writes before deciding. Decide before the output stage exists |
| What maths does the frame do? | Multiplies and divides can go to the integer coprocessor (section 7a) instead of being hand-written |
| Where do settings and high scores live? | The settings-as-a-file model answers EAROM, CMOS and battery RAM alike, with an operator program editing the same file |
| How big is the kept code and data? | Against 40,192 bytes of module and one 8K data area (section 3). Measure it early; relief is moving tables into asset blocks |

**Graphics first. The order is not arbitrary, and it is the single best procedural lesson of the Joust
port.** (Tempest's version of the viewer was host-side: its display was proven by rendering MAME's captured
display lists at the port's resolution and comparing with MAME's own pictures, long before the line engine
was fixed. Either way, the display is proven before the game needs it.) Before the game logic, before the sound, before the skeleton was finished, the assets were
converted on the host and put on the screen by a standalone viewer (`jstview`) that did nothing but load
them and show them. That bought, in order:

- **proof of every graphics primitive the design assumed** — layer order, sprite-versus-bitmap depth, the
  tile set's pixel layout, CLUT writes and cycling, the band cut, the glyphs — each confirmed on real
  hardware against a photograph, months before any game code could have exercised them. Two of those
  turned out differently than the manual said (the tile set register order, the tile layer's 8-pixel
  offset), and finding that in a viewer costs an afternoon where finding it inside a half-written game
  costs a week;
- **an instrument.** Once the assets are on screen and correct, every later failure is *the game's* fault,
  which halves the search space of every bug after it. Without it, "the screen is wrong" has two suspects
  and no way to separate them;
- **a converter that is already right.** The viewer is what proves the host tool chain, and every asset
  the game later loads comes through it.

Sound is the reverse case and confirms the rule: it is invisible, its failures are silent (a wrong codec
input, a stranded format, a metered feed that is subtly short), and it has no equivalent of a photograph.
It belongs after graphics, with a harness of its own, and it needs the instrumentation of section 8.2
precisely *because* you cannot see it.

**So, in this order**

1. **Convert the assets on the host and display them with a standalone viewer.** No game logic, no
   platform layer — load and show. Confirm against photographs of the real machine.
2. **Bring-up harnesses for every remaining hardware primitive the design will lean on that this project
   has not proven** — today that means sprites-and-lines together, the PSGs and the OPL3, the coprocessor
   divide's latency, the floating-point registers, the mouse (`SS.MsDelta`), and anything a new core
   changed. One harness each, on real hardware, with a number written down at the end. *Design
   waits on these*, because a design built on an assumed capability gets rewritten when the assumption
   fails.
3. **The two interface documents** — game logic → graphics, game logic → sound — written from the original
   listing with every call site listed, and the harness numbers in them (section 1).
4. **The program skeleton**: data area, asset blocks, display set-up, frame loop, `SS.WSig` pause,
   terminal lockdown, clean exit. Port `src/platform.a` rather than rewriting it; it is proven.
5. **The graphics section** against a harness that issues display requests (Joust: `jstgfx`).
6. **The sound section** against a harness that fires every sound and prints the feed's health numbers
   (Joust: `jstsnd`).
7. **The game logic, in parts**, each part confirmed on hardware before the next one starts. Joust's parts
   were: scheduler, utilities and tables, attract mode, the wave and the player, the enemies, then the
   remainder. Each part had a named harness or a screen to check it against.

**What is already built and should be reused rather than rewritten**

- `src/platform.a`: start-up, asset loading, display set-up, frame loop, input, `SS.WSig` pause, terminal
  lockdown, clean exit on every path.
- `src/sched.a`: the arcade process/nap scheduler in PIC form.
- `src/text.a`, `src/draw.a`: proportional glyph rendering, one-colour masks, box fills, per-line routing
  between two bitmaps.
- `src/dma.a`: the per-frame request pool and sprite-slot commit.
- `src/snd.a`: VS1053 set-up, the metered feed, the script sequencer.
- `src/cmos.a` + `joustadm`: the settings file and an operator program for it (`docs/joustadm.md`).
- `tools/piccheck.py`: the static position-independence check.
- The `grfdrv256` calls of `docs/grfdrv256-api.md`, and its reserved code space for the rest.
- From Tempest: `tools/osrun.py` (the whole-machine host model, section 13), `tools/cpu6502.py` and
  `tools/cpu6809.py` (cycle-counted host CPUs), the SOL clock and virtual IRQ in `src/frame.a`, the SID
  output stage in `src/sound.a`, the pad guard in `src/input.a`, the DMA clear in `src/gfx.a`, and the
  stock-MAME Lua capture scripts (`tools/avgcap.lua`, `tools/sndref.lua`).

## 14a. When the original is not a 6809: translating, with the ROM as the oracle

Tempest's 6502 was translated, not transcribed, and "compare against the listing" had to be rebuilt as
something stronger. The pipeline, which ended with **2,417 recorded game frames byte-exact against Atari's
ROM**:

1. **A host reference that runs the original.** A cycle-counted host CPU of the original's type, loading
   the ROM as MAME does, with MAME's models of its custom chips ported beside it. First check that the
   source rebuilds the ROM byte for byte, and which revision it is; pick the revision MAME treats as the
   parent. A tool that aligns every source statement with the ROM gives every label its real address.
2. **A pilot before a translator.** Hand-translate three contrasting routines under each candidate
   register model, exactly as a translator would emit them, and measure size, cycles and correctness.
   Tempest's choice (6502 X and Y as direct-page pseudo-registers, B always scratch) was decided not by the
   2-6% it saved but because it **needs no register liveness to be correct** — the model whose failure mode
   is a silently wrong register loses. The pilot also gives the code-size ratio (1.33; the whole game came
   out 1.35), which is what says whether the module fits.
3. **A mechanical translator, whose output is never edited.** It is regenerated; hand-finishing happens in a
   copy (`xlat/` → `src/`), and the translator marks every site it cannot do (`* HAND:`) by category. What
   it had to handle for the 6502, each a rule worth writing down before the first file: carry is inverted
   after a subtract or compare; 6809 loads, stores and `CLR` set flags the 6502 leaves alone (so flags need
   a whole-program liveness analysis); `PULS` sets none where `PLA` sets N and Z; decimal mode is a
   dataflow; `BIT` translates by which flags are read after it; zero-page indexing wraps on the 6502 and not
   on the 6809; the RTS-dispatch idiom becomes one jump through an offset table.
4. **A differential test that runs each routine on both CPUs from the same state** and compares all of RAM,
   the chip shadows and the registers — **with the 6809 side run at two different load and data
   addresses**, which is the position-independence check for free. Three test layers:
   - **named routines** with generators that force every edge case;
   - **a fuzz** of every routine on random RAM, with **written rules for which states the game can
     produce** (a case outside them is skipped, not compared). The rules are themselves the list of what
     the port assumes;
   - **recorded game states**: stock MAME's RAM at the start of every n-th game frame, over a scripted
     played game and attract; whole frames run on both CPUs. This caught what the fuzz hid (a cross-file
     label distance, an anti-tamper check reading code as data).

   Prove the test catches bugs: deliberate one-line mutations must fail it.
5. **Hand work in an agreed order**, each piece re-tested before the next: the replaced maths hardware,
   start-up relocation of pointer tables, the flag sites, decimal arithmetic, the coin code, and last the
   hardware shadows, which become the platform layer's seams.

**The original's assembler has its own rules**, and each one broke a tool until handled: Atari's MACRO-11
dialect has symbols significant to six characters, a separate symbol table per file, a bare expression line
that assembles as a word, `.REPT 0` as a block comment, and macros that define a small bytecode (Tempest's
enemy behaviour). Read the dialect once, with a parser that classifies every line and reports anything it
does not recognise.

**Record the original's behaviour in stock MAME with Lua** — display lists, RAM at frame boundaries, chip
register writes, per-frame work — all with MAME unmodified. Those captures are the reference for the
display, the sound and the timing, as well as the logic.

---

## Appendix: the one-page checklist

**Before designing**
- [ ] Assets converted and shown on real hardware by a standalone viewer, checked against photographs
- [ ] Both seams written down, with every call site listed
- [ ] Every hardware primitive the design depends on proven on real hardware by a harness
- [ ] Logical-space plan: module budget, data area, how many windows are live at once
- [ ] The original's frame and interrupt rates known, and the clock designed to catch up lost ticks
- [ ] Not a 6809: host reference CPU on the ROM, register-model pilot, differential test proven to catch
      mutations
- [ ] Anti-tamper and hardware-probe code found and made to pass
- [ ] A host model of the machine that checks the display every frame

**Before believing the sound works**
- [ ] Metered feed, not FIFO top-up; latency judged by ear against an event
- [ ] Drift measured over minutes, not seconds
- [ ] Lowest FIFO count and empty-frame count instrumented and read after a real game
- [ ] The codec input register checked for *this* machine (VS1053; the FPGA's own chips need none)
- [ ] A synth original: its register writes logged, the output stage checked per pass on the host, and a
      reference recording from stock MAME

**Before every hardware run**
- [ ] One change since the last run
- [ ] `make` clean, `budget` passes, `pic` at 0 reports, `.map` checked for any new symbol
- [ ] Sources scanned case-folded for duplicate labels
- [ ] Installed module byte-identical to the built one, and its size recorded
- [ ] Run in the Wildbits MAME: start, coin, start, quit, the sign-off (and know which core that MAME models)
- [ ] Every register each driver call returns saved where needed, and modelled on the host
- [ ] The diagnostic build and a fixed benchmark if the run is meant to measure anything

**Before writing a doc line**
- [ ] Measured, or labelled untested
- [ ] "Pushed" not written as "tested"
