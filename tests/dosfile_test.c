#include <stdio.h>
#include <string.h>
#include "dosravi.h"

extern int dr_dos_open_file(char *name, unsigned mode, unsigned create);
extern void dr_dos_close_file(int handle);
extern dr_u32 dr_dos_seek_file(int handle, dr_u32 offset, unsigned origin);
extern int dr_dos_read_file(int handle, dr_u8 *data, unsigned length);
extern int dr_dos_write_file(int handle, const dr_u8 *data, unsigned length);
extern int dr_dos_read_at(int handle, dr_u32 offset, dr_u8 *data,
                          unsigned length);
extern int dr_dos_write_at(int handle, dr_u32 offset, const dr_u8 *data,
                           unsigned length);

static int fail(code, message)
int code;
char *message;
{
    printf("FAIL %d: %s\n", code, message);
    return code;
}

int main()
{
    static dr_u8 first[512];
    static dr_u8 second[512];
    static dr_u8 result[1024];
    dr_u32 position;
    dr_u32 offset;
    int count;
    int handle;
    int index;
    FILE *marker;
    for (index = 0; index < 512; ++index) {
        first[index] = (dr_u8)index;
        second[index] = (dr_u8)(index ^ 0xa5);
    }
    handle = dr_dos_open_file("FILE.BIN", 2, 1);
    if (handle < 0) return fail(1, "create");
    if (!dr_dos_write_file(handle, first, sizeof(first))) return fail(2, "write first");
    dr_dos_close_file(handle);
    handle = dr_dos_open_file("FILE.BIN", 2, 0);
    if (handle < 0) return fail(3, "reopen");
    if (!dr_dos_write_at(handle, 512UL, second, sizeof(second)))
        return fail(5, "write second");
    dr_dos_close_file(handle);
    for (index = 2; index < 128; ++index) {
        handle = dr_dos_open_file("FILE.BIN", 2, 0);
        if (handle < 0) return fail(12, "reopen large");
        offset = (dr_u32)index * 512UL;
        if (!dr_dos_write_at(handle, offset, first, sizeof(first)))
            return fail(13, "write large");
        dr_dos_close_file(handle);
    }
    handle = dr_dos_open_file("FILE.BIN", 0, 0);
    if (handle < 0) return fail(6, "open read");
    position = dr_dos_seek_file(handle, 0UL, SEEK_END);
    if (position != 65536UL) {
        printf("actual size %lu\n", (unsigned long)position);
        return fail(7, "size");
    }
    count = dr_dos_read_at(handle, 0UL, result, sizeof(result));
    if (count != sizeof(result))
        return fail(9, "read");
    if (memcmp(result, first, sizeof(first)) ||
        memcmp(result + sizeof(first), second, sizeof(second)))
        return fail(10, "content");
    count = dr_dos_read_at(handle, 65024UL, result, sizeof(first));
    if (count != sizeof(first) || memcmp(result, first, sizeof(first)))
        return fail(14, "large content");
    dr_dos_close_file(handle);
    marker = fopen("FILE.OK", "wb");
    if (!marker) return fail(11, "marker");
    fputs("ok\n", marker);
    fclose(marker);
    puts("DOS file shim passed");
    return 0;
}
