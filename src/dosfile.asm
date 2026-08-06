BITS 16

SECTION .text

GLOBAL _dr_dos_open_file
GLOBAL _dr_dos_close_file
GLOBAL _dr_dos_seek_file
GLOBAL _dr_dos_read_file
GLOBAL _dr_dos_write_file
GLOBAL _dr_dos_read_at
GLOBAL _dr_dos_write_at

; int dr_dos_open_file(char *name, unsigned mode, unsigned create)
; mode is DOS access mode 0 (read) or 2 (read/write).
_dr_dos_open_file:
    push bp
    mov bp, sp
    push bx
    push si
    push di
    push ds
    push es
    mov dx, [bp+4]
    mov ax, 3d00h
    or al, byte [bp+6]
    push bp
    int 21h
    pop bp
    jnc .open_done
    cmp word [bp+8], 0
    je .open_failed
    mov ah, 3ch
    xor cx, cx
    push bp
    int 21h
    pop bp
    jnc .open_done
.open_failed:
    mov ax, 0ffffh
.open_done:
    cld
    pop es
    pop ds
    pop di
    pop si
    pop bx
    pop bp
    ret

; void dr_dos_close_file(int handle)
_dr_dos_close_file:
    push bp
    mov bp, sp
    push bx
    push si
    push di
    push ds
    push es
    mov bx, [bp+4]
    mov ah, 3eh
    push bp
    int 21h
    pop bp
    cld
    pop es
    pop ds
    pop di
    pop si
    pop bx
    pop bp
    ret

; unsigned long dr_dos_seek_file(int handle, unsigned long offset,
;                                unsigned origin), or 0xffffffff on error.
_dr_dos_seek_file:
    push bp
    mov bp, sp
    push bx
    push si
    push di
    push ds
    push es
    mov bx, [bp+4]
    mov dx, [bp+6]
    mov cx, [bp+8]
    mov ax, 4200h
    or al, byte [bp+10]
    push bp
    int 21h
    pop bp
    pop es
    pop ds
    jc .seek_failed
    jmp .seek_done
.seek_failed:
    mov ax, 0ffffh
    mov dx, ax
.seek_done:
    cld
    pop di
    pop si
    pop bx
    pop bp
    ret

; int dr_dos_read_file(int handle, void *data, unsigned length), or -1.
_dr_dos_read_file:
    push bp
    mov bp, sp
    push bx
    push si
    push di
    push ds
    push es
    mov bx, [bp+4]
    mov dx, [bp+6]
    mov cx, [bp+8]
    mov ah, 3fh
    push bp
    int 21h
    pop bp
    pop es
    pop ds
    jnc .read_done
.read_failed:
    mov ax, 0ffffh
.read_done:
    cld
    pop di
    pop si
    pop bx
    pop bp
    ret

; int dr_dos_write_file(int handle, const void *data, unsigned length)
_dr_dos_write_file:
    push bp
    mov bp, sp
    push bx
    push si
    push di
    push ds
    push es
    mov bx, [bp+4]
    mov dx, [bp+6]
    mov cx, [bp+8]
    mov si, cx
    mov ah, 40h
    push bp
    int 21h
    pop bp
    pop es
    pop ds
    jc .write_failed
    cmp ax, si
    jne .write_failed
    mov ax, 1
    jmp .write_done
.write_failed:
    xor ax, ax
.write_done:
    cld
    pop di
    pop si
    pop bx
    pop bp
    ret

; int dr_dos_read_at(int handle, unsigned long offset, void *data,
;                    unsigned length), or -1.
_dr_dos_read_at:
    push bp
    mov bp, sp
    push bx
    push si
    push di
    push ds
    push es
    mov bx, [bp+4]
    mov si, [bp+6]
    mov di, [bp+8]
    mov dx, si
    mov cx, di
    mov ax, 4200h
    push bp
    int 21h
    pop bp
    pop es
    pop ds
    jc .read_at_failed
    cmp ax, si
    jne .read_at_failed
    cmp dx, di
    jne .read_at_failed
    mov dx, [bp+10]
    mov cx, [bp+12]
    mov ah, 3fh
    push ds
    push es
    push bp
    int 21h
    pop bp
    pop es
    pop ds
    jnc .read_at_done
.read_at_failed:
    mov ax, 0ffffh
.read_at_done:
    cld
    pop di
    pop si
    pop bx
    pop bp
    ret

; int dr_dos_write_at(int handle, unsigned long offset, const void *data,
;                     unsigned length)
_dr_dos_write_at:
    push bp
    mov bp, sp
    push bx
    push si
    push di
    push ds
    push es
    mov bx, [bp+4]
    mov si, [bp+6]
    mov di, [bp+8]
    mov dx, si
    mov cx, di
    mov ax, 4200h
    push bp
    int 21h
    pop bp
    pop es
    pop ds
    jc .write_at_failed
    cmp ax, si
    jne .write_at_failed
    cmp dx, di
    jne .write_at_failed
    mov dx, [bp+10]
    mov cx, [bp+12]
    mov si, cx
    mov ah, 40h
    push ds
    push es
    push bp
    int 21h
    pop bp
    pop es
    pop ds
    jc .write_at_failed
    cmp ax, si
    jne .write_at_failed
    mov ax, 1
    jmp .write_at_done
.write_at_failed:
    xor ax, ax
.write_at_done:
    cld
    pop di
    pop si
    pop bx
    pop bp
    ret
