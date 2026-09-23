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

WHERE THINGS STAND (2026-09-23): STAGE 0 COMPLETE; D6 PILOT, TRANSLATOR (xlat/) AND THE D6 HAND
WORK DONE, all host only. The hand work is FOR REVIEW (docs/status.md, "D6 hand work"; not yet
committed):
  - src/ is the game, hand-finished from the draft (28,352 bytes): WORSCR and CASCAL on the
    coprocessor (CASCAL's Math Box overflow reproduced exactly), src/reloc.a relocating the address
    tables at start-up, the BIT/flag/decimal sites, GETOP3, and COIN65 (ALCOIN) in 6809.
  - tools/xlattest.py --src tests it: named tests with code, data area and window all moved; the
    fuzz; and --states, whole game frames (EXSTAT, NONSTA, DISPLA) from MAME's own RAM, recorded by
    tools/avgcap.lua AVGCAP_RAM into captures/ (regenerable). All 2,417 recorded frames (a played
    game and attract) are byte-exact against the Rev 3 ROM; the game logic costs 7.5 ms a frame.
  - Found and fixed on the way: ZATC4V anti-tamper (now in docs/port-tempest.md 2.4), a cross-file
    label distance the draft relied on (MSGLBS).
  - HAND markers left (78) are the platform layer's: hardware shadows, the IRQ, RESET, the dropped
    self-test's dispatch entries.

DECIDED: Rev 3; D3 glyph masks on a front text bitmap; D4 keyboard (arrows, Shift fire, z zapper) +
mouse (SS.MsDelta, approved) + joystick, no spinner; D6 model B and its conventions; D8 math
coprocessor approved; hand-finished code in src/ (xlat/ generated, never edited). The rest of the
plan's recommendations stand unless I say otherwise.

HARDWARE: the rc16 line engine DROPS PIXELS (gaps that move run to run; K2, two cores). The FPGA
developer is on it and we ASSUME A FIX. Re-run bmtest C then L, and C then F, on each new core.

THIS SESSION: first my answers to docs/status.md "D6 hand work", "For review" (ZATC4V; CASCAL's exact
overflow path; the data area to $B9D), and whether to commit. Then, unless I choose otherwise, the
proposed next step: stage 2's interpreter on the host - the 6809 AVG interpreter, run on the host
6809 over stage 0's captured frames and checked record for record against tools/avgview.py (its
hardware half waits for the fixed core). Propose any SS call it needs before coding it; no SS call
code until I approve it. Update docs/status.md as pieces land; stop and report at the end.

WHAT ONLY I CAN SUPPLY: hardware runs (tline once the core is fixed), new cores, and the decisions.

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
  - The game's tests: python3 tools/xlattest.py --src (named tests, ~10 min at -n 1000), --src --fuzz
    -n 30 (~25 min), --src --states captures/states_play.bin captures/states_attract.bin (~3 min).
    The captures are regenerable (command in docs/status.md, "D6 hand work", 4); run the fuzz in the
    background and never "pkill -f" a pattern your own command line contains.
  - The D6 pilot test: python3 tools/d6pilot.py (-n cases; ~90 s at 2,000). It calls lwasm.orig --6809
    directly: the coco-shelf "lwasm" wrapper adds --map/--list and fails with --format=raw. The
    listing's cycle counts are 6809 ones only with --6809 (without it lwasm counts 6309 cycles).
  - The .MAC sources use CRLF line endings, and ALSOUN/MBUDOC have stray CRs: normalise a copy with
    sed 's/\r$//' | tr '\r' ' ' so line numbers match the originals.
```
