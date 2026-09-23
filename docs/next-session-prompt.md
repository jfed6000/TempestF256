# Next session prompt

Paste the block below to start the next session, from ~/projects/wild/tempest.

```
We're porting Atari's arcade TEMPEST (Rev 3, the source's "2A(alt)") to NitrOS-9 Level 2 on the
Wildbits F256 (6809, rc16 FPGA core, K2 and Jr2). Joust, the first game on this platform, is finished in
~/projects/wild/joust. This folder is a local git repo (branch main, no remote until I say so).

READ FIRST:
  - docs/status.md: state, decisions, hardware findings, stage 0's numbers. Start here.
  - docs/port-plan.md: the plan (section 5 decisions, section 6 SS call proposals).
  - docs/port-tempest.md: the survey of tempest_orig/src, file by file, with line numbers.
  - ~/.claude/projects/-home-magnus-projects-wild-joust/memory/MEMORY.md and the files it points at:
    Joust's platform rules, which apply here unchanged.
  - docs/port-guide.md (generic platform guide) and, from ~/projects/wild/joust/docs, only as needed:
    grfdrv256-api.md, bitmap-api.md, driver-performance.md.

WHERE THINGS STAND (2026-09-23): STAGE 0, THE D6 WORK, STAGE 2'S INTERPRETER ON THE HOST (its CPU
budget and layout approved) AND NOW THE PLATFORM LAYER ARE DONE, host and MAME only. The platform
layer is FOR REVIEW (docs/status.md, "The platform layer"):
  - src/tempest, a 34,693-byte OS-9 module (src/makefile: make = build, budget, make pic; make
    install DSK= is the targeted copy). src/tempest.a is still the host tests' build of the game.
  - The IRQ is ALHAR2's own on a virtual 246.09375 Hz clock (525/128 of the tick, src/frame.a);
    RANDOM is a generator (src/hw.a) that xlattest mirrors read for read; ZPOKST and ZPONTS are
    neutralised; the text bitmap redraws only what changed (src/text.a).
  - ONE PASS A TICK, AS JOUST (SS.Tick was proposed and withdrawn): the game frame is split, a
    logic pass then drawing passes, the drawing a coroutine (DrwBeg/DrwRes/Spend) that gives the
    tick back on an estimated budget; AvgFlush sizes each next batch (avg.a's new AV.RMAX).
  - tools/osrun.py runs the module on the host 6809 with every os9 call scripted: 120 s of play,
    every game frame checked (text bitmap, CLUT, line bitmap), 245.9 virtual IRQs a second, 1 tick
    lost in 7,200, but 14 GAME FRAMES A SECOND (21 unsplit). In the Wildbits MAME (no line
    engine) it starts, takes 5 and 1, shows the attract and rating screens, and q exits cleanly;
    its game clock ran slow there (unexplained; MAME is no timing evidence).
  - Committed: 8a5f02a (the platform layer before the split). The split and the sign-off numbers:
    not committed unless I said so.

DECIDED: Rev 3; D3 glyph masks on a front text bitmap; D4 keyboard (arrows, Shift fire, z zapper) +
mouse (SS.MsDelta, approved) + joystick, no spinner; D6 model B and its conventions; D8 math
coprocessor approved, its multiplier too; hand-finished code in src/ (xlat/ generated, never
edited); the D6 hand work's recommendations; stage 2: redundant dots dropped, the CPU budget
(heavy frames stretch, no tuning before tline S) and the layout (AVGPG $0C00, window A) approved.
The rest of the plan's recommendations stand unless I say otherwise.

HARDWARE: THE LINE ENGINE IS FIXED (user, 2026-09-23) and tempest RUNS ON THE K2: the picture is
right (the user's photograph), but "it plays, but it is really slow". The build on the K2 image
prints "G game frames, P passes in S s" on q: passes/s below 60 means ticks lost, frames/s is the
real rate (the host model says 14.7 and 60). The developer has now sent a NEW CORE WITH THE LINE
ENGINE AND A 640x240 BITMAP MODE: nothing about it is known here yet (the defs list only 320x240
and 320x200 bitmaps, wildbits.d:866). Re-run bmtest C then L, and C then F, on each new core.

THIS SESSION: OPTIMIZE, AND LOOK AT 640x240.
  1. The speed: I bring the sign-off's numbers from the K2 (frames, passes, seconds). From them,
     decide where the time goes (the driver's real SS.BmLine cost against osrun.py's guess, lost
     ticks, the split's slack) and speed it up. Remedies already written down (docs/status.md,
     "The split frame"): real costs in the budgets, overlapping the logic with the drawing as the
     arcade does, the raster row as an exact clock (a new absolute-address exception: my call),
     and interpreter tuning; tline S measures the driver directly.
  2. 640x240: find out from the new core's RTL (and whatever the developer sent) how the mode is
     set and what the line engine and SS.BmLine/SS.BmClear need for it; whether grfdrv256 needs
     changes (propose any SS call change for my review first); what it costs the port (bitmap
     memory ~19 blocks a bitmap, the clear, the text bitmap, the interpreter's scale and clip).
Update docs/status.md as pieces land; stop and report at the end.

WHAT ONLY I CAN SUPPLY: hardware runs (tline once the core is fixed), new cores, and the decisions.

GROUND RULES (from Joust, all still in force): Level 2 only. Position-independent code, OS-9 program
modules, data through DP/U; a "make pic" check like Joust's tools/piccheck.py. No direct MMU access from
programs (F$MapBlk and F$ClrBlk only). The approved absolute I/O addresses are the VS1053 at
$FF50-$FF57 and the math coprocessor at $FEE0-$FEFF (D8; tools/piccheck.py knows both). Addresses come from the rc16 memory map, https://nitrobotics.github.io/Wildbits/ and, above
both, the FPGA source in ~/projects/wild/joust/fpga-6809-cores-staging/, a READ-ONLY clone: never modify,
commit or push anything inside it (it does not have the DMA fix yet). Propose new SS call layouts, and
any change to an existing one, for my review before coding. DON'T MODIFY MAME, either copy.
tempest_orig/ is READ-ONLY reference: never edit it; work from copies in the scratchpad. Change one
thing per hardware run. Docs are the handoff: label a diagnosis untested until hardware confirms it.

TOOLING (all in the Joust tree, shared):
  - NitrOS-9 and the drivers: export NITROS9DIR=/home/magnus/projects/wild/joust/nitros9_complete/nitros9
    on EVERY command; build in $NITROS9DIR/recipes/wildbits/l2 with PLATFORM=k2 or jr2. Driver changes
    go to branch wb/multiterm and push to jfed6000/nitros9. NEVER "git add -A" there.
  - The Wildbits MAME: from $NITROS9DIR as
        mame/mame wbjr2 -window -skip_gameinfo -bios turbo -hard recipes/wildbits/l2/l2_wildbitsjr2.dsk
    It proves a program's logic, never its timing; -autoboot_command needs the two-character escape \n.
    Its source tree also holds MAME's Tempest, AVG and Math Box drivers (src/mame/atari/tempest.cpp,
    src/devices/video/avgdvg.cpp, src/mame/atari/mathbox.cpp): read them, don't touch them.
  - PUT MODULES ON A DISK WITH A TARGETED COPY, NEVER A BARE "make PLATFORM=k2":
        os9 del  l2_wildbitsk2.dsk,CMDS/prog
        os9 copy -o=0 path/to/prog l2_wildbitsk2.dsk,CMDS/prog
        os9 attr -q -pe -npw -pr -e -w -r l2_wildbitsk2.dsk,CMDS/prog
    Then copy it back out and cmp it, clearing the scratch file first.
  - lwasm with nosymbolcase: scan case-folded for clashes. A local label's (name@) scope ends at a BLANK
    line. A new source file must join the makefile's SOURCES or make silently checks old listings.
  - F$Sleep with X=1 only yields; X=2 waits one 60 Hz tick.
  - The game's tests: python3 tools/xlattest.py --src (named tests, ~10 min at -n 1000), --src --fuzz
    -n 30 (~25 min), --src --states captures/states_play.bin captures/states_attract.bin (~3 min).
    The captures are regenerable (command in docs/status.md, "D6 hand work", 4); run the fuzz in the
    background and never "pkill -f" a pattern your own command line contains.
  - The module: cd src; make (budget and pic); make EXTRA="-DRECUS=170" tries a budget. The host
    run: python3 tools/osrun.py --seconds 60 [--png DIR --every N] [--passes] (~2 min a simulated
    minute). avgtest.py --batch 0 tests AvgFlush's changing batch sizes. The Wildbits MAME types and
    snaps from a Lua -autoboot_script (it replaces -autoboot_command; keep the notifier's
    subscription in a global or it is collected after one frame).
  - The interpreter's test: python3 tools/avgtest.py captures/avg_play.bin captures/avg_attract.bin
    (~8 min; --sw for the software multiply) and --fuzz 10000 (~5 min). avgview.py --verify, --compare,
    --port [--png DIR --frames N]. The avg_*.bin captures are regenerable (docs/status.md, stage 2).
  - The D6 pilot test: python3 tools/d6pilot.py (-n cases; ~90 s at 2,000). It calls lwasm.orig --6809
    directly: the coco-shelf "lwasm" wrapper adds --map/--list and fails with --format=raw. The
    listing's cycle counts are 6809 ones only with --6809 (without it lwasm counts 6309 cycles).
  - The .MAC sources use CRLF line endings, and ALSOUN/MBUDOC have stray CRs: normalise a copy with
    sed 's/\r$//' | tr '\r' ' ' so line numbers match the originals.
```
