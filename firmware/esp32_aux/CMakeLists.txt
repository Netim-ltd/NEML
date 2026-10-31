# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# NEML esp32_aux v1.1.0 - SPEC 13.3 electronics.aux_mcu.firmware.
#
# Firmware:   idf.py set-target esp32s3 && idf.py build
# Host tests: cmake -B build-test -DHOST_TESTS=ON && cmake --build build-test
#             && ctest --test-dir build-test

cmake_minimum_required(VERSION 3.16)

option(HOST_TESTS "Build the host tests instead of the firmware" OFF)

if(HOST_TESTS)
  project(esp32_aux_tests C)
  set(CMAKE_C_STANDARD 11)
  set(CMAKE_C_STANDARD_REQUIRED ON)
  add_executable(test_sensors test/test_sensors.c)
  target_include_directories(test_sensors PRIVATE main ..)
  if(UNIX)
    target_compile_options(test_sensors PRIVATE -Wall -Wextra -Werror)
    target_link_libraries(test_sensors PRIVATE m)
  endif()
  enable_testing()
  add_test(NAME esp32_aux_sensors COMMAND test_sensors)
  return()
endif()

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(esp32_aux)
