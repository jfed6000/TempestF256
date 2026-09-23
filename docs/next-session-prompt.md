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

WHERE THINGS STAND (2026-09-23): STAGE 0 COMPLETE; D6 PILOT DONE (model B and the pilot/pilot.d
conventions approved); D6 STEP 1, THE TRANSLATOR, DONE AND REVIEWED. All host only, all committed.
docs/status.md, sections "D6 pilot" and "D6 step 1: the translator", has the details and decisions:
  - tools/romalign.py aligns every source statement with the Rev 3 ROM (all 12 sections exact
    against ALEXEC.MAP): label addresses, data bytes, macro output.
  - tools/m65to09.py translates the whole game to model B 6809 into xlat/ (generated, gitignored,
    never edited): 28,013 bytes with vector ROM, code ratio 1.35, "* HAND:" markers for the rest.
  - tools/xlattest.py runs translated routines against the ROM on the host (MODSND, DSPNYM, or
    --fuzz for all 190 called routines; --trace shows where two paths part). 169 pass, 4 fail at
    HAND sites, 17 have no in-domain random case yet. tools/d6pilot.py still tests the pilot.

DECIDED: Rev 3; D3 glyph masks on a front text bitmap; D4 keyboard (arrows, Shift fire, z zapper) +
mouse (SS.MsDelta, approved) + joystick, no spinner; D6 model B and its conventions; D8 math
coprocessor approved. Translator review (2026-09-23): hand-finished code goes in src/, taken from
xlat/; the hand-work order below; a recorded-game-state test. The rest of the plan's
recommendations stand unless I say otherwise.

HARDWARE: the rc16 line engine DROPS PIXELS (gaps that move run to run; K2, two cores). The FPGA
developer is on it and we ASSUME A FIX. Re-run bmtest C then L, and C then F, on each new core.

THIS SESSION: the hand work, in the approved order, each piece re-tested with tools/xlattest.py
against the ROM before the next:
  1. WORSCR and CASCAL on the coprocessor (pilot/worscr.a is the model; CASCAL's divide is N=24,
     a 16-bit fraction, docs/port-tempest.md section 6.2), so the Math Box users get tested.
  2. Start-up relocation of the pointer tables and pointer constants (the "address-table",
     "vram-table" and address-constant HAND sites), Joust's reloc.a way.
  3. The six flag and BIT sites; PRORAT's decimal SBC; ALCOIN (COIN65) translated.
  4. The recorded-state test: extend tools/avgcap.lua to dump MAME's 2K RAM at game-frame
     boundaries in a played game, and run routines in xlattest.py from those states.
The hardware shadows (HW_xxxx) stay as the platform layer's seams for now. Update docs/status.md as
each piece lands; stop and report at the end. No SS call code until I approve it.

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
  - The D6 test: python3 tools/d6pilot.py (-n cases; ~90 s at 2,000). It calls lwasm.orig --6809
    directly: the coco-shelf "lwasm" wrapper adds --map/--list and fails with --format=raw. The
    listing's cycle counts are 6809 ones only with --6809 (without it lwasm counts 6309 cycles).
  - The .MAC sources use CRLF line endings, and ALSOUN/MBUDOC have stray CRs: normalise a copy with
    sed 's/\r$//' | tr '\r' ' ' so line numbers match the originals.
```
