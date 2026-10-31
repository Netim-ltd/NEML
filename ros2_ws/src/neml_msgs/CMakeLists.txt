# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

cmake_minimum_required(VERSION 3.16)
project(neml_msgs)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(std_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(action_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/BatteryState.msg"
  "msg/SafetyStatus.msg"
  "msg/JointTelemetry.msg"
  "msg/RobotState.msg"
  "srv/SetDeploymentLevel.srv"
  "srv/RunSelfTest.srv"
  "action/ExecuteSkill.action"
  "action/RunManoeuvre.action"
  DEPENDENCIES builtin_interfaces std_msgs geometry_msgs action_msgs
)

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(interface_docs test/test_interfaces.py)
endif()

ament_package()
