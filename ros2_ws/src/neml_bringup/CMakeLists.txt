# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

cmake_minimum_required(VERSION 3.16)
project(neml_bringup)

find_package(ament_cmake REQUIRED)

install(DIRECTORY launch config DESTINATION share/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  find_package(launch_testing_ament_cmake REQUIRED)

  ament_add_pytest_test(launch_descriptions test/test_launch_descriptions.py)
  # SS18.1: launch tests on all bringup. This one starts the real safety stack.
  add_launch_test(test/test_safety_launch.py TIMEOUT 60)
endif()

ament_package()
