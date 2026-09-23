# Next session prompt

Paste the block below to start the next session, from ~/projects/wild/tempest.

```
We're starting a port of Atari's arcade TEMPEST to NitrOS-9 Level 2 on the Wildbits F256 (6809, rc16
FPGA core, K2 and Jr2). It is the second game on this platform. The first, Joust, is finished and lives
in ~/projects/wild/joust: its code, its docs and the driver work it needed. This folder is the new
project and nothing is built yet.

WHAT IS HERE
  - tempest_orig/ is Atari's original source, from the 2021 historicalsource release, with mwenge's
    notes on rebuilding it: src/*.MAC is MAC65 6502 assembler (ALEXEC, ALDISP, ALSOUN, ALWELG, ALSCOR,
    ...), MBUCOD is the Math Box microcode, TEMPST.DOC is Atari's own documentation, and notebooks/ has
    the ROM reconstruction, the well geometry and the sound work. It is READ-ONLY reference: never
    edit it.
  - docs/port-guide.md is the generic guide to porting a game to this platform, written from Joust.
    docs/port-tempest.md is its Tempest companion, a survey written BEFORE most of the driver work
    below existed, so parts of it are out of date.
  - This folder is not a git repository yet. Make it one first ("git init -b main"), with a .gitignore
    for *.list, *.map and built modules, and commit the docs and tempest_orig/ as they stand. It stays
    local: no remote until I say so.

READ FIRST, from ~/projects/wild/joust:
  - ~/.claude/projects/-home-magnus-projects-wild-joust/memory/MEMORY.md and the files it points at.
    This project has its own memory directory, so Joust's does not load on its own, and most of those
    entries are platform rules that apply here unchanged.
  - docs/grfdrv256-api.md: every driver call's register layout. docs/bitmap-api.md: the bitmap group,
    which is the part Tempest lives in. docs/driver-performance.md: what a call costs (one I$SetStt is
    about 474 us; CALL COUNT is the only lever that has ever moved the frame time).
  - docs/tile-plan.md or docs/sprite-registration-plan.md: the model for how a plan is written here.
  - docs/status.md in Joust only as far as you need it; it is long.

WHAT THE PLATFORM ALREADY GIVES TEMPEST (all confirmed on K2 unless it says otherwise):
  - SS.BmLine draws a BATCH of lines with the rc16's hardware line engine: 8-byte records, a colour per
    record, up to 255 a call, and it stops early rather than overflow the engine's 4,096-pixel FIFO,
    returning how many it drew. What nobody has measured is VOLUME: pixels drained per frame, and so
    lines per frame. bmtest's F key (255 full-width lines, the flood case) has never been pressed.
  - SS.BmClear fills a bitmap with the DMA engine: 76,800 bytes in about 384 us 16-bit, one call,
    synchronous with wait mode 7 (DmaWt.Poll). THE rc16 DMA WAS FIXED ON 2026-09-22 and Joust uses it.
    That answers port-tempest.md's "erasing is the part with no obvious answer": two bitmaps, draw into
    the hidden one, clear it with one call. An UNFIXED core still wedges on this path.
  - Two or three bitmaps, a CLUT per layer, tile maps and sprites, all through grfdrv256. Joust's
    pattern for assets: F$AllRAM blocks outside the 64K, mapped one block at a time.
  - Input: SS.KyLive/SS.KyDwn for held keys, SS.Joy for sticks. No spinner call exists.
  - Sound: the VS1053 at $FF50-$FF57, direct I/O approved, PCM streamed with a metered feed. There is
    no POKEY on the F256.
  - The integer math coprocessor is the Math Box's natural replacement (port-tempest.md section 4).

THIS SESSION'S WORK, in order. No game code until I have approved the plan.
  1. git init and the first commit, as above.
  2. Survey tempest_orig/src: what each .MAC file does, how big it is, where the display-list build,
     the well geometry, the Math Box calls, the spinner read and the POKEY writes live. Write it into
     docs/port-tempest.md, and correct everything in that file the driver work has overtaken
     (SS.BmLine, SS.BmClear, the DMA fix). Label anything not yet checked as unchecked.
  3. Decide which revision to port (Rev 1 or Rev 2A(Alt), per tempest_orig's notebooks) and say why.
  4. Write docs/port-plan.md in the shape of the Joust plans: the stages, the harness programs, and the
     decisions I have to make, each with a recommendation. The ones I already know about: geometry-
     faithful or appearance-faithful (it drives the CLUT, since beam intensity has to become colour);
     line-drawn text or glyph masks; the spinner (what hardware, and what call reads it); POKEY sound
     (samples through the VS1053 like Joust, or synthesis); and the 6502-to-6809 translation method.
  5. Propose any NEW SS call layouts (a spinner read, a line call shape Tempest needs) for my review.
     Do not code them.

WHAT ONLY I CAN SUPPLY: hardware runs (the first is bmtest's F key on the K2, for the line-volume
number), whether I have or will get a spinner, and the answers to the plan's decisions. Everything else
is yours: don't wait on these to do the survey and the plan.

GROUND RULES (from Joust, all still in force): Level 2 only. Position-independent code, OS-9 program
modules, data through DP/U; a "make pic" check like Joust's tools/piccheck.py. No direct MMU access
from programs (F$MapBlk and F$ClrBlk only). The one approved absolute I/O address is the VS1053 at
$FF50-$FF57. Addresses come from the rc16 memory map, https://nitrobotics.github.io/Wildbits/ and, above
both, the FPGA source in ~/projects/wild/joust/fpga-6809-cores-staging/, a READ-ONLY clone: never modify,
commit or push anything inside it. It does not have the DMA fix yet; I will update it when the developer
commits. Propose new SS call layouts, and any change to an existing one, for my review before coding.
DON'T MODIFY MAME. Change one thing per hardware run. Docs are the handoff: label a diagnosis untested
until hardware confirms it.

TOOLING (all in the Joust tree, shared):
  - NitrOS-9 and the drivers: export NITROS9DIR=/home/magnus/projects/wild/joust/nitros9_complete/nitros9
    on EVERY command; build in $NITROS9DIR/recipes/wildbits/l2 with PLATFORM=k2 or jr2. Driver changes
    go to branch wb/multiterm and push to jfed6000/nitros9. NEVER "git add -A" there: about 80 untracked
    files, including an embedded mame repo.
  - MAME: $NITROS9DIR/mame renders bitmaps, tile maps and sprites, and does the DMA instantly, so it
    proves a program's logic but never its timing. Whether it emulates the line engine at all is
    unchecked. Run it from $NITROS9DIR as
        mame/mame wbjr2 -window -skip_gameinfo -bios turbo -hard recipes/wildbits/l2/l2_wildbitsjr2.dsk
    and headless with -video none -sound none -nothrottle -seconds_to_run N; -autoboot_command needs
    the two-character escape \n, not a real newline.
  - PUT MODULES ON A DISK WITH A TARGETED COPY, NEVER A BARE "make PLATFORM=k2" (the image target
    reformats and wipes everything added by hand):
        os9 del  l2_wildbitsk2.dsk,CMDS/prog
        os9 copy -o=0 path/to/prog l2_wildbitsk2.dsk,CMDS/prog
        os9 attr -q -pe -npw -pr -e -w -r l2_wildbitsk2.dsk,CMDS/prog
    Name the destination explicitly: os9 copy otherwise names it after the source's basename. Then
    copy it back out and cmp it, clearing the scratch file first.
  - .mods is shared between platforms and normally holds the K2 build; grfdrv256 differs between them.
  - lwasm with nosymbolcase: symbols are case-insensitive, so scan case-folded for clashes. A local
    label's (name@) scope ends at a BLANK line. A new source file must join the makefile's SOURCES or
    make silently checks old listings.
  - F$Sleep with X=1 only yields; X=2 waits one 60 Hz tick.
  - Cards: I write them with dd; check lsblk first, and read back and compare.
```
