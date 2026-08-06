#ifndef DOSRAVI_H
#define DOSRAVI_H

#define DR_VERSION 1
#define DR_HEADER_SIZE 14
#define DR_MAX_PAYLOAD 4096
#define DR_MAX_RAW (DR_HEADER_SIZE + DR_MAX_PAYLOAD + 2)
#define DR_MAX_ENCODED 4608

#define DR_FRAME_REQUEST 1
#define DR_FRAME_RESPONSE 2
#define DR_FRAME_EVENT 3

typedef unsigned char dr_u8;
typedef unsigned short dr_u16;
typedef unsigned long dr_u32;

typedef struct dr_frame {
    dr_u8 version;
    dr_u8 type;
    dr_u8 flags;
    dr_u32 transaction;
    dr_u32 sequence;
    dr_u16 payload_length;
    dr_u8 payload[DR_MAX_PAYLOAD];
} dr_frame;

typedef struct dr_decoder {
    dr_u8 encoded[DR_MAX_ENCODED];
    dr_u16 length;
    int discarding;
} dr_decoder;

dr_u16 dr_crc16(const dr_u8 *data, dr_u16 length);
dr_u32 dr_crc32_update(dr_u32 crc, const dr_u8 *data, dr_u16 length);
int dr_cobs_encode(const dr_u8 *input, dr_u16 input_length,
                   dr_u8 *output, dr_u16 output_size);
int dr_cobs_decode(const dr_u8 *input, dr_u16 input_length,
                   dr_u8 *output, dr_u16 output_size);
int dr_frame_encode(const dr_frame *frame, dr_u8 *output, dr_u16 output_size);
int dr_frame_decode(const dr_u8 *encoded, dr_u16 encoded_length,
                    dr_frame *frame);
void dr_decoder_init(dr_decoder *decoder);
int dr_decoder_byte(dr_decoder *decoder, dr_u8 byte, dr_frame *frame);

#endif
