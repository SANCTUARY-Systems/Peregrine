ENTRY(_reset)

SECTIONS {
	. = 0xef000000;
	.startup . : { startup.*(.text) }
	.text : { *(.text) }
	.data : { *(.data) }
	.bss : { *(.bss COMMON) }
	. = ALIGN(8);
	. = . + 0x1000; /* 4kB of stack memory */
	_stack_start = .;
}