BITS 16
ORG 100h

    mov dx, marker
    xor cx, cx
    mov ah, 3ch
    int 21h
    jc short done
    mov bx, ax
    mov dx, text
    mov cx, text_end - text
    mov ah, 40h
    int 21h
    mov ah, 3eh
    int 21h
done:
    mov ax, 4c00h
    int 21h

marker db 'ROLLED.OK', 0
text db 'fallback started', 13, 10
text_end:
