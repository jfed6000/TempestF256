# tempest - Tempest for NitrOS-9 Level 2 (Wildbits F256)
#
#   make                          build tempest; the budget and PIC checks
#   make install DSK=image.dsk    copy it to CMDS on a disk image (a targeted copy, nothing else)
#   make EXTRA="-DRECUS=170"      a build with a frame.a budget changed (touch tempest.asm first)
#
# The host tests build the game alone from tempest.a (tools/xlattest.py --src, tools/avgtest.py).

NITROS9DIR ?= /home/magnus/projects/wild/joust/nitros9_complete/nitros9
AS          = lwasm.orig --6809 --format=os9 \
              --pragma=nosymbolcase,condundefzero,dollarnotlocal \
              --includedir=$(NITROS9DIR)/defs -I $(NITROS9DIR)/level2/wildbits -I . -Dwildbits=1 $(EXTRA)
PROGS       = tempest
# every source the module includes: a file missing here is not rebuilt (make sees no change)
SOURCES     = tempest.asm data.a platform.a frame.a input.a gfx.a text.a avg.a avgtab.a glyphs.a \
              alwelg.a alsco2.a aldis2.a alexec.a alsoun.a alvrom.a alcoin.a allang.a alhar2.a \
              alearo.a alvgut.a stubs.a hw.a reloc.a port.d arcade.d vrom.bin \
              $(NITROS9DIR)/defs/wildbits.d

all: $(PROGS) budget pic

tempest: $(SOURCES)
	$(AS) --list=$@.list --map=$@.map -o $@ tempest.asm

# logical space (docs/port-plan.md section 3): the module, the data area (1 block), window A (1)
# and the service window (1) share the 8 blocks; the top block loses $FD00-$FFFF, so the module
# gets 5 blocks less 768 bytes.  Holds only while nothing maps more than those two windows at once.
budget: tempest
	@s=$$(stat -c %s tempest); echo "tempest is $$s bytes of 40192"; \
	test $$s -le 40192 || { echo "tempest is more than 5 blocks less 768"; exit 1; }

# the static position-independence check over the listing (tools/piccheck.py); a reviewed
# exception carries pic:ok in its comment
pic: tempest
	python3 ../tools/piccheck.py tempest.list

install: tempest
	@test -n "$(DSK)" || { echo "usage: make install DSK=path/to/image.dsk"; exit 1; }
	-os9 del $(DSK),CMDS/tempest
	os9 copy -o=0 tempest $(DSK),CMDS/tempest
	os9 attr -q -pe -npw -pr -e -w -r $(DSK),CMDS/tempest

clean:
	rm -f $(PROGS) *.map *.list

.PHONY: all budget pic install clean
