BITS 16
ORG 100h

start:
    mov bx, 1
    mov dx, stdout_text
    mov cx, stdout_end - stdout_text
    mov ah, 40h
    int 21h

    mov bx, 2
    mov dx, stderr_text
    mov cx, stderr_end - stderr_text
    mov ah, 40h
    int 21h

    mov dx, artifact_name
    xor cx, cx
    mov ah, 3ch
    int 21h
    jc short append_run
    mov bx, ax
    mov dx, artifact_text
    mov cx, artifact_end - artifact_text
    mov ah, 40h
    int 21h
    mov ah, 3eh
    int 21h

append_run:
    mov dx, runs_name
    mov ax, 3d02h
    int 21h
    jnc short have_runs
    mov dx, runs_name
    xor cx, cx
    mov ah, 3ch
    int 21h
    jc short finished
have_runs:
    mov bx, ax
    xor cx, cx
    xor dx, dx
    mov ax, 4202h
    int 21h
    mov dx, run_marker
    mov cx, 1
    mov ah, 40h
    int 21h
    mov ah, 3eh
    int 21h

finished:
    mov ax, 4c07h
    int 21h

stdout_text db 'captured stdout', 13, 10
stdout_end:
stderr_text db 'captured stderr', 13, 10
stderr_end:
artifact_name db 'FILE.OUT', 0
artifact_text db 'child artifact', 13, 10
artifact_end:
runs_name db 'RUNS.BIN', 0
run_marker db 'X'
