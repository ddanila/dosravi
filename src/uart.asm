BITS 16

SECTION .text

GLOBAL _dr_uart_bios_base
GLOBAL _dr_uart_save
GLOBAL _dr_uart_restore
GLOBAL _dr_uart_init
GLOBAL _dr_uart_capability
GLOBAL _dr_uart_rx_ready
GLOBAL _dr_uart_lsr
GLOBAL _dr_uart_get
GLOBAL _dr_uart_put
GLOBAL _dr_uart_drain
GLOBAL _dr_uart_loopback
GLOBAL _dr_uart_external_loopback
GLOBAL _dr_key_ready
GLOBAL _dr_key_get

; unsigned dr_key_ready(void), nonzero when BIOS has a console key buffered.
_dr_key_ready:
    mov ah, 01h
    int 16h
    mov ax, 0
    jz .no_key
    inc ax
.no_key:
    ret

; unsigned dr_key_get(void), blocking BIOS read with ASCII in the low byte.
_dr_key_get:
    mov ah, 00h
    int 16h
    xor ah, ah
    ret

; unsigned dr_uart_bios_base(unsigned index), index 0..3
_dr_uart_bios_base:
    push bp
    mov bp, sp
    push es
    mov bx, [bp+4]
    shl bx, 1
    mov ax, 0040h
    mov es, ax
    mov ax, [es:bx]
    pop es
    pop bp
    ret

; void dr_uart_save(unsigned base, unsigned char state[7])
; IER, LCR, MCR, SCR, DLL, DLM, and IIR FIFO-enable indication.
_dr_uart_save:
    push bp
    mov bp, sp
    push si
    push dx
    mov dx, [bp+4]
    mov si, [bp+6]
    inc dx
    in al, dx
    mov [si], al
    add dx, 2
    in al, dx
    mov [si+1], al
    inc dx
    in al, dx
    mov [si+2], al
    add dx, 3
    in al, dx
    mov [si+3], al
    sub dx, 4
    mov al, [si+1]
    or al, 080h
    out dx, al
    sub dx, 3
    in al, dx
    mov [si+4], al
    inc dx
    in al, dx
    mov [si+5], al
    add dx, 2
    mov al, [si+1]
    out dx, al
    dec dx
    in al, dx
    and al, 0c0h
    mov [si+6], al
    pop dx
    pop si
    pop bp
    ret

; void dr_uart_restore(unsigned base, unsigned char state[7])
_dr_uart_restore:
    push bp
    mov bp, sp
    push si
    push dx
    mov dx, [bp+4]
    mov si, [bp+6]
    add dx, 2
    xor al, al
    out dx, al                 ; disable FIFO (original FCR cannot be read)
    inc dx
    mov al, [si+1]
    or al, 080h
    out dx, al
    sub dx, 3
    mov al, [si+4]
    out dx, al
    inc dx
    mov al, [si+5]
    out dx, al
    add dx, 2
    mov al, [si+1]
    out dx, al
    inc dx
    mov al, [si+2]
    out dx, al
    add dx, 3
    mov al, [si+3]
    out dx, al
    sub dx, 6
    mov al, [si]
    out dx, al
    inc dx
    xor al, al
    cmp byte [si+6], 0
    je .fifo_restored
    mov al, 1
.fifo_restored:
    out dx, al
    pop dx
    pop si
    pop bp
    ret

; void dr_uart_init(unsigned base, unsigned divisor)
_dr_uart_init:
    push bp
    mov bp, sp
    push dx
    mov dx, [bp+4]
    inc dx
    xor al, al
    out dx, al                 ; no UART interrupts
    inc dx
    out dx, al                 ; FIFO off for 8250-compatible behavior
    inc dx
    mov al, 080h
    out dx, al
    sub dx, 3
    mov ax, [bp+6]
    out dx, al
    inc dx
    mov al, ah
    out dx, al
    add dx, 2
    mov al, 003h               ; 8 data, no parity, one stop
    out dx, al
    inc dx
    mov al, 003h               ; DTR and RTS
    out dx, al
    pop dx
    pop bp
    ret

; unsigned dr_uart_capability(unsigned base)
; Returns IIR FIFO identification bits: 00=8250/16450, 40=broken, C0=16550A.
_dr_uart_capability:
    push bp
    mov bp, sp
    mov dx, [bp+4]
    add dx, 2
    mov al, 001h
    out dx, al
    in al, dx
    and al, 0c0h
    mov ah, al
    xor al, al
    out dx, al
    mov al, ah
    xor ah, ah
    pop bp
    ret

_dr_uart_rx_ready:
    push bp
    mov bp, sp
    mov dx, [bp+4]
    add dx, 5
    in al, dx
    and ax, 1
    pop bp
    ret

; unsigned dr_uart_lsr(unsigned base), raw line-status register snapshot.
_dr_uart_lsr:
    push bp
    mov bp, sp
    mov dx, [bp+4]
    add dx, 5
    in al, dx
    xor ah, ah
    pop bp
    ret

_dr_uart_get:
    push bp
    mov bp, sp
    mov dx, [bp+4]
.rx_wait:
    push dx
    add dx, 5
    in al, dx
    pop dx
    test al, 1
    jz .rx_wait
    in al, dx
    xor ah, ah
    pop bp
    ret

_dr_uart_put:
    push bp
    mov bp, sp
    mov dx, [bp+4]
.tx_wait:
    push dx
    add dx, 5
    in al, dx
    pop dx
    test al, 020h
    jz .tx_wait
    mov ax, [bp+6]
    out dx, al
    pop bp
    ret

; void dr_uart_drain(unsigned base), wait until holding and shift registers empty.
_dr_uart_drain:
    push bp
    mov bp, sp
    push cx
    mov dx, [bp+4]
    add dx, 5
    xor cx, cx
.drain_wait:
    in al, dx
    test al, 040h
    jnz .drain_done
    loop .drain_wait
.drain_done:
    pop cx
    pop bp
    ret

; int dr_uart_loopback(unsigned base), nonzero on successful 4-byte test.
_dr_uart_loopback:
    push bp
    mov bp, sp
    push bx
    push di
    mov dx, [bp+4]
    add dx, 4
    in al, dx
    mov ah, al
    mov al, 01eh               ; loopback, RTS/DTR/OUT1/OUT2
    out dx, al
    sub dx, 4
    mov bx, 0
.loop:
    mov al, bl
    xor al, 0a5h
    out dx, al
    push dx
    add dx, 5
    mov di, 0ffffh
.ready:
    in al, dx
    test al, 1
    jnz .received
    dec di
    jnz .ready
    pop dx
    jmp .failed
.received:
    pop dx
    in al, dx
    mov cl, bl
    xor cl, 0a5h
    cmp al, cl
    jne .failed
    inc bl
    cmp bl, 4
    jb .loop
    mov bx, 1
    jmp .restore
.failed:
    xor bx, bx
.restore:
    add dx, 4
    mov al, ah
    out dx, al
    mov ax, bx
    pop di
    pop bx
    pop bp
    ret

; int dr_uart_external_loopback(unsigned base)
; Requires an RS-232 loopback plug. Sends and verifies 64 deterministic bytes.
_dr_uart_external_loopback:
    push bp
    mov bp, sp
    push bx
    push cx
    push di
    mov dx, [bp+4]
    mov bx, 0
.external_next:
    push dx
    add dx, 5
    mov di, 0ffffh
.external_tx_ready:
    in al, dx
    test al, 020h
    jnz .external_tx_available
    dec di
    jnz .external_tx_ready
    pop dx
    xor ax, ax
    jmp .external_done
.external_tx_available:
    pop dx
    mov al, bl
    xor al, 05ah
    out dx, al
    push dx
    add dx, 5
    mov di, 0ffffh
.external_rx_wait:
    in al, dx
    test al, 1
    jnz .external_received
    dec di
    jnz .external_rx_wait
    pop dx
    xor ax, ax
    jmp .external_done
.external_received:
    pop dx
    in al, dx
    mov cl, bl
    xor cl, 05ah
    cmp al, cl
    jne .external_failed
    inc bl
    cmp bl, 64
    jb .external_next
    mov ax, 1
    jmp .external_done
.external_failed:
    xor ax, ax
.external_done:
    pop di
    pop cx
    pop bx
    pop bp
    ret
