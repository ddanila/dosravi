#include "dosravi.h"
#include <stdio.h>
#include <string.h>

static int failures = 0;

static void check(int condition, const char *message)
{
    if (!condition) {
        fprintf(stderr, "FAIL: %s\n", message);
        ++failures;
    }
}

int main(void)
{
    static const dr_u8 check_text[] = "123456789";
    static const dr_u8 cobs_input[] = {0, 1, 2, 0, 3, 0, 0, 4};
    dr_u8 encoded[DR_MAX_ENCODED + 1];
    dr_u8 decoded[64];
    dr_frame input;
    dr_frame output;
    dr_decoder stream;
    int length;
    int decoded_length;
    int index;
    int got;
    static const dr_u8 python_fixture[] = {
        0x03, 0x01, 0x01, 0x01, 0x06, 0x12, 0x34, 0x56,
        0x78, 0x03, 0x01, 0x01, 0x02, 0x06, 0x02, 0x41,
        0x02, 0x42, 0x05, 0x43, 0x44, 0xed, 0xc3, 0x00
    };

    check(dr_crc16(check_text, 9) == 0x29b1U, "CRC-16 check vector");
    check(dr_crc32_update(0, check_text, 9) == 0xcbf43926UL,
          "CRC-32 check vector");
    check(dr_crc32_update(dr_crc32_update(0, check_text, 4),
                          check_text + 4, 5) == 0xcbf43926UL,
          "CRC-32 incremental check vector");
    length = dr_cobs_encode(cobs_input, sizeof(cobs_input), encoded,
                            sizeof(encoded));
    check(length > 0, "COBS encode");
    decoded_length = dr_cobs_decode(encoded, (dr_u16)length, decoded,
                                    sizeof(decoded));
    check(decoded_length == (int)sizeof(cobs_input), "COBS decoded length");
    check(memcmp(cobs_input, decoded, sizeof(cobs_input)) == 0,
          "COBS round trip");

    memset(&input, 0, sizeof(input));
    input.version = DR_VERSION;
    input.type = DR_FRAME_REQUEST;
    input.flags = 0;
    input.transaction = 0x78563412UL;
    input.sequence = 3;
    input.payload_length = 6;
    memcpy(input.payload, "A\0B\0CD", 6);
    length = dr_frame_encode(&input, encoded, sizeof(encoded));
    check(length > 0, "frame encode");
    check(length == (int)sizeof(python_fixture) &&
          memcmp(encoded, python_fixture, sizeof(python_fixture)) == 0,
          "frame matches frozen Python fixture");
    check(dr_frame_decode(encoded, (dr_u16)length, &output) == 0,
          "frame decode");
    check(output.transaction == input.transaction, "transaction round trip");
    check(output.sequence == input.sequence, "sequence round trip");
    check(output.payload_length == input.payload_length, "payload length");
    check(memcmp(output.payload, input.payload, input.payload_length) == 0,
          "payload round trip");

    dr_decoder_init(&stream);
    got = 0;
    for (index = 0; index < length; ++index)
        if (dr_decoder_byte(&stream, encoded[index], &output) == 1)
            ++got;
    check(got == 1, "stream decoder emits frame");

    encoded[length / 2] ^= 0x40U;
    check(dr_frame_decode(encoded, (dr_u16)length, &output) != 0,
          "corrupt frame rejected");

    if (failures != 0) {
        fprintf(stderr, "%d test(s) failed\n", failures);
        return 1;
    }
    puts("C protocol tests passed");
    return 0;
}
