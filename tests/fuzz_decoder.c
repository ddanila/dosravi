#include "dosravi.h"
#include <stdio.h>

int main(void)
{
    dr_decoder decoder;
    dr_frame frame;
    int byte;
    dr_decoder_init(&decoder);
    while ((byte = getchar()) != EOF)
        dr_decoder_byte(&decoder, (dr_u8)byte, &frame);
    return decoder.length <= DR_MAX_ENCODED ? 0 : 1;
}
