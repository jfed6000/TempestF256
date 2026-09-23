********************************************************************
* tempest - Atari's Tempest (Rev 3) for NitrOS-9 Level 2 on the
*   Wildbits F256 (docs/port-plan.md).
*
* The game is Atari's 6502 translated to position-independent 6809
* and finished by hand (alwelg.a ... alvgut.a, tested byte for byte
* against the arcade ROM by tools/xlattest.py).  Its hardware is the
* platform layer's: the IRQ runs on a virtual 246 Hz clock (frame.a),
* the vector generator is an interpreter (avg.a) drawing through the
* line engine (gfx.a), text is glyph masks on a bitmap of its own
* (text.a), and the controls feed the arcade's switch bytes (input.a).
*
* Usage: tempest [s | n]      (s: the sound test; n: the game without sound)
*   5  coin      1 / 2  start      q  quit
*   left/right arrows turn, Shift fires, z superzaps; joystick 0 and
*   the mouse (with SS.MsDelta) too.
*
* Edt/Rev  YYYY/MM/DD  Modified by
* Comment
* ------------------------------------------------------------------
*   1      2026/09/23  Claude
* The platform layer: start-up, the frame loop and the virtual IRQ,
* input, the display, the text bitmap, the exit.
*   2      2026/09/23  Claude
* One pass a tick, as Joust: the game frame is split across passes, the
* drawing a coroutine that gives the tick back on a budget (SS.Tick,
* proposed for edition 1, is withdrawn).
********************************************************************

                    nam       tempest
                    ttl       Tempest for NitrOS-9 Level 2 (Wildbits)

                    ifp1
                    use       defsfile
                    endc

                    opt       c
                    include   port.d
                    include   arcade.d

tylg                set       Prgrm+Objct
atrv                set       ReEnt+rev
rev                 set       $00
edition             set       2

ModBeg              mod       eom,name,tylg,atrv,start,size the module's first byte (reloc.a)

                    include   data.a

name                fcs       /tempest/
                    fcb       edition

* the platform layer
                    include   platform.a
                    include   frame.a
                    include   input.a
                    include   gfx.a
                    include   text.a
                    include   sound.a             the POKEY image on the SIDs; tsnd
* the vector generator, and the tables it and the text bitmap read.  AvgFlush sizes each batch
* from the pass's budget (gfx.a NxtBat), so the drawing can give the tick back between them
                    include   avg.a
                    include   avgtab.a
                    include   glyphs.a
* the game, in the arcade's link order (as tempest.a, the host tests' build)
                    include   alwelg.a
                    include   alsco2.a
                    include   aldis2.a
                    include   alexec.a
                    include   alsoun.a
                    include   alvrom.a
                    include   alcoin.a
                    include   allang.a
                    include   alhar2.a
                    include   alearo.a
                    include   alvgut.a
                    include   stubs.a
                    include   hw.a
                    include   reloc.a
VROM                includebin vrom.bin           vector ROM (136002-138.np3), read by the CPU and the interpreter

                    emod
eom                 equ       *
                    end
