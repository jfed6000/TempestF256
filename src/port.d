* port.d - the approved conventions (docs/status.md, D6), for the translated game.
RXP	equ	$B8
RX	equ	$B9
RYP	equ	$BA
RY	equ	$BB
POKIMG	equ	$0800		POKEY register image (AUDF1 at +0, AUDF2 at +8)
VWIN	equ	$0810		window A's logical address, for absolute vector RAM
CLRSHD	equ	$0820		colour RAM's shadow, committed by SS.ClutWrite
HWSHAD	equ	$0900		shadows of the other hardware registers (HAND)
HW_0C00	equ	HWSHAD+0
HW_0D00	equ	HWSHAD+1
HW_0E00	equ	HWSHAD+2
HW_4000	equ	HWSHAD+3
HW_4800	equ	HWSHAD+4
HW_5000	equ	HWSHAD+5
HW_5800	equ	HWSHAD+6
HW_6000	equ	HWSHAD+7
HW_6040	equ	HWSHAD+8
HW_6050	equ	HWSHAD+9
HW_6060	equ	HWSHAD+10
HW_6070	equ	HWSHAD+11
HW_6080	equ	HWSHAD+12
HW_6081	equ	HWSHAD+13
HW_6083	equ	HWSHAD+14
HW_6084	equ	HWSHAD+15
HW_6085	equ	HWSHAD+16
HW_6086	equ	HWSHAD+17
HW_6087	equ	HWSHAD+18
HW_6089	equ	HWSHAD+19
HW_608C	equ	HWSHAD+20
HW_608D	equ	HWSHAD+21
HW_608E	equ	HWSHAD+22
HW_608F	equ	HWSHAD+23
HW_6090	equ	HWSHAD+24
HW_6094	equ	HWSHAD+25
HW_6095	equ	HWSHAD+26
HW_6096	equ	HWSHAD+27
HW_60C8	equ	HWSHAD+28
HW_60CA	equ	HWSHAD+29
HW_60CB	equ	HWSHAD+30
HW_60CF	equ	HWSHAD+31
HW_60D8	equ	HWSHAD+32
HW_60DA	equ	HWSHAD+33
HW_60DB	equ	HWSHAD+34
HW_60DF	equ	HWSHAD+35
HW_60E0	equ	HWSHAD+36

AVGPG	equ	$0C00		the AVG interpreter's page, DP while it runs (avg.a)

* The integer coprocessor (D8, the approved absolute exception): 16/16 unsigned divide and
* 16x16 unsigned multiply, all big-endian (JR_Math_Block.v).  Shared with other programs (fm), so every use is masked.
CP.MA	equ	$FEE0		multiplicand (16x16 unsigned multiply, combinational)
CP.MB	equ	$FEE2		multiplier
CP.DVSR	equ	$FEE4		divisor
CP.DVND	equ	$FEE6		dividend
CP.PROD	equ	$FEF0		product, 32 bits
CP.QUOT	equ	$FEF4		quotient
CP.REM	equ	$FEF6		remainder (right from rc14 on)

* Tables that hold addresses, copied here at start-up with run-time addresses (reloc.a RELINI).
* Little-endian, as the translated code reads them a byte at a time.
RELTAB	equ	$0A00
R.BUF	equ	RELTAB			BUFASL, BUFBSL, BUFSWL: 27 vector-RAM addresses (window A)
R.BUFA	equ	R.BUF			  BUFASL (BFASTA = +6)
R.BUFB	equ	R.BUF+18		  BUFBSL (BFBSTA = +12)
R.BUFS	equ	R.BUF+36		  BUFSWL
R.LNG	equ	R.BUF+54		LNGTAB: the four languages' message tables, below
R.MSG	equ	R.LNG+8			ENGMSG, FREMSG, GERMSG, SPAMSG: 4 x 30 message addresses (module)
R.WTAB	equ	R.MSG+240		WTABLE: 28 pairs, a module table and a RAM variable
RELEND	equ	R.WTAB+112
