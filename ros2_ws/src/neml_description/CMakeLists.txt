# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

cmake_minimum_required(VERSION 3.16)
project(neml_description)

find_package(ament_cmake REQUIRED)

# meshes/ is empty in git on purpose: the STL artefacts are git-lfs objects
# produced by the FreeCAD template engine (NEML_SPEC.md SS12.1, SS15).
install(DIRECTORY urdf meshes DESTINATION share/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(urdf_rules test/test_urdf.py)
endif()

ament_package()
