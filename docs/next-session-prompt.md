# Next session prompt

Paste the block below to start the next session, from ~/projects/wild/tempest.

```
We're porting Atari's arcade TEMPEST (Rev 3, the source's "2A(alt)") to NitrOS-9 Level 2 on the
Wildbits F256 (6809, rc16 FPGA core, K2 and Jr2). Joust, the first game on this platform, is finished in
~/projects/wild/joust. This folder is a local git repo (branch main, no remote until I say so).

READ FIRST:
  - docs/port-plan.md: the plan. Section 5 is the decisions, section 6 the proposed SS call layouts.
  - docs/port-tempest.md: the survey of tempest_orig/src it rests on, file by file, with line numbers.
  - docs/port-guide.md: the generic platform guide (stale in three places; port-tempest.md's head says
    which).
  - ~/.claude/projects/-home-magnus-projects-wild-joust/memory/MEMORY.md and the files it points at:
    Joust's platform rules, which apply here unchanged.
  - From ~/projects/wild/joust/docs, only as needed: grfdrv256-api.md, bitmap-api.md (its section 15
    still says SS.BmLine runs with interrupts masked; it does not), driver-performance.md.

WHERE THINGS STAND (2026-09-22): the survey and the plan are written and committed. Nothing is built.
The findings that shape everything: the game advances once per 9 IRQs of 246.1 Hz (27.3 Hz, not 60);
the display is AVG display lists, which a 6809 interpreter will turn into SS.BmLine records; the Math
Box use is ONE divide, floor(dz*128/dy), exactly; the spinner is signed counts per game frame, 72 a
turn, clamped to +-31; sound is one table interpreter writing 8 POKEY channels; zero page is full;
tempest_orig contains anti-tamper checks that must be made to pass (port-tempest 2.4). Stock MAME 0.276
(/usr/games/mame) verifies the tempest set from tempest_orig/notebooks/roms, and runs Lua scripts.

THIS SESSION: I will open with my answers to the plan's decisions (D2-D10) and to the section 6
layouts. Take the plan's recommendation for any decision I do not answer, and say that you did. Then,
in order:
  1. Record the decisions in docs/port-plan.md section 5, and start docs/status.md (state, decisions,
     findings, open items) in the Joust shape.
  2. Stage 0: tools/m65parse.py, tools/avgcap.lua (stock MAME, unmodified, via -autoboot_script),
     tools/avgview.py. Render captured frames to PNG and put them beside MAME's own screenshots. Write
     the lines and pixels per frame, over attract mode and play, into docs/status.md. Check the screen
     mapping of port-tempest 4.4 against the renders.
  3. The D6 pilot: WORSCR, MODSND and one list builder, under both register models; size and cycles.
  Steps 2 and 3 are host work and need nothing from me. No game code beyond the pilot until I have
  seen its numbers. Do not code the section 6 calls until I approve them.

WHAT ONLY I CAN SUPPLY: the decisions; the hardware runs (bmtest's F key on the K2 first, then tline
when it exists); whether I have or will get a spinner and what kind; approval of the $FEE0 exception.
Don't wait on any of these to do the host work.

GROUND RULES (from Joust, all still in force): Level 2 only. Position-independent code, OS-9 program
modules, data through DP/U; a "make pic" check like Joust's tools/piccheck.py. No direct MMU access from
programs (F$MapBlk and F$ClrBlk only). The one approved absolute I/O address is the VS1053 at
$FF50-$FF57. Addresses come from the rc16 memory map, https://nitrobotics.github.io/Wildbits/ and, above
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
  - The .MAC sources use CRLF line endings, and ALSOUN/MBUDOC have stray CRs: normalise a copy with
    sed 's/\r$//' | tr '\r' ' ' so line numbers match the originals.
```
