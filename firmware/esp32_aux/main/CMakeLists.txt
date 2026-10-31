# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# "../.." is firmware/, for neml_limits.h - the one limits header shared by all
# three MCUs (SPEC 5.1 / 13.3). It is included, never copied: two copies of a
# safety limit is how they drift apart.

idf_component_register(
  SRCS "main.c"
  INCLUDE_DIRS "." "../.."
  REQUIRES micro_ros_espidf_component driver esp_adc esp_timer)
