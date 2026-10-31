# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# NEML stm32_motion v1.4.2 - SPEC 13.3 electronics.motion_controller.firmware.
#
# Two builds live here:
#   cmake -B build-test -DHOST_TESTS=ON && cmake --build build-test && ctest --test-dir build-test
#   cmake -B build -DSTM32CUBEF4_DIR=... -DMICROROS_DIR=... && cmake --build build
#
# STM32CubeF4 (BSD-3-Clause) and the pre-built micro-ROS static library are
# referenced from outside the tree, never copied into it: SPEC 1.3 keeps third
# party source out of this repository.

cmake_minimum_required(VERSION 3.20)

option(HOST_TESTS "Build the host tests instead of the firmware" OFF)

if(HOST_TESTS)
  project(stm32_motion_tests C)
  set(CMAKE_C_STANDARD 11)
  set(CMAKE_C_STANDARD_REQUIRED ON)
  add_executable(test_stm32_motion
    test/test_stm32_motion.c
    src/control.c
    src/servo_bus.c)
  target_include_directories(test_stm32_motion PRIVATE include ..)
  if(UNIX)
    target_compile_options(test_stm32_motion PRIVATE -Wall -Wextra -Werror)
    target_link_libraries(test_stm32_motion PRIVATE m)
  endif()
  enable_testing()
  add_test(NAME stm32_motion COMMAND test_stm32_motion)
  return()
endif()

set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_SYSTEM_PROCESSOR arm)
set(CMAKE_C_COMPILER arm-none-eabi-gcc)
set(CMAKE_ASM_COMPILER arm-none-eabi-gcc)
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

project(stm32_motion C ASM)
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

set(STM32CUBEF4_DIR "" CACHE PATH "STM32CubeF4 checkout (Drivers/ lives here)")
set(MICROROS_DIR "" CACHE PATH "micro-ROS static library: include/ and libmicroros.a")
set(NEML_ROBOT_NS "robot_01" CACHE STRING "ROS namespace, one per robot")

if(NOT EXISTS "${STM32CUBEF4_DIR}/Drivers/STM32F4xx_HAL_Driver")
  message(FATAL_ERROR "STM32CUBEF4_DIR does not point at an STM32CubeF4 checkout")
endif()
if(NOT EXISTS "${MICROROS_DIR}/libmicroros.a")
  message(FATAL_ERROR "MICROROS_DIR must contain libmicroros.a - see README.md")
endif()

set(CMSIS "${STM32CUBEF4_DIR}/Drivers/CMSIS")
set(HAL "${STM32CUBEF4_DIR}/Drivers/STM32F4xx_HAL_Driver")

# Only the HAL modules enabled in include/stm32f4xx_hal_conf.h.
set(HAL_SRC
  ${HAL}/Src/stm32f4xx_hal.c
  ${HAL}/Src/stm32f4xx_hal_cortex.c
  ${HAL}/Src/stm32f4xx_hal_dma.c
  ${HAL}/Src/stm32f4xx_hal_flash.c
  ${HAL}/Src/stm32f4xx_hal_flash_ex.c
  ${HAL}/Src/stm32f4xx_hal_gpio.c
  ${HAL}/Src/stm32f4xx_hal_pwr.c
  ${HAL}/Src/stm32f4xx_hal_pwr_ex.c
  ${HAL}/Src/stm32f4xx_hal_rcc.c
  ${HAL}/Src/stm32f4xx_hal_rcc_ex.c
  ${HAL}/Src/stm32f4xx_hal_tim.c
  ${HAL}/Src/stm32f4xx_hal_tim_ex.c
  ${HAL}/Src/stm32f4xx_hal_uart.c)

set(NEML_SRC src/main.c src/control.c src/servo_bus.c)

add_executable(${PROJECT_NAME}.elf
  ${NEML_SRC}
  ${HAL_SRC}
  ${CMSIS}/Device/ST/STM32F4xx/Source/Templates/system_stm32f4xx.c
  ${CMSIS}/Device/ST/STM32F4xx/Source/Templates/gcc/startup_stm32f446xx.s)

target_include_directories(${PROJECT_NAME}.elf PRIVATE
  include
  ..                                  # firmware/neml_limits.h, shared by all three MCUs
  ${CMSIS}/Include
  ${CMSIS}/Device/ST/STM32F4xx/Include
  ${HAL}/Inc
  ${MICROROS_DIR}/include)

target_compile_definitions(${PROJECT_NAME}.elf PRIVATE
  STM32F446xx
  USE_HAL_DRIVER
  NEML_ROBOT_NS="${NEML_ROBOT_NS}")

# Hard float: libmicroros.a must be built with exactly these four flags or the
# link fails with an ABI mismatch.
set(MCU_FLAGS -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard)

target_compile_options(${PROJECT_NAME}.elf PRIVATE
  ${MCU_FLAGS} -Os -g3 -ffunction-sections -fdata-sections -fno-common)

# -Werror on our own code only; the vendor HAL is not ours to fix.
set_source_files_properties(${NEML_SRC} PROPERTIES COMPILE_OPTIONS "-Wall;-Wextra;-Werror")

target_link_options(${PROJECT_NAME}.elf PRIVATE
  ${MCU_FLAGS}
  -T${CMAKE_CURRENT_SOURCE_DIR}/stm32f446re.ld
  -specs=nano.specs
  -specs=nosys.specs
  -Wl,--gc-sections
  -Wl,-Map=${PROJECT_NAME}.map
  -Wl,--print-memory-usage)

target_link_libraries(${PROJECT_NAME}.elf PRIVATE ${MICROROS_DIR}/libmicroros.a m)

add_custom_command(TARGET ${PROJECT_NAME}.elf POST_BUILD
  COMMAND arm-none-eabi-objcopy -O binary $<TARGET_FILE:${PROJECT_NAME}.elf> ${PROJECT_NAME}.bin
  COMMAND arm-none-eabi-objcopy -O ihex   $<TARGET_FILE:${PROJECT_NAME}.elf> ${PROJECT_NAME}.hex
  COMMAND arm-none-eabi-size $<TARGET_FILE:${PROJECT_NAME}.elf>)

# SPEC 5.4 global_forbidden: firmware.flash. No agent may invoke this target. A
# human runs it at the bench, behind a Level 4 approval (SPEC 5.2).
add_custom_target(flash
  COMMAND openocd -f interface/stlink.cfg -f target/stm32f4x.cfg
          -c "program ${PROJECT_NAME}.elf verify reset exit"
  DEPENDS ${PROJECT_NAME}.elf
  COMMENT "HUMAN ONLY - flashing is not an agent action (SPEC 5.4)")
