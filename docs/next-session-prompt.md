# Next session prompt

Paste the block below to start the next session, from ~/projects/wild/tempest.

```
We're porting Atari's arcade TEMPEST (Rev 3, the source's "2A(alt)") to NitrOS-9 Level 2 on the
Wildbits F256 (6809, rc16 FPGA core, K2 and Jr2). Joust, the first game on this platform, is finished in
~/projects/wild/joust. This folder is a local git repo (main and hires640, no remote until I say so).

READ FIRST:
  - docs/status.md: state, decisions, hardware findings, stage 0's numbers. Start here.
  - docs/port-plan.md: the plan (section 5 decisions, section 6 SS call proposals).
  - docs/port-tempest.md: the survey of tempest_orig/src, file by file, with line numbers.
  - ~/.claude/projects/-home-magnus-projects-wild-joust/memory/MEMORY.md and the files it points at:
    Joust's platform rules, which apply here unchanged.
  - docs/port-guide.md (generic platform guide) and, from ~/projects/wild/joust/docs, only as needed:
    grfdrv256-api.md, bitmap-api.md, driver-performance.md.

WHERE THINGS STAND (2026-09-23, end of the optimisation session; docs/status.md "Optimising, and
640x240" has it all):
  - main 6b76ef7 + dacdbbb: the split frame (one pass a tick), the clear armed in the logic pass
    (SS.BmClear mode 7 waited a whole tick for vertical blank: one tick lost a game frame), the
    text list matched with a look-ahead (the high score screen no longer redraws every entry).
    K2, 320: 15.4 game frames and 59.8 passes a second.
  - BRANCH hires640 (checked out): the lines AND the text on 640x240 4-bit planes (SS.BmCfg
    HIRES4, CLUT 1, colour + 1 as the nibble, intensity 12); glyphs rendered at 640 with 1-dot
    strokes (tools/glyphs.py --hires); text columns in 640ths from the beam's fraction (avg.a
    AVTX64). K2: 13.0 game frames a second with attract in the run, no ticks lost; "looks
    better". The logo's smear is the 240 rows (MAME's own frame drawn at 640x240 shows it).
    Line endpoints are still a 320 position doubled. Not merged into main: my call.
  - nitros9 wb/multiterm ec0cc198 (committed, NOT PUSHED): SS.BmLine takes X to 639 with a
    640-pixel FIFO margin on a HIRES4 plane. On both disk images with the hires640 tempest.
  - tools/osrun.py now models the DMA engine's vertical-blank timing, GetStat SS.BmClear's
    diagnostic R$Y/R$U, SS.BmCfg, 4-bit planes and CLUT 1.

THIS SESSION: Q&A AND BRAINSTORMING ON PERFORMANCE. I want to understand what the interpreter
(src/avg.a, its specification tools/avgview.py PortAVG, docs/status.md "Stage 2 on the host") does:
walk me through it at my pace, answer questions, and brainstorm where the frame's time goes and how
to win it back (the numbers: docs/status.md "Time", "The split frame", "Optimising"). Explain and
propose; change code only when I ask. Candidate ideas already written down: tighter budget
estimates (RECUS), overlapping the logic with the drawing, the raster row as an exact clock (a new
absolute-address exception, my call), faster glyph drawing, fewer logo copies, tline S.

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
