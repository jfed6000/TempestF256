# TempestF256

This is a port of the source code located at https://github.com/mwenge/tempest, Atari's arcade
Tempest (Rev 3), to NitrOS-9 Level 2 on the Wildbits F256 K2 and Jr2.

That repository builds on the original source released at
https://github.com/historicalsource/tempest. Tempest is © Atari. A copy of the mwenge repository
is kept, unchanged, in `tempest_orig/` as the port's reference.

- `src/`: the port (the game's 6502 code translated to 6809, and the NitrOS-9 platform layer)
- `tools/`: host-side models and tests
- `docs/`: the port's plan, survey and status

The 640x240 build is on `main` (merged from `hires640`). It is feature-complete and plays at about 27
game frames a second on a 12 MHz K2 (the arcade's 27.1).

Build: `cd src; make` for the production module; `make EXTRA="-DDIAG"` (after `touch tempest.asm`)
for a diagnostic one whose sign-off adds the run's numbers. `make install DSK=path/to/image.dsk`
copies it to `CMDS` on a disk image.
