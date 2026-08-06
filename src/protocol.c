#include "dosravi.h"
#include <string.h>

static void dr_put16(dr_u8 *data, dr_u16 value)
{
    data[0] = (dr_u8)(value & 0xffU);
    data[1] = (dr_u8)((value >> 8) & 0xffU);
}
static dr_u16 dr_get16(const dr_u8 *data)
{
    return (dr_u16)((dr_u16)data[0] | ((dr_u16)data[1] << 8));
}

static void dr_put32(dr_u8 *data, dr_u32 value)
{
    data[0] = (dr_u8)(value & 0xffUL);
    data[1] = (dr_u8)((value >> 8) & 0xffUL);
    data[2] = (dr_u8)((value >> 16) & 0xffUL);
    data[3] = (dr_u8)((value >> 24) & 0xffUL);
}

static dr_u32 dr_get32(const dr_u8 *data)
{
    return (dr_u32)data[0] |
           ((dr_u32)data[1] << 8) |
           ((dr_u32)data[2] << 16) |
           ((dr_u32)data[3] << 24);
}

dr_u16 dr_crc16(const dr_u8 *data, dr_u16 length)
{
    dr_u16 crc;
    dr_u16 index;
    int bit;
    crc = 0xffffU;
    for (index = 0; index < length; ++index) {
        crc ^= (dr_u16)((dr_u16)data[index] << 8);
        for (bit = 0; bit < 8; ++bit) {
            if (crc & 0x8000U)
                crc = (dr_u16)((crc << 1) ^ 0x1021U);
            else
                crc = (dr_u16)(crc << 1);
        }
    }
    return crc;
}

dr_u32 dr_crc32_update(dr_u32 crc, const dr_u8 *data, dr_u16 length)
{
    dr_u16 index;
    int bit;
    crc ^= 0xffffffffUL;
    for (index = 0; index < length; ++index) {
        crc ^= (dr_u32)data[index];
        for (bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ ((crc & 1UL) ? 0xedb88320UL : 0UL);
    }
    return crc ^ 0xffffffffUL;
}

int dr_cobs_encode(const dr_u8 *input, dr_u16 input_length,
                   dr_u8 *output, dr_u16 output_size)
{
    dr_u16 read_index;
    dr_u16 write_index;
    dr_u16 code_index;
    dr_u8 code;
    if (output_size == 0)
        return -1;
    read_index = 0;
    write_index = 1;
    code_index = 0;
    code = 1;
    while (read_index < input_length) {
        if (input[read_index] == 0) {
            output[code_index] = code;
            code_index = write_index++;
            if (write_index > output_size)
                return -1;
            code = 1;
            ++read_index;
        } else {
            if (write_index >= output_size)
                return -1;
            output[write_index++] = input[read_index++];
            ++code;
            if (code == 0xffU) {
                output[code_index] = code;
                code_index = write_index++;
                if (write_index > output_size)
                    return -1;
                code = 1;
            }
        }
    }
    output[code_index] = code;
    return (int)write_index;
}

int dr_cobs_decode(const dr_u8 *input, dr_u16 input_length,
                   dr_u8 *output, dr_u16 output_size)
{
    dr_u16 read_index;
    dr_u16 write_index;
    dr_u16 count;
    dr_u8 code;
    read_index = 0;
    write_index = 0;
    if (input_length == 0)
        return -1;
    while (read_index < input_length) {
        code = input[read_index++];
        if (code == 0)
            return -1;
        count = (dr_u16)(code - 1);
        if ((dr_u16)(input_length - read_index) < count)
            return -1;
        if ((dr_u16)(output_size - write_index) < count)
            return -1;
        while (count-- != 0)
            output[write_index++] = input[read_index++];
        if (code != 0xffU && read_index < input_length) {
            if (write_index >= output_size)
                return -1;
            output[write_index++] = 0;
        }
    }
    return (int)write_index;
}

int dr_frame_encode(const dr_frame *frame, dr_u8 *output, dr_u16 output_size)
{
    static dr_u8 raw[DR_MAX_RAW];
    dr_u16 raw_length;
    dr_u16 crc;
    int encoded_length;
    if (frame->payload_length > DR_MAX_PAYLOAD || output_size < 2)
        return -1;
    raw[0] = frame->version;
    raw[1] = frame->type;
    raw[2] = frame->flags;
    raw[3] = 0;
    dr_put32(raw + 4, frame->transaction);
    dr_put32(raw + 8, frame->sequence);
    dr_put16(raw + 12, frame->payload_length);
    memcpy(raw + DR_HEADER_SIZE, frame->payload, frame->payload_length);
    raw_length = (dr_u16)(DR_HEADER_SIZE + frame->payload_length);
    crc = dr_crc16(raw, raw_length);
    dr_put16(raw + raw_length, crc);
    raw_length = (dr_u16)(raw_length + 2);
    encoded_length = dr_cobs_encode(raw, raw_length, output,
                                    (dr_u16)(output_size - 1));
    if (encoded_length < 0)
        return -1;
    output[encoded_length++] = 0;
    return encoded_length;
}

int dr_frame_decode(const dr_u8 *encoded, dr_u16 encoded_length,
                    dr_frame *frame)
{
    static dr_u8 raw[DR_MAX_RAW];
    int raw_length;
    dr_u16 payload_length;
    dr_u16 actual_crc;
    dr_u16 expected_crc;
    if (encoded_length != 0 && encoded[encoded_length - 1] == 0)
        --encoded_length;
    raw_length = dr_cobs_decode(encoded, encoded_length, raw, DR_MAX_RAW);
    if (raw_length < DR_HEADER_SIZE + 2)
        return -1;
    if (raw[0] != DR_VERSION || raw[3] != 0)
        return -1;
    if (raw[1] < DR_FRAME_REQUEST || raw[1] > DR_FRAME_EVENT)
        return -1;
    payload_length = dr_get16(raw + 12);
    if (payload_length > DR_MAX_PAYLOAD ||
        raw_length != (int)(DR_HEADER_SIZE + payload_length + 2))
        return -1;
    expected_crc = dr_get16(raw + raw_length - 2);
    actual_crc = dr_crc16(raw, (dr_u16)(raw_length - 2));
    if (actual_crc != expected_crc)
        return -1;
    frame->version = raw[0];
    frame->type = raw[1];
    frame->flags = raw[2];
    frame->transaction = dr_get32(raw + 4);
    frame->sequence = dr_get32(raw + 8);
    frame->payload_length = payload_length;
    memcpy(frame->payload, raw + DR_HEADER_SIZE, payload_length);
    return 0;
}

void dr_decoder_init(dr_decoder *decoder)
{
    decoder->length = 0;
    decoder->discarding = 0;
}

int dr_decoder_byte(dr_decoder *decoder, dr_u8 byte, dr_frame *frame)
{
    int result;
    if (byte == 0) {
        if (decoder->discarding) {
            decoder->discarding = 0;
            decoder->length = 0;
            return 0;
        }
        if (decoder->length == 0)
            return 0;
        result = dr_frame_decode(decoder->encoded, decoder->length, frame);
        decoder->length = 0;
        return result == 0 ? 1 : -1;
    }
    if (decoder->discarding)
        return 0;
    if (decoder->length >= DR_MAX_ENCODED) {
        decoder->length = 0;
        decoder->discarding = 1;
        return -1;
    }
    decoder->encoded[decoder->length++] = byte;
    return 0;
}
