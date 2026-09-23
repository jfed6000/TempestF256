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

WHERE THINGS STAND (2026-09-22): STAGE 0 IS COMPLETE (host only, all committed). The tools:
tools/avgcap.lua (stock MAME + Lua: display-list capture, a scripted player, 6502 frame timing, POKEY
log), tools/avgview.py (literal port of MAME's Tempest AVG, 320x240 renderer, matches MAME's own
snapshots), tools/glyphs.py (the D3 font from the vector ROM), tools/m65parse.py (the MAC65 reader).
Captures go to captures/ (gitignored; regenerate with the tools). Key numbers: a played frame needs
148 line records median, 305 max, once characters are glyphs; pixels <= ~3.6K; the 6502 works 21.4 ms
of each 36.6 ms game frame (27.1 Hz), 99% 41 ms; indexed addressing is ~15% of live instructions.

DECIDED: Rev 3; D3 glyph masks on a front text bitmap; D4 keyboard (arrows, Shift fire, z zapper) +
mouse (SS.MsDelta, approved) + joystick, no spinner; D8 math coprocessor approved. The rest of the
plan's recommendations stand unless I say otherwise.

HARDWARE: the rc16 line engine DROPS PIXELS (gaps that move run to run; K2, two cores). The FPGA
developer is on it and we ASSUME A FIX. Re-run bmtest C then L, and C then F, on each new core.

THIS SESSION: the D6 pilot. Translate WORSCR (ALDIS2:2208), MODSND (ALSOUN:270) and one display-list
builder that uses STA NY,VGLIST into 6809, under the plan's two register models (A: 6502 X in B via
ABX, Y in a page-1 byte; B: X and Y both in page-1 bytes), position-independent, lwasm. Measure size
and cycles for each, check each against Atari's routine with a host 6502 emulator on the same inputs
(the ROMs rebuild byte-identical, so the original binary is the oracle), and recommend a model with
the size ratio it implies for the 40,192-byte module. Write it into docs/status.md. Then stop for my
review before any translator or game code. No SS call code until I approve it.

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
  - The .MAC sources use CRLF line endings, and ALSOUN/MBUDOC have stray CRs: normalise a copy with
    sed 's/\r$//' | tr '\r' ' ' so line numbers match the originals.
```
