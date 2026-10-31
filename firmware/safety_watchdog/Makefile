# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# NEML safety_watchdog v1.0.3 - SPEC 13.3 electronics.safety_mcu.firmware.
# Ubuntu 24.04: sudo apt install gcc-avr avr-libc avrdude
#
#   make        build the operational firmware
#   make test   run the host test of the decision logic
#   make flash  HUMAN ONLY - see the note on the flash target

MCU     := atmega328p
F_CPU   := 16000000UL
BUILD   := build
TARGET  := $(BUILD)/safety_watchdog

CC      := avr-gcc
OBJCOPY := avr-objcopy
SIZE    := avr-size
HOSTCC  ?= cc

CFLAGS  := -std=c11 -Os -Wall -Wextra -Werror -mmcu=$(MCU) -DF_CPU=$(F_CPU) \
           -Iinclude -ffunction-sections -fdata-sections -fno-common -flto
LDFLAGS := -mmcu=$(MCU) -Wl,--gc-sections -flto

# usbasp is what sits on the bench; override on the command line if yours differs.
PROGRAMMER ?= usbasp
AVRDUDE    := avrdude -c $(PROGRAMMER) -p m328p

SRC  := src/main.c
DEPS := $(SRC) include/watchdog_core.h

.PHONY: all test wdttest flash fuses clean
.DELETE_ON_ERROR:

all: $(TARGET).hex
	$(SIZE) --format=avr --mcu=$(MCU) $(TARGET).elf

# T-071 step 4 only: hangs on purpose after ~2 s so the hardware watchdog path
# can be put on the scope. Separate file name so it can never be confused with
# the operational hex.
wdttest: $(BUILD)/safety_watchdog_WDTTEST.hex

$(BUILD):
	mkdir -p $(BUILD)

$(TARGET).elf: $(DEPS) | $(BUILD)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $(SRC)

$(BUILD)/safety_watchdog_WDTTEST.elf: $(DEPS) | $(BUILD)
	$(CC) $(CFLAGS) -DWDT_HANG_TEST $(LDFLAGS) -o $@ $(SRC)

%.hex: %.elf
	$(OBJCOPY) -O ihex -R .eeprom $< $@

test: | $(BUILD)
	$(HOSTCC) -std=c11 -Wall -Wextra -Werror -Iinclude \
	    test/test_watchdog_core.c -o $(BUILD)/test_watchdog_core
	$(BUILD)/test_watchdog_core

# SPEC 5.4 global_forbidden: firmware.flash. No agent, no autonomy loop and no
# MCP server may run this target. A human types it, at the bench, with the motor
# bus physically disconnected, and records the T-071 re-test afterwards.
flash: $(TARGET).hex
	$(AVRDUDE) -U flash:w:$(TARGET).hex:i

# lfuse FF  external 16 MHz crystal, full swing, slow rising power, CKDIV8 off
# hfuse D9  no bootloader, reset pin enabled, WDT under software control
# efuse FC  brown-out at 4.3 V - below 4.5 V a 16 MHz part is out of spec, so it
#           must reset (and drop the relay) instead of running erratically
fuses:
	$(AVRDUDE) -U lfuse:w:0xFF:m -U hfuse:w:0xD9:m -U efuse:w:0xFC:m

clean:
	rm -rf $(BUILD)
