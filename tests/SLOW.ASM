bits 16
org 100h

    xor ax, ax
    int 1ah
    mov bx, dx
    add bx, 12

.wait:
    xor ax, ax
    int 1ah
    cmp dx, bx
    jb .wait

    mov ax, 4c00h
    int 21h
