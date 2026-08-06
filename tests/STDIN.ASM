bits 16
org 100h

    mov ah, 3fh
    xor bx, bx
    mov cx, 64
    mov dx, buffer
    int 21h
    jc .failed
    mov [count], ax

    mov ah, 3ch
    xor cx, cx
    mov dx, output_name
    int 21h
    jc .failed
    mov bx, ax
    mov ah, 40h
    mov cx, [count]
    mov dx, buffer
    int 21h
    mov ah, 3eh
    int 21h
    mov ax, 4c00h
    int 21h

.failed:
    mov ax, 4c01h
    int 21h

count dw 0
output_name db 'STDIN.OUT', 0
buffer times 64 db 0
