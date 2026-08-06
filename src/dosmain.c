#include <bios.h>
#include <dos.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "dosravi.h"

#ifdef index
#undef index
#endif
#ifdef rindex
#undef rindex
#endif

#define AGENT_VERSION "0.1.0"
#define DEFAULT_BAUD 38400UL
#define DEFAULT_CHUNK 512U
#define MAX_CHUNK 1024U
#define MAX_PATH 12
#define CACHE_COUNT 6
#define CACHE_PAYLOAD 1200
#define EXEC_CACHE_COUNT 4

#define CMD_PING 1
#define CMD_INFO 2
#define CMD_LIST 3
#define CMD_PUT_BEGIN 4
#define CMD_PUT_DATA 5
#define CMD_PUT_COMMIT 6
#define CMD_GET 7
#define CMD_CRC 8
#define CMD_REMOVE 9
#define CMD_EXEC 10
#define CMD_EXEC_RESULT 11
#define CMD_QUIT 12
#define CMD_UPDATE 13
#define CMD_UPDATE_CONFIRM 14
#define CMD_UPDATE_ROLLBACK 15

#define STATUS_OK 0
#define STATUS_BAD_REQUEST 1
#define STATUS_NOT_FOUND 2
#define STATUS_DENIED 3
#define STATUS_IO_ERROR 4
#define STATUS_CRC_MISMATCH 5
#define STATUS_OFFSET_MISMATCH 6
#define STATUS_BUSY 7
#define STATUS_UNSUPPORTED 8
#define STATUS_INTERNAL 9

#define TAG_PATH 1
#define TAG_OFFSET 2
#define TAG_SIZE 3
#define TAG_CRC32 4
#define TAG_DATA 5
#define TAG_ARGS 6
#define TAG_EXEC_ID 7
#define TAG_EXIT_CODE 8
#define TAG_STDOUT 9
#define TAG_STDERR 10
#define TAG_JSON 11
#define TAG_MESSAGE 12
#define TAG_CHUNK_SIZE 13
#define TAG_ELAPSED_MS 14

extern unsigned dr_uart_bios_base(unsigned index);
extern void dr_uart_save(unsigned base, unsigned char *state);
extern void dr_uart_restore(unsigned base, unsigned char *state);
extern void dr_uart_init(unsigned base, unsigned divisor);
extern unsigned dr_uart_capability(unsigned base);
extern unsigned dr_uart_get(unsigned base);
extern void dr_uart_put(unsigned base, unsigned value);
extern void dr_uart_drain(unsigned base);

struct replay_entry {
    int valid;
    dr_u32 transaction;
    dr_u16 request_crc;
    dr_u16 length;
    dr_u8 payload[CACHE_PAYLOAD];
};

struct execution_entry {
    int valid;
    dr_u32 execution_id;
    dr_u16 request_crc;
    dr_u32 exit_code;
    dr_u32 elapsed_ms;
    char stdout_name[13];
    char stderr_name[13];
};

struct upload_meta {
    char magic[4];
    char path[13];
    dr_u32 size;
    dr_u32 crc32;
};

struct exec_parameters {
    unsigned environment;
    unsigned command_offset;
    unsigned command_segment;
    unsigned fcb1_offset;
    unsigned fcb1_segment;
    unsigned fcb2_offset;
    unsigned fcb2_segment;
};

static dr_decoder decoder;
static dr_frame request_frame;
static dr_frame response_frame;
static dr_u8 encoded_frame[DR_MAX_ENCODED + 1];
static struct replay_entry replay_cache[CACHE_COUNT];
static struct execution_entry execution_cache[EXEC_CACHE_COUNT];
static unsigned replay_next;
static unsigned execution_next;
static unsigned uart_base;
static unsigned uart_capability;
static unsigned char uart_state[6];
static int running;
static int requested_exit;

static dr_u16 get16(data)
const dr_u8 *data;
{
    return (dr_u16)((dr_u16)data[0] | ((dr_u16)data[1] << 8));
}

static dr_u32 get32(data)
const dr_u8 *data;
{
    return (dr_u32)data[0] | ((dr_u32)data[1] << 8) |
           ((dr_u32)data[2] << 16) | ((dr_u32)data[3] << 24);
}

static void put16(data, value)
dr_u8 *data;
dr_u16 value;
{
    data[0] = (dr_u8)(value & 0xffU);
    data[1] = (dr_u8)(value >> 8);
}

static void put32(data, value)
dr_u8 *data;
dr_u32 value;
{
    data[0] = (dr_u8)(value & 0xffUL);
    data[1] = (dr_u8)((value >> 8) & 0xffUL);
    data[2] = (dr_u8)((value >> 16) & 0xffUL);
    data[3] = (dr_u8)((value >> 24) & 0xffUL);
}

static int same_text(left, right)
char *left;
char *right;
{
    unsigned char a;
    unsigned char b;
    while (*left && *right) {
        a = (unsigned char)*left++;
        b = (unsigned char)*right++;
        if (a >= 'a' && a <= 'z') a -= 'a' - 'A';
        if (b >= 'a' && b <= 'z') b -= 'a' - 'A';
        if (a != b) return 0;
    }
    return *left == *right;
}

static void uart_send(frame)
dr_frame *frame;
{
    int length;
    int index;
    length = dr_frame_encode(frame, encoded_frame, sizeof(encoded_frame));
    if (length < 0) return;
    for (index = 0; index < length; ++index)
        dr_uart_put(uart_base, encoded_frame[index]);
}

static void response_begin(command, status)
int command;
int status;
{
    response_frame.version = DR_VERSION;
    response_frame.type = DR_FRAME_RESPONSE;
    response_frame.flags = 0;
    response_frame.transaction = request_frame.transaction;
    response_frame.sequence = request_frame.sequence;
    response_frame.payload_length = 2;
    response_frame.payload[0] = (dr_u8)command;
    response_frame.payload[1] = (dr_u8)status;
}

static int response_tlv(tag, data, length)
int tag;
const dr_u8 *data;
dr_u16 length;
{
    dr_u16 offset;
    offset = response_frame.payload_length;
    if ((dr_u32)offset + 3UL + length > DR_MAX_PAYLOAD) return 0;
    response_frame.payload[offset] = (dr_u8)tag;
    put16(response_frame.payload + offset + 1, length);
    memcpy(response_frame.payload + offset + 3, data, length);
    response_frame.payload_length = (dr_u16)(offset + 3 + length);
    return 1;
}

static int response_text(tag, text)
int tag;
char *text;
{
    return response_tlv(tag, (dr_u8 *)text, (dr_u16)strlen(text));
}

static int response_u32(tag, value)
int tag;
dr_u32 value;
{
    dr_u8 bytes[4];
    put32(bytes, value);
    return response_tlv(tag, bytes, 4);
}

static void error_response(command, status, message)
int command;
int status;
char *message;
{
    response_begin(command, status);
    if (message) response_text(TAG_MESSAGE, message);
}

static int find_tlv(tag, data, length, value, value_length)
int tag;
const dr_u8 *data;
dr_u16 length;
const dr_u8 **value;
dr_u16 *value_length;
{
    dr_u16 offset;
    dr_u16 item_length;
    int item_tag;
    offset = 0;
    while (offset < length) {
        if ((dr_u16)(length - offset) < 3) return -1;
        item_tag = data[offset];
        item_length = get16(data + offset + 1);
        offset = (dr_u16)(offset + 3);
        if (item_length > (dr_u16)(length - offset)) return -1;
        if (item_tag == tag) {
            *value = data + offset;
            *value_length = item_length;
            return 1;
        }
        offset = (dr_u16)(offset + item_length);
    }
    return 0;
}

static int required_u32(tag, data, length, value)
int tag;
const dr_u8 *data;
dr_u16 length;
dr_u32 *value;
{
    const dr_u8 *found;
    dr_u16 found_length;
    int result;
    result = find_tlv(tag, data, length, &found, &found_length);
    if (result != 1 || found_length != 4) return 0;
    *value = get32(found);
    return 1;
}

static int reserved_stem(path)
char *path;
{
    char stem[9];
    int length;
    char *dot;
    dot = strchr(path, '.');
    length = dot ? (int)(dot - path) : (int)strlen(path);
    memcpy(stem, path, length);
    stem[length] = 0;
    if (same_text(stem, "CON") || same_text(stem, "PRN") ||
        same_text(stem, "AUX") || same_text(stem, "NUL") ||
        same_text(stem, "CLOCK$")) return 1;
    if (length == 4 && !strncmp(stem, "COM", 3) && stem[3] >= '1' && stem[3] <= '9') return 1;
    if (length == 4 && !strncmp(stem, "LPT", 3) && stem[3] >= '1' && stem[3] <= '9') return 1;
    return 0;
}

static int valid_path_bytes(value, length, output)
const dr_u8 *value;
dr_u16 length;
char *output;
{
    int stem_length;
    int extension_length;
    int seen_dot;
    int index;
    unsigned char character;
    if (length == 0 || length > MAX_PATH) return 0;
    stem_length = 0;
    extension_length = 0;
    seen_dot = 0;
    for (index = 0; index < length; ++index) {
        character = value[index];
        if (character >= 'a' && character <= 'z') character -= 'a' - 'A';
        if (character == '.') {
            if (seen_dot || stem_length == 0 || index == length - 1) return 0;
            seen_dot = 1;
        } else {
            if (!((character >= 'A' && character <= 'Z') ||
                  (character >= '0' && character <= '9') ||
                  strchr((char *)"_$~!#%&-{}()@'", (int)character) != 0)) return 0;
            if (seen_dot) ++extension_length; else ++stem_length;
        }
        output[index] = (char)character;
    }
    output[length] = 0;
    if (stem_length > 8 || extension_length > 3 || reserved_stem(output)) return 0;
    return 1;
}

static int required_path(data, length, output)
const dr_u8 *data;
dr_u16 length;
char *output;
{
    const dr_u8 *value;
    dr_u16 value_length;
    if (find_tlv(TAG_PATH, data, length, &value, &value_length) != 1) return 0;
    return valid_path_bytes(value, value_length, output);
}

static void transfer_names(path, part, meta)
char *path;
char *part;
char *meta;
{
    unsigned high;
    unsigned low;
    unsigned character;
    high = 0x45d9U;
    low = 0x9e37U;
    while (*path) {
        character = (unsigned char)*path++;
        high = (unsigned)(high * 33U + character);
        low = (unsigned)(low * 131U + character);
    }
    sprintf(part, "%04X%04X.RVP", high, low);
    sprintf(meta, "%04X%04X.RVM", high, low);
}

static int file_identity(path, size, crc)
char *path;
dr_u32 *size;
dr_u32 *crc;
{
    FILE *file;
    dr_u8 block[512];
    int count;
    long position;
    dr_u32 running_crc;
    file = fopen(path, "rb");
    if (!file) return 0;
    running_crc = 0;
    while ((count = fread(block, 1, sizeof(block), file)) > 0)
        running_crc = dr_crc32_update(running_crc, block, (dr_u16)count);
    position = ftell(file);
    if (ferror(file) || position < 0) {
        fclose(file);
        return 0;
    }
    fclose(file);
    *size = (dr_u32)position;
    *crc = running_crc;
    return 1;
}

static int dos_rename(old_name, new_name)
char *old_name;
char *new_name;
{
    union REGS input;
    union REGS output;
    struct SREGS segments;
    segread(&segments);
    input.x.ax = 0x5600U;
    input.x.dx = (unsigned)old_name;
    input.x.di = (unsigned)new_name;
    segments.es = segments.ds;
    int86x(0x21, &input, &output, &segments);
    return output.x.cflag ? -1 : 0;
}

static int dos_remove(name)
char *name;
{
    union REGS input;
    union REGS output;
    struct SREGS segments;
    segread(&segments);
    input.h.ah = 0x41U;
    input.x.dx = (unsigned)name;
    int86x(0x21, &input, &output, &segments);
    return output.x.cflag ? -1 : 0;
}

static int dos_chdir(path)
char *path;
{
    union REGS input;
    union REGS output;
    struct SREGS segments;
    if (path[0] && path[1] == ':') {
        input.h.ah = 0x0eU;
        input.h.dl = (unsigned char)((path[0] >= 'a' ? path[0] - 'a' : path[0] - 'A'));
        int86(0x21, &input, &output);
    }
    segread(&segments);
    input.h.ah = 0x3bU;
    input.x.dx = (unsigned)path;
    int86x(0x21, &input, &output, &segments);
    return output.x.cflag ? -1 : 0;
}

static dr_u32 bios_milliseconds()
{
    union REGS input;
    union REGS output;
    dr_u32 ticks;
    input.h.ah = 0;
    int86(0x1a, &input, &output);
    ticks = ((dr_u32)output.x.cx << 16) | output.x.dx;
    return ticks * 55UL;
}

static int dos_duplicate(handle)
int handle;
{
    union REGS input;
    union REGS output;
    input.h.ah = 0x45U;
    input.x.bx = (unsigned)handle;
    int86(0x21, &input, &output);
    return output.x.cflag ? -1 : (int)output.x.ax;
}

static int dos_force_duplicate(source, destination)
int source;
int destination;
{
    union REGS input;
    union REGS output;
    input.h.ah = 0x46U;
    input.x.bx = (unsigned)source;
    input.x.cx = (unsigned)destination;
    int86(0x21, &input, &output);
    return output.x.cflag ? -1 : 0;
}

static void dos_close(handle)
int handle;
{
    union REGS input;
    union REGS output;
    input.h.ah = 0x3eU;
    input.x.bx = (unsigned)handle;
    int86(0x21, &input, &output);
}

static int dos_exec(program, arguments, exit_code)
char *program;
char *arguments;
dr_u32 *exit_code;
{
    struct exec_parameters parameters;
    struct SREGS segments;
    union REGS input;
    union REGS output;
    static char command_tail[128];
    int length;
    length = strlen(arguments);
    if (length > 126) return -2;
    command_tail[0] = (char)length;
    memcpy(command_tail + 1, arguments, length);
    command_tail[length + 1] = '\r';
    segread(&segments);
    parameters.environment = 0;
    parameters.command_offset = (unsigned)command_tail;
    parameters.command_segment = segments.ds;
    parameters.fcb1_offset = 0x5cU;
    parameters.fcb1_segment = __psp;
    parameters.fcb2_offset = 0x6cU;
    parameters.fcb2_segment = __psp;
    input.x.ax = 0x4b00U;
    input.x.dx = (unsigned)program;
    input.x.bx = (unsigned)&parameters;
    segments.es = segments.ds;
    int86x(0x21, &input, &output, &segments);
    if (output.x.cflag) return -(int)output.x.ax;
    input.h.ah = 0x4dU;
    int86(0x21, &input, &output);
    *exit_code = output.h.al;
    return 0;
}

static int execute_captured(program, arguments, stdout_name, stderr_name, exit_code, elapsed)
char *program;
char *arguments;
char *stdout_name;
char *stderr_name;
dr_u32 *exit_code;
dr_u32 *elapsed;
{
    FILE *out_file;
    FILE *err_file;
    int saved_out;
    int saved_err;
    int result;
    dr_u32 started;
    fflush(stdout);
    fflush(stderr);
    saved_out = dos_duplicate(1);
    saved_err = dos_duplicate(2);
    if (saved_out < 0 || saved_err < 0) {
        if (saved_out >= 0) dos_close(saved_out);
        if (saved_err >= 0) dos_close(saved_err);
        return -1;
    }
    out_file = fopen(stdout_name, "wb");
    err_file = fopen(stderr_name, "wb");
    if (!out_file || !err_file) {
        if (out_file) fclose(out_file);
        if (err_file) fclose(err_file);
        dos_close(saved_out);
        dos_close(saved_err);
        return -1;
    }
    if (dos_force_duplicate(fileno(out_file), 1) ||
        dos_force_duplicate(fileno(err_file), 2)) {
        fclose(out_file);
        fclose(err_file);
        dos_force_duplicate(saved_out, 1);
        dos_force_duplicate(saved_err, 2);
        dos_close(saved_out);
        dos_close(saved_err);
        return -1;
    }
    fclose(out_file);
    fclose(err_file);
    started = bios_milliseconds();
    result = dos_exec(program, arguments, exit_code);
    *elapsed = bios_milliseconds() - started;
    dos_force_duplicate(saved_out, 1);
    dos_force_duplicate(saved_err, 2);
    dos_close(saved_out);
    dos_close(saved_err);
    clearerr(stdout);
    clearerr(stderr);
    return result;
}

static void send_exec_started(execution_id)
dr_u32 execution_id;
{
    dr_frame saved;
    saved = response_frame;
    response_begin(CMD_EXEC, STATUS_OK);
    response_frame.type = DR_FRAME_EVENT;
    response_u32(TAG_EXEC_ID, execution_id);
    response_text(TAG_MESSAGE, "STARTED");
    uart_send(&response_frame);
    response_frame = saved;
}

static struct execution_entry *find_execution(execution_id)
dr_u32 execution_id;
{
    int index;
    for (index = 0; index < EXEC_CACHE_COUNT; ++index)
        if (execution_cache[index].valid &&
            execution_cache[index].execution_id == execution_id)
            return &execution_cache[index];
    return 0;
}

static void execution_response(entry)
struct execution_entry *entry;
{
    response_begin(CMD_EXEC, STATUS_OK);
    response_u32(TAG_EXEC_ID, entry->execution_id);
    response_u32(TAG_EXIT_CODE, entry->exit_code);
    response_text(TAG_STDOUT, entry->stdout_name);
    response_text(TAG_STDERR, entry->stderr_name);
    response_u32(TAG_ELAPSED_MS, entry->elapsed_ms);
}

static void handle_ping()
{
    response_begin(CMD_PING, STATUS_OK);
    response_text(TAG_MESSAGE, "PONG");
}

static void handle_info()
{
    union REGS input;
    union REGS output;
    dr_u32 free_bytes;
    dr_u32 free_memory;
    char info[384];
    unsigned dos_major;
    unsigned dos_minor;
    input.h.ah = 0x30U;
    int86(0x21, &input, &output);
    dos_major = output.h.al;
    dos_minor = output.h.ah;
    input.h.ah = 0x36U;
    input.h.dl = 0;
    int86(0x21, &input, &output);
    if (output.x.ax == 0xffffU) free_bytes = 0;
    else free_bytes = (dr_u32)output.x.ax * output.x.bx * output.x.cx;
    input.h.ah = 0x48U;
    input.x.bx = 0xffffU;
    int86(0x21, &input, &output);
    free_memory = (dr_u32)output.x.bx * 16UL;
    sprintf(info,
            "{\"agent\":\"DOSRAVI.COM\",\"version\":\"%s\","
            "\"protocol\":1,\"dos\":\"%u.%u\",\"com_base\":%u,"
            "\"uart_fifo_bits\":%u,\"free_memory\":%lu,"
            "\"free_disk\":%lu,\"chunk_size\":%u,"
            "\"capabilities\":[\"replay\",\"resume\",\"exec-capture\"]}",
            AGENT_VERSION, dos_major, dos_minor, uart_base, uart_capability,
            free_memory, free_bytes, DEFAULT_CHUNK);
    response_begin(CMD_INFO, STATUS_OK);
    response_text(TAG_JSON, info);
}

static void set_dta(address, segment)
unsigned address;
unsigned segment;
{
    union REGS input;
    union REGS output;
    struct SREGS segments;
    segread(&segments);
    segments.ds = segment;
    input.h.ah = 0x1aU;
    input.x.dx = address;
    int86x(0x21, &input, &output, &segments);
}

static int find_file(pattern, attributes, next)
char *pattern;
unsigned attributes;
int next;
{
    union REGS input;
    union REGS output;
    struct SREGS segments;
    segread(&segments);
    input.h.ah = next ? 0x4fU : 0x4eU;
    input.x.cx = attributes;
    input.x.dx = (unsigned)pattern;
    int86x(0x21, &input, &output, &segments);
    return output.x.cflag ? -1 : 0;
}

static void handle_list()
{
    static dr_u8 dta[64];
    static char listing[1050];
    char item[48];
    char *name;
    dr_u32 size;
    int first_item;
    int truncated;
    set_dta((unsigned)dta, __get_ds());
    strcpy(listing, "[");
    first_item = 1;
    truncated = 0;
    if (find_file("*.*", 0x27U, 0) == 0) {
        do {
            name = (char *)(dta + 30);
            size = get32(dta + 26);
            if (!(dta[21] & 0x10U) &&
                !strstr(name, ".RVP") && !strstr(name, ".RVM")) {
                sprintf(item, "%s{\"name\":\"%s\",\"size\":%lu}",
                        first_item ? "" : ",", name, size);
                if (strlen(listing) + strlen(item) + 2 >= sizeof(listing)) {
                    truncated = 1;
                    break;
                }
                strcat(listing, item);
                first_item = 0;
            }
        } while (find_file("*.*", 0x27U, 1) == 0);
    }
    strcat(listing, "]");
    set_dta(0x80U, __psp);
    if (truncated) {
        error_response(CMD_LIST, STATUS_IO_ERROR, "workspace listing exceeds v0.1 DOS limit");
        return;
    }
    response_begin(CMD_LIST, STATUS_OK);
    response_text(TAG_JSON, listing);
}

static void handle_put_begin(fields, length)
const dr_u8 *fields;
dr_u16 length;
{
    char path[13];
    char part[13];
    char meta_name[13];
    struct upload_meta expected;
    struct upload_meta existing;
    FILE *file;
    long offset;
    if (!required_path(fields, length, path) ||
        !required_u32(TAG_SIZE, fields, length, &expected.size) ||
        !required_u32(TAG_CRC32, fields, length, &expected.crc32)) {
        error_response(CMD_PUT_BEGIN, STATUS_BAD_REQUEST, "invalid PUT_BEGIN fields");
        return;
    }
    memcpy(expected.magic, "RVM1", 4);
    strcpy(expected.path, path);
    transfer_names(path, part, meta_name);
    file = fopen(meta_name, "rb");
    if (!file || fread(&existing, 1, sizeof(existing), file) != sizeof(existing) ||
        memcmp(&existing, &expected, sizeof(existing))) {
        if (file) fclose(file);
        dos_remove(part);
        dos_remove(meta_name);
        file = fopen(meta_name, "wb");
        if (!file || fwrite(&expected, 1, sizeof(expected), file) != sizeof(expected)) {
            if (file) fclose(file);
            error_response(CMD_PUT_BEGIN, STATUS_IO_ERROR, "cannot create upload metadata");
            return;
        }
    }
    fclose(file);
    file = fopen(part, "rb");
    if (file) {
        fseek(file, 0L, SEEK_END);
        offset = ftell(file);
        fclose(file);
    } else offset = 0;
    if (offset < 0 || (dr_u32)offset > expected.size) {
        dos_remove(part);
        offset = 0;
    }
    response_begin(CMD_PUT_BEGIN, STATUS_OK);
    response_u32(TAG_OFFSET, (dr_u32)offset);
}

static void handle_put_data(fields, length)
const dr_u8 *fields;
dr_u16 length;
{
    char path[13];
    char part[13];
    char meta_name[13];
    const dr_u8 *data;
    dr_u16 data_length;
    dr_u32 offset;
    FILE *file;
    long actual;
    if (!required_path(fields, length, path) ||
        !required_u32(TAG_OFFSET, fields, length, &offset) ||
        find_tlv(TAG_DATA, fields, length, &data, &data_length) != 1 ||
        data_length > MAX_CHUNK) {
        error_response(CMD_PUT_DATA, STATUS_BAD_REQUEST, "invalid PUT_DATA fields");
        return;
    }
    transfer_names(path, part, meta_name);
    file = fopen(part, "r+b");
    if (!file) file = fopen(part, "w+b");
    if (!file) {
        error_response(CMD_PUT_DATA, STATUS_IO_ERROR, "cannot open upload temporary");
        return;
    }
    fseek(file, 0L, SEEK_END);
    actual = ftell(file);
    if (actual < 0 || (dr_u32)actual != offset) {
        fclose(file);
        response_begin(CMD_PUT_DATA, STATUS_OFFSET_MISMATCH);
        response_u32(TAG_OFFSET, actual < 0 ? 0 : (dr_u32)actual);
        return;
    }
    if (fwrite(data, 1, data_length, file) != data_length || fflush(file)) {
        fclose(file);
        error_response(CMD_PUT_DATA, STATUS_IO_ERROR, "upload write failed");
        return;
    }
    fclose(file);
    response_begin(CMD_PUT_DATA, STATUS_OK);
    response_u32(TAG_OFFSET, offset + data_length);
}

static void handle_put_commit(fields, length)
const dr_u8 *fields;
dr_u16 length;
{
    char path[13];
    char part[13];
    char meta_name[13];
    dr_u32 expected_size;
    dr_u32 expected_crc;
    dr_u32 actual_size;
    dr_u32 actual_crc;
    if (!required_path(fields, length, path) ||
        !required_u32(TAG_SIZE, fields, length, &expected_size) ||
        !required_u32(TAG_CRC32, fields, length, &expected_crc)) {
        error_response(CMD_PUT_COMMIT, STATUS_BAD_REQUEST, "invalid PUT_COMMIT fields");
        return;
    }
    transfer_names(path, part, meta_name);
    if (!file_identity(part, &actual_size, &actual_crc)) {
        error_response(CMD_PUT_COMMIT, STATUS_NOT_FOUND, "upload temporary missing");
        return;
    }
    if (actual_size != expected_size || actual_crc != expected_crc) {
        response_begin(CMD_PUT_COMMIT, STATUS_CRC_MISMATCH);
        response_u32(TAG_SIZE, actual_size);
        response_u32(TAG_CRC32, actual_crc);
        return;
    }
    dos_remove(path);
    if (dos_rename(part, path)) {
        error_response(CMD_PUT_COMMIT, STATUS_IO_ERROR, "verified upload rename failed");
        return;
    }
    dos_remove(meta_name);
    response_begin(CMD_PUT_COMMIT, STATUS_OK);
    response_u32(TAG_SIZE, actual_size);
    response_u32(TAG_CRC32, actual_crc);
}

static void handle_crc(fields, length)
const dr_u8 *fields;
dr_u16 length;
{
    char path[13];
    dr_u32 size;
    dr_u32 crc;
    if (!required_path(fields, length, path)) {
        error_response(CMD_CRC, STATUS_DENIED, "invalid workspace path");
        return;
    }
    if (!file_identity(path, &size, &crc)) {
        error_response(CMD_CRC, STATUS_NOT_FOUND, "file not found");
        return;
    }
    response_begin(CMD_CRC, STATUS_OK);
    response_u32(TAG_SIZE, size);
    response_u32(TAG_CRC32, crc);
}

static void handle_get(fields, length)
const dr_u8 *fields;
dr_u16 length;
{
    char path[13];
    dr_u32 size;
    dr_u32 crc;
    dr_u32 offset;
    dr_u32 chunk_size;
    FILE *file;
    int count;
    static dr_u8 chunk[MAX_CHUNK];
    if (!required_path(fields, length, path) ||
        !required_u32(TAG_OFFSET, fields, length, &offset) ||
        !required_u32(TAG_CHUNK_SIZE, fields, length, &chunk_size) ||
        chunk_size == 0) {
        error_response(CMD_GET, STATUS_BAD_REQUEST, "invalid GET fields");
        return;
    }
    if (!file_identity(path, &size, &crc)) {
        error_response(CMD_GET, STATUS_NOT_FOUND, "file not found");
        return;
    }
    if (offset > size) {
        response_begin(CMD_GET, STATUS_OFFSET_MISMATCH);
        response_u32(TAG_OFFSET, size);
        return;
    }
    if (chunk_size > MAX_CHUNK) chunk_size = MAX_CHUNK;
    file = fopen(path, "rb");
    if (!file || fseek(file, (long)offset, SEEK_SET)) {
        if (file) fclose(file);
        error_response(CMD_GET, STATUS_IO_ERROR, "file seek failed");
        return;
    }
    count = fread(chunk, 1, (unsigned)chunk_size, file);
    if (ferror(file)) {
        fclose(file);
        error_response(CMD_GET, STATUS_IO_ERROR, "file read failed");
        return;
    }
    fclose(file);
    response_begin(CMD_GET, STATUS_OK);
    response_u32(TAG_SIZE, size);
    response_u32(TAG_CRC32, crc);
    response_u32(TAG_OFFSET, offset);
    response_tlv(TAG_DATA, chunk, (dr_u16)count);
}

static void handle_remove(fields, length)
const dr_u8 *fields;
dr_u16 length;
{
    char path[13];
    FILE *file;
    if (!required_path(fields, length, path)) {
        error_response(CMD_REMOVE, STATUS_DENIED, "invalid workspace path");
        return;
    }
    file = fopen(path, "rb");
    if (!file) {
        error_response(CMD_REMOVE, STATUS_NOT_FOUND, "file not found");
        return;
    }
    fclose(file);
    if (dos_remove(path)) {
        error_response(CMD_REMOVE, STATUS_IO_ERROR, "remove failed");
        return;
    }
    response_begin(CMD_REMOVE, STATUS_OK);
}

static int write_update_marker(size, crc)
dr_u32 size;
dr_u32 crc;
{
    FILE *file;
    dr_u8 marker[12];
    memcpy(marker, "RUP1", 4);
    put32(marker + 4, size);
    put32(marker + 8, crc);
    file = fopen("UPDATE.PND", "wb");
    if (!file) return 0;
    if (fwrite(marker, 1, sizeof(marker), file) != sizeof(marker) || fflush(file)) {
        fclose(file);
        dos_remove("UPDATE.PND");
        return 0;
    }
    fclose(file);
    return 1;
}

static void handle_update(fields, length)
const dr_u8 *fields;
dr_u16 length;
{
    char path[13];
    dr_u32 expected_size;
    dr_u32 expected_crc;
    dr_u32 actual_size;
    dr_u32 actual_crc;
    if (!required_path(fields, length, path) ||
        !same_text(path, "DOSRAVI.NEW") ||
        !required_u32(TAG_SIZE, fields, length, &expected_size) ||
        !required_u32(TAG_CRC32, fields, length, &expected_crc)) {
        error_response(CMD_UPDATE, STATUS_BAD_REQUEST,
                       "UPDATE requires verified DOSRAVI.NEW");
        return;
    }
    if (!file_identity(path, &actual_size, &actual_crc)) {
        error_response(CMD_UPDATE, STATUS_NOT_FOUND, "DOSRAVI.NEW not found");
        return;
    }
    if (actual_size == 0 || actual_size > 65280UL ||
        actual_size != expected_size || actual_crc != expected_crc) {
        response_begin(CMD_UPDATE, STATUS_CRC_MISMATCH);
        response_u32(TAG_SIZE, actual_size);
        response_u32(TAG_CRC32, actual_crc);
        return;
    }
    if (!write_update_marker(actual_size, actual_crc)) {
        error_response(CMD_UPDATE, STATUS_IO_ERROR, "cannot write update marker");
        return;
    }
    dos_remove("DOSRAVI.OLD");
    if (dos_rename("DOSRAVI.COM", "DOSRAVI.OLD")) {
        dos_remove("UPDATE.PND");
        error_response(CMD_UPDATE, STATUS_IO_ERROR, "cannot preserve current agent");
        return;
    }
    if (dos_rename("DOSRAVI.NEW", "DOSRAVI.COM")) {
        dos_rename("DOSRAVI.OLD", "DOSRAVI.COM");
        dos_remove("UPDATE.PND");
        error_response(CMD_UPDATE, STATUS_IO_ERROR, "cannot promote replacement agent");
        return;
    }
    response_begin(CMD_UPDATE, STATUS_OK);
    response_u32(TAG_SIZE, actual_size);
    response_u32(TAG_CRC32, actual_crc);
    requested_exit = 85;
    running = 0;
}

static void handle_update_confirm()
{
    FILE *file;
    file = fopen("UPDATE.PND", "rb");
    if (!file) {
        error_response(CMD_UPDATE_CONFIRM, STATUS_NOT_FOUND,
                       "no update awaits confirmation");
        return;
    }
    fclose(file);
    if (dos_remove("UPDATE.PND")) {
        error_response(CMD_UPDATE_CONFIRM, STATUS_IO_ERROR,
                       "cannot clear update marker");
        return;
    }
    response_begin(CMD_UPDATE_CONFIRM, STATUS_OK);
}

static void handle_update_rollback()
{
    dr_u32 size;
    dr_u32 crc;
    if (!file_identity("DOSRAVI.OLD", &size, &crc)) {
        error_response(CMD_UPDATE_ROLLBACK, STATUS_NOT_FOUND,
                       "fallback agent not found");
        return;
    }
    dos_remove("DOSRAVI.BAD");
    if (dos_rename("DOSRAVI.COM", "DOSRAVI.BAD") ||
        dos_rename("DOSRAVI.OLD", "DOSRAVI.COM")) {
        dos_rename("DOSRAVI.BAD", "DOSRAVI.COM");
        error_response(CMD_UPDATE_ROLLBACK, STATUS_IO_ERROR,
                       "rollback rename failed");
        return;
    }
    dos_remove("UPDATE.PND");
    response_begin(CMD_UPDATE_ROLLBACK, STATUS_OK);
    requested_exit = 85;
    running = 0;
}

static int executable_path(path)
char *path;
{
    char *extension;
    extension = strrchr(path, '.');
    return extension && (same_text(extension, ".COM") || same_text(extension, ".EXE"));
}

static void handle_exec(fields, length, request_crc)
const dr_u8 *fields;
dr_u16 length;
dr_u16 request_crc;
{
    char path[13];
    char arguments[127];
    const dr_u8 *argument_data;
    static const dr_u8 empty_arguments[] = "";
    dr_u16 argument_length;
    dr_u32 execution_id;
    struct execution_entry *entry;
    int result;
    if (!required_path(fields, length, path) || !executable_path(path) ||
        !required_u32(TAG_EXEC_ID, fields, length, &execution_id) ||
        find_tlv(TAG_ARGS, fields, length, &argument_data, &argument_length) < 0 ||
        argument_length > 126) {
        error_response(CMD_EXEC, STATUS_BAD_REQUEST, "invalid EXEC fields");
        return;
    }
    if (find_tlv(TAG_ARGS, fields, length, &argument_data, &argument_length) == 0) {
        argument_length = 0;
        argument_data = empty_arguments;
    }
    memcpy(arguments, argument_data, argument_length);
    arguments[argument_length] = 0;
    entry = find_execution(execution_id);
    if (entry) {
        if (entry->request_crc != request_crc) {
            error_response(CMD_EXEC, STATUS_BAD_REQUEST, "execution ID reused for different command");
            return;
        }
        execution_response(entry);
        return;
    }
    entry = &execution_cache[execution_next++ % EXEC_CACHE_COUNT];
    memset(entry, 0, sizeof(*entry));
    entry->execution_id = execution_id;
    entry->request_crc = request_crc;
    sprintf(entry->stdout_name, "O%02X%04X.OUT",
            (unsigned)((execution_id >> 16) & 0xffUL),
            (unsigned)(execution_id & 0xffffUL));
    sprintf(entry->stderr_name, "E%02X%04X.ERR",
            (unsigned)((execution_id >> 16) & 0xffUL),
            (unsigned)(execution_id & 0xffffUL));
    send_exec_started(execution_id);
    result = execute_captured(path, arguments, entry->stdout_name,
                              entry->stderr_name, &entry->exit_code,
                              &entry->elapsed_ms);
    if (result) {
        error_response(CMD_EXEC, STATUS_IO_ERROR, "DOS EXEC or capture failed");
        return;
    }
    entry->valid = 1;
    execution_response(entry);
}

static void dispatch_request(request_crc)
dr_u16 request_crc;
{
    int command;
    const dr_u8 *fields;
    dr_u16 length;
    if (request_frame.payload_length == 0) {
        error_response(CMD_PING, STATUS_BAD_REQUEST, "empty request");
        return;
    }
    command = request_frame.payload[0];
    fields = request_frame.payload + 1;
    length = (dr_u16)(request_frame.payload_length - 1);
    switch (command) {
    case CMD_PING: handle_ping(); break;
    case CMD_INFO: handle_info(); break;
    case CMD_LIST: handle_list(); break;
    case CMD_PUT_BEGIN: handle_put_begin(fields, length); break;
    case CMD_PUT_DATA: handle_put_data(fields, length); break;
    case CMD_PUT_COMMIT: handle_put_commit(fields, length); break;
    case CMD_GET: handle_get(fields, length); break;
    case CMD_CRC: handle_crc(fields, length); break;
    case CMD_REMOVE: handle_remove(fields, length); break;
    case CMD_EXEC: handle_exec(fields, length, request_crc); break;
    case CMD_UPDATE: handle_update(fields, length); break;
    case CMD_UPDATE_CONFIRM: handle_update_confirm(); break;
    case CMD_UPDATE_ROLLBACK: handle_update_rollback(); break;
    case CMD_QUIT:
        response_begin(CMD_QUIT, STATUS_OK);
        running = 0;
        break;
    default:
        error_response(command, STATUS_UNSUPPORTED, "unsupported command");
    }
}

static struct replay_entry *find_replay(transaction)
dr_u32 transaction;
{
    int index;
    for (index = 0; index < CACHE_COUNT; ++index)
        if (replay_cache[index].valid && replay_cache[index].transaction == transaction)
            return &replay_cache[index];
    return 0;
}

static void process_frame()
{
    struct replay_entry *entry;
    dr_u16 request_crc;
    if (request_frame.type != DR_FRAME_REQUEST) return;
    request_crc = dr_crc16(request_frame.payload, request_frame.payload_length);
    entry = find_replay(request_frame.transaction);
    if (entry) {
        if (entry->request_crc != request_crc) {
            error_response(request_frame.payload_length ? request_frame.payload[0] : CMD_PING,
                           STATUS_BAD_REQUEST,
                           "transaction ID reused for different request");
            uart_send(&response_frame);
            return;
        }
        response_frame.version = DR_VERSION;
        response_frame.type = DR_FRAME_RESPONSE;
        response_frame.flags = 2;
        response_frame.transaction = request_frame.transaction;
        response_frame.sequence = request_frame.sequence;
        response_frame.payload_length = entry->length;
        memcpy(response_frame.payload, entry->payload, entry->length);
        uart_send(&response_frame);
        return;
    }
    dispatch_request(request_crc);
    uart_send(&response_frame);
    if (response_frame.payload_length <= CACHE_PAYLOAD) {
        entry = &replay_cache[replay_next++ % CACHE_COUNT];
        entry->valid = 1;
        entry->transaction = request_frame.transaction;
        entry->request_crc = request_crc;
        entry->length = response_frame.payload_length;
        memcpy(entry->payload, response_frame.payload, entry->length);
    }
}

static unsigned parse_baud(text)
char *text;
{
    unsigned long baud;
    baud = strtoul(text, 0, 10);
    if (baud == 9600UL || baud == 19200UL || baud == 38400UL ||
        baud == 57600UL || baud == 115200UL)
        return (unsigned)(115200UL / baud);
    return 0;
}

static int configure(argc, argv, root, divisor)
int argc;
char **argv;
char **root;
unsigned *divisor;
{
    int index;
    unsigned com_index;
    unsigned base_override;
    char *end;
    com_index = 0;
    base_override = 0;
    *root = "C:\\RAVI";
    *divisor = (unsigned)(115200UL / DEFAULT_BAUD);
    for (index = 1; index < argc; ++index) {
        if (!strncmp(argv[index], "/COM", 4) && argv[index][4] >= '1' &&
            argv[index][4] <= '4' && argv[index][5] == 0) {
            com_index = argv[index][4] - '1';
        } else if (!strncmp(argv[index], "/BAUD:", 6)) {
            *divisor = parse_baud(argv[index] + 6);
            if (!*divisor) return 0;
        } else if (!strncmp(argv[index], "/ROOT:", 6)) {
            *root = argv[index] + 6;
        } else if (!strncmp(argv[index], "/BASE:", 6)) {
            base_override = (unsigned)strtoul(argv[index] + 6, &end, 16);
            if (*end || !base_override) return 0;
        } else return 0;
    }
    uart_base = base_override ? base_override : dr_uart_bios_base(com_index);
    return uart_base != 0;
}

int main(argc, argv)
int argc;
char **argv;
{
    char *root;
    unsigned divisor;
    int decoded;
    if (!configure(argc, argv, &root, &divisor)) {
        puts("Usage: DOSRAVI /COM1 [/BAUD:38400] [/ROOT:C:\\RAVI] [/BASE:3F8]");
        return 2;
    }
    if (dos_chdir(root)) {
        printf("DOSRAVI: cannot enter workspace %s\n", root);
        return 3;
    }
    memset(replay_cache, 0, sizeof(replay_cache));
    memset(execution_cache, 0, sizeof(execution_cache));
    dr_decoder_init(&decoder);
    dr_uart_save(uart_base, uart_state);
    uart_capability = dr_uart_capability(uart_base);
    dr_uart_init(uart_base, divisor);
    requested_exit = 0;
    running = 1;
    while (running) {
        decoded = dr_decoder_byte(&decoder, (dr_u8)dr_uart_get(uart_base),
                                  &request_frame);
        if (decoded == 1) process_frame();
    }
    dr_uart_drain(uart_base);
    dr_uart_restore(uart_base, uart_state);
    return requested_exit;
}
