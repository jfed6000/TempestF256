# Next session prompt

Paste the block below to start the next session, from ~/projects/wild/tempest.

```
We're porting Atari's arcade TEMPEST (Rev 3, the source's "2A(alt)") to NitrOS-9 Level 2 on the
Wildbits F256 (6809, rc16 FPGA core, K2 and Jr2). Joust, the first game on this platform, is finished in
~/projects/wild/joust. This folder is a git repo (main, hires640, ff90-sound), remote origin https://github.com/jfed6000/TempestF256 (public).

READ FIRST:
  - docs/status.md: state, decisions, hardware findings, stage 0's numbers. Start here.
  - docs/port-plan.md: the plan (section 5 decisions, section 6 SS call proposals).
  - docs/port-tempest.md: the survey of tempest_orig/src, file by file, with line numbers.
  - ~/.claude/projects/-home-magnus-projects-wild-joust/memory/MEMORY.md and the files it points at:
    Joust's platform rules, which apply here unchanged.
  - docs/port-guide.md (generic platform guide) and, from ~/projects/wild/joust/docs, only as needed:
    grfdrv256-api.md, bitmap-api.md, driver-performance.md.

WHERE THINGS STAND (2026-09-27, end of session; docs/status.md from "Hardware: the collapse and BmWait build works"
on has every step, each marked confirmed or untested):
  - main (ff90-sound merged in 2026-09-27; ff90-sound kept). 640x240 HIRES4 planes. The K2 now
    runs the 6809 at 12 MHz: 26.9 game frames a second (2,524 in 94 s, 3 dropped; the arcade's
    27.1), up from 19.8 at 8 MHz. The ff90-sound merge brought: the SIDs through the new core's
    $FF90 sound block ($FF98 selector, $FF99 data; SidOn/SidOff and the MMU exception gone), the
    frame gate's IRQs past 9 carried (frame.a GamLog, FRCARY 4: before, frames took 3 ticks, a
    20-a-second cap whatever the CPU), KEYRATE 4 (keys and stick), all confirmed on the K2; and the
    superzapper on stick button 2 (JY.Btn2), untested: the user's stick wires both buttons to fire.
  - After the merge (2026-09-27, main): the K2 core ties stick buttons 1-2 open (no stick zap, no
    paddles; docs/status.md), so SNES pad 0 was added (input.a JoyA: d-pad, B fire, A zap; PADST
    guard; osrun.py --pad), untested on a real pad; left/right swapped for keys, stick and pad
    (confirmed in play) and reversed back in the rating ladder and initials (KnbRev, QSTATE
    $12/$16; the ladder confirmed by host trace only). The sign-off gained ticks, pauses and a line
    a game (frames, ticks, passes: platform.a GamStat), kept by the user. Module 40,187 of 40,192
    bytes.
  - The slowdown within a run (game 2 or 4: 11.6 frames a second, restart fixed it) was FOUND on the
    host and fixed in 57fd80d: gfx.a bcgo latched NODMA on SS.BmClear's E$DevBsy (a fill still
    outstanding after two logic passes in one frame, a dropped drawing between, allowed by the FRTIMR
    carry), so the CPU cleared 80K every frame. Busy is now success. Host replay 8.0 -> 23.0; NOT YET
    RUN ON THE K2 (check every game line of the sign-off stays ~27, and the sound). docs/status.md
    "The slowdown found". Module 40,191 of 40,192 bytes: 1 free.
  - Before that, in order: small shapes collapsed to dots (AVCOLL), BmWait gone, sound on the two
    SIDs (POKEY image), layers (0 tile map off, 1 lines, 2 text and the well), the well
    cached and skipped while its SWWELL word and colour hold (AVWELL), the 8,192-entry line FIFO,
    the stick read only when used, the SOL clock (/fSOL line-0 signal counts ticks, passes catch
    up lost ticks, muted in pause), no split (a game frame = a logic pass + a whole drawing; the
    budgets removed), the title logo: every other trail copy skipped (LOGSKP 2), the merge 4 a
    frame and the hold set to 90 frames (LOGOQK, LOGMS, LOGHD). All confirmed on the K2.
  - nitros9 wb/multiterm ec0cc198 (SS.BmLine X to 639 on HIRES4) and c45760ab (LD.Depth 8192,
    the new core's line FIFO): pushed to jfed6000/nitros9 2026-09-24. Installed on both disk images.
  - The 320 build: main before the merge, dacdbbb (15.4 game frames a second).

NEXT SESSION: my call. Open items: docs/status.md "Open items".

GROUND RULES (from Joust, all still in force): Level 2 only. Position-independent code, OS-9 program
modules, data through DP/U; a "make pic" check like Joust's tools/piccheck.py. No direct MMU access from
programs (F$MapBlk and F$ClrBlk only; SidOn/SidOff's exception retired 2026-09-24). The
approved absolute I/O addresses are the VS1053 at $FF50-$FF57, the math coprocessor at $FEE0-$FEFF
(D8) and the SIDs' selector and data at $FF98-$FF99 (tools/piccheck.py knows all three). Addresses come from the rc16 memory map, https://nitrobotics.github.io/Wildbits/ and, above
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
