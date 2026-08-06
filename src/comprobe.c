#include <stdio.h>
#include <string.h>

extern unsigned dr_uart_bios_base(unsigned index);
extern unsigned dr_uart_capability(unsigned base);
extern int dr_uart_loopback(unsigned base);
extern int dr_uart_external_loopback(unsigned base);
extern void dr_uart_save(unsigned base, unsigned char *state);
extern void dr_uart_restore(unsigned base, unsigned char *state);
extern void dr_uart_init(unsigned base, unsigned divisor);

static char *uart_name(capability)
unsigned capability;
{
    if (capability == 0xc0U) return "16550A-compatible FIFO";
    if (capability == 0x40U || capability == 0x80U) return "16550 FIFO fault/unknown";
    return "8250/16450-compatible (no usable FIFO detected)";
}

int main(argc, argv)
int argc;
char **argv;
{
    unsigned index;
    unsigned base;
    unsigned capability;
    int internal_result;
    unsigned baud_index;
    static unsigned bauds[] = {9600U, 19200U, 38400U, 57600U, 115200U};
    unsigned char state[7];
    int external;
    external = argc == 2 && (!strcmp(argv[1], "/EXTERNAL") ||
                             !strcmp(argv[1], "-EXTERNAL"));
    if (argc > 2 || (argc == 2 && !external)) {
        puts("Usage: COMPROBE [/EXTERNAL]");
        return 2;
    }
    puts("COMPROBE 0.1 - non-destructive BIOS/UART inventory");
    puts("Internal loopback temporarily changes MCR and restores it.");
    for (index = 0; index < 4; ++index) {
        base = dr_uart_bios_base(index);
        if (!base) {
            printf("COM%u: not present in BIOS data area\n", index + 1);
            continue;
        }
        dr_uart_save(base, state);
        dr_uart_init(base, 12U);
        capability = dr_uart_capability(base);
        internal_result = dr_uart_loopback(base);
        printf("COM%u: base %04X, %s, internal loopback %s\n",
               index + 1, base, uart_name(capability),
               internal_result ? "PASS" : "FAIL");
        if (external) {
            for (baud_index = 0; baud_index < sizeof(bauds) / sizeof(bauds[0]);
                 ++baud_index) {
                dr_uart_init(base, (unsigned)(115200UL / bauds[baud_index]));
                printf("  external loopback %u baud: %s\n", bauds[baud_index],
                       dr_uart_external_loopback(base) ? "PASS" : "FAIL");
            }
        }
        dr_uart_restore(base, state);
    }
    if (!external)
        puts("Run COMPROBE /EXTERNAL with an RS-232 loopback plug for the external test.");
    return 0;
}
