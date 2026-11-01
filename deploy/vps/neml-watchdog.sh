#!/bin/sh
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
# Docker marks a hung container "unhealthy" but never restarts it; the brain once sat hung for two days.
# Install on the host (root crontab):  */2 * * * * /path/to/neml-watchdog.sh
for c in $(docker ps --filter health=unhealthy --format '{{.Names}}' | grep '^neml-'); do
  logger -t neml-watchdog "restarting $c"
  docker restart "$c"
done
