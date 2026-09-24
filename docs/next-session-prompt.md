# Next session prompt

Paste the block below to start the next session, from ~/projects/wild/tempest.

```
We're porting Atari's arcade TEMPEST (Rev 3, the source's "2A(alt)") to NitrOS-9 Level 2 on the
Wildbits F256 (6809, rc16 FPGA core, K2 and Jr2). Joust, the first game on this platform, is finished in
~/projects/wild/joust. This folder is a git repo (main and hires640), remote origin https://github.com/jfed6000/TempestF256 (public).

READ FIRST:
  - docs/status.md: state, decisions, hardware findings, stage 0's numbers. Start here.
  - docs/port-plan.md: the plan (section 5 decisions, section 6 SS call proposals).
  - docs/port-tempest.md: the survey of tempest_orig/src, file by file, with line numbers.
  - ~/.claude/projects/-home-magnus-projects-wild-joust/memory/MEMORY.md and the files it points at:
    Joust's platform rules, which apply here unchanged.
  - docs/port-guide.md (generic platform guide) and, from ~/projects/wild/joust/docs, only as needed:
    grfdrv256-api.md, bitmap-api.md, driver-performance.md.

WHERE THINGS STAND (2026-09-24, end of the performance session; docs/status.md from "Hardware:
the collapse and BmWait build works" on has every step, each marked confirmed or untested):
  - BRANCH hires640 (checked out, c0a1f59, 39 commits past main, not merged: my call). 640x240
    HIRES4 planes. K2: 19.8 game frames a second (4,230 in 214 s, 5 dropped), up from 13.0.
    In order: small shapes collapsed to dots (AVCOLL), BmWait gone, sound on the two SIDs
    (POKEY image; the SIDs reached by a direct MMU slot write, interrupts masked: SidOn/SidOff,
    an approved exception), layers (0 tile map off, 1 lines, 2 text and the well), the well
    cached and skipped while its SWWELL word and colour hold (AVWELL), the 8,192-entry line FIFO,
    the stick read only when used, the SOL clock (/fSOL line-0 signal counts ticks, passes catch
    up lost ticks, muted in pause), no split (a game frame = a logic pass + a whole drawing; the
    budgets removed), the title logo: every other trail copy skipped (LOGSKP 2), the merge 4 a
    frame and the hold set to 90 frames (LOGOQK, LOGMS, LOGHD). All confirmed on the K2.
  - nitros9 wb/multiterm ec0cc198 (SS.BmLine X to 639 on HIRES4) and c45760ab (LD.Depth 8192,
    the new core's line FIFO): committed, NOT PUSHED. Installed on both disk images.
  - main dacdbbb: the 320 build from 2026-09-23 (15.4 game frames a second).

NEXT SESSION: my call. Open items: docs/status.md "Open items".

GROUND RULES (from Joust, all still in force): Level 2 only. Position-independent code, OS-9 program
modules, data through DP/U; a "make pic" check like Joust's tools/piccheck.py. No direct MMU access from
programs (F$MapBlk and F$ClrBlk only) except SidOn/SidOff's slot write (approved 2026-09-23). The
approved absolute I/O addresses are the VS1053 at $FF50-$FF57, the math coprocessor at $FEE0-$FEFF
(D8) and the MMU at $FFA0-$FFAF (tools/piccheck.py knows all three). Addresses come from the rc16 memory map, https://nitrobotics.github.io/Wildbits/ and, above
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
