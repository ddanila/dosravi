BITS 16
ORG 100h

jmp install

old_vector:
    dw 0, 0
ticks:
    db 0
queued:
    db 0

timer_handler:
    push ax
    push bx
    push dx
    push es
    cmp byte [cs:queued], 0
    jne chain
    inc byte [cs:ticks]
    cmp byte [cs:ticks], 18
    jb chain

    ; Queue Ctrl+C directly in the BIOS keyboard ring after DOSRAVI is
    ; already running. COMMAND.COM would consume a key queued before launch.
    mov ax, 0040h
    mov es, ax
    mov bx, [es:001ch]
    mov dx, bx
    add dx, 2
    cmp dx, 003eh
    jb no_wrap
    mov dx, 001eh
no_wrap:
    cmp dx, [es:001ah]
    je chain
    mov word [es:bx], 2e03h
    mov [es:001ch], dx
    mov byte [cs:queued], 1

chain:
    pop es
    pop dx
    pop bx
    pop ax
    jmp far [cs:old_vector]

install:
    mov ax, 351ch
    int 21h
    mov [old_vector], bx
    mov [old_vector+2], es
    push cs
    pop ds
    mov dx, timer_handler
    mov ax, 251ch
    int 21h
    mov dx, resident_end
    add dx, 15
    mov cl, 4
    shr dx, cl
    mov ax, 3100h
    int 21h

resident_end:
