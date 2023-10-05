volatile unsigned int * const UART0DR = (unsigned int *)0x1C090000;
volatile unsigned int * const UART1DR = (unsigned int *)0x1C0A0000;
volatile unsigned int * const UART2DR = (unsigned int *)0x1C0B0000;
volatile unsigned int * const UART3DR = (unsigned int *)0x1C0C0000;

extern void uart_init(volatile void *);

void printc_uart(const char c) {
	// *UART0DR = (unsigned int)(c);
	// *UART1DR = (unsigned int)(c);
	*UART2DR = (unsigned int)(c);
	// *UART3DR = (unsigned int)(c);
}


void prints_uart(const char *s) {
	for (const char* c = s; *c != '\0'; c++) {
		printc_uart(*c);
	}
}

void c_entry() {
	uart_init(UART2DR);
	//uart_init(UART3DR);

	for (;;) {
		for (char a = '0'; a <= '9'; a++)
		for (char b = '0'; b <= '9'; b++)
		for (char c = '0'; c <= '9'; c++)
		for (char d = '0'; d <= '9'; d++) {
			printc_uart(a);
			printc_uart(b);
			printc_uart(c);
			printc_uart(d);
			prints_uart("Hello world!\r\n");
			for (volatile int i = 0; i < 5000000; i++);
		}
	}




	// *(int*)(0x42424242) = 0x42;

	// for (;;);
}