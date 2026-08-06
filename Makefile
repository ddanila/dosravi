CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra -Werror -std=c89 -pedantic
DOSFLAGS = -0 -Md -ansi -O

.PHONY: all test check fuzz verify clean dos dos-test dosbox-headless dist

all: test

build/test_protocol: src/protocol.c tests/test_protocol.c include/dosravi.h
	mkdir -p build
	$(CC) $(CFLAGS) -Iinclude src/protocol.c tests/test_protocol.c -o $@

test: build/test_protocol
	./build/test_protocol
	python3 -m unittest discover -s tests -v

check: test
	ruff check .
	ruff format --check .
	cppcheck --enable=warning,performance,portability --error-exitcode=1 --suppress=missingIncludeSystem -Iinclude -I/usr/lib/bcc/include src/dosmain.c src/comprobe.c src/protocol.c tests/test_protocol.c

fuzz:
	bash tools/fuzz_decoder.sh

verify:
	bash tools/verify.sh

build/dos/protocol.o: src/protocol.c include/dosravi.h
	mkdir -p build/dos
	bcc $(DOSFLAGS) -Iinclude -c $< -o $@

build/dos/dosmain.o: src/dosmain.c include/dosravi.h
	mkdir -p build/dos
	bcc $(DOSFLAGS) -Iinclude -c $< -o $@

build/dos/uart.o: src/uart.asm
	mkdir -p build/dos
	nasm -f as86 $< -o $@

build/dos/DOSRAVI.COM: build/dos/dosmain.o build/dos/protocol.o build/dos/uart.o
	bcc -0 -Md -i -o $@ $^

build/dos/comprobe.o: src/comprobe.c
	mkdir -p build/dos
	bcc $(DOSFLAGS) -Iinclude -c $< -o $@

build/dos/COMPROBE.COM: build/dos/comprobe.o build/dos/uart.o
	bcc -0 -Md -i -o $@ $^

dos: build/dos/DOSRAVI.COM build/dos/COMPROBE.COM
	file build/dos/DOSRAVI.COM
	file build/dos/COMPROBE.COM

dos-test: dos
	bash tools/test_dosbox.sh

dosbox-headless: dos
	bash tools/run_dosbox_headless.sh

dist: dos
	bash tools/make_dist.sh build/dos/DOSRAVI.COM build/dos/COMPROBE.COM dos build/dist

clean:
	rm -rf build
