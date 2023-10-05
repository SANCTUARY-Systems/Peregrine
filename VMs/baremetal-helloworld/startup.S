.global _reset
_reset:
	ADRP	x0, _stack_start
	MOV		sp, x0
	BL		c_entry
	B		.



#define DR   0x00
#define ECR  0x04
#define FR   0x18
#define CR   0x30

.global uart_init
.func uart_init
uart_init:
	// LDR		x0, =PLATFORM_PL011_BASE
	STR		wzr, [x0, #CR]
	STR		wzr, [x0, #ECR]
	STR		wzr, [x0, #DR]
	LDR		w1, =0x301
	STR		w1, [x0, #CR]
	RET