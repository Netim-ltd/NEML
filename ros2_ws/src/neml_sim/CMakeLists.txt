# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

cmake_minimum_required(VERSION 3.16)
project(neml_sim)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)

# One python module: the bridge config renderer the launch file imports.
ament_python_install_package(${PROJECT_NAME})

# World system plugin behind the /world/<w>/neml/* services (src/NemlSystem.cc).
# UNVERIFIED until built against Gazebo Harmonic (T-034).
find_package(gz-sim8 QUIET)
find_package(gz-plugin2 QUIET COMPONENTS register)
find_package(nlohmann_json QUIET)
find_package(OpenSSL QUIET)
if(gz-sim8_FOUND AND gz-plugin2_FOUND AND nlohmann_json_FOUND AND OpenSSL_FOUND)
  add_library(NemlSystem SHARED src/NemlSystem.cc)
  target_compile_features(NemlSystem PRIVATE cxx_std_17)
  target_link_libraries(NemlSystem PRIVATE gz-sim8::gz-sim8 gz-plugin2::register
                        nlohmann_json::nlohmann_json OpenSSL::Crypto)
  install(TARGETS NemlSystem LIBRARY DESTINATION lib/${PROJECT_NAME})
else()
  message(WARNING "Gazebo Harmonic / nlohmann_json / OpenSSL not found: NemlSystem not built")
endif()

install(DIRECTORY worlds models launch DESTINATION share/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(worlds test/test_worlds.py)
  ament_add_pytest_test(bridge_config test/test_bridge_config.py)
endif()

ament_package()
