# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# neml/sandbox:1.0 - SPEC 5.3. Nothing the model generates ever runs on the
# host; it runs here, with network: none, read_only_rootfs: true, cap_drop ALL,
# no-new-privileges, 2 CPU / 2 GB / 256 pids / 180 s, user 1000:1000.
#
# Build:  docker build -t neml/sandbox:1.0 docker/sandbox
#
# The image deliberately has no package manager, no utility that speaks a
# network protocol and no credentials. The static gate (ruff, mypy --strict,
# bandit, the forbidden-call list) runs before anything gets here; this image is
# the second wall, not the first.

FROM python:3.12-slim

# numpy is the one thing generated geometry and metric code legitimately needs.
# The deletions drop the package manager and every network client from the
# image, even though the container also runs with network: none. Two walls.
RUN pip install --no-cache-dir "numpy==2.*" \
    && rm -rf /usr/bin/apt* /usr/bin/dpkg* /usr/lib/apt /etc/apt \
    && rm -f /usr/bin/curl /usr/bin/wget /usr/bin/nc /usr/bin/netcat /usr/bin/ssh /usr/bin/scp \
    && rm -rf /root/.cache /var/lib/apt/lists/* /usr/local/bin/pip*

# /work is the only writable mount (SPEC 5.3), so everything that wants to write
# - HOME, temp files, caches - points at it. Nothing else is writable.
ENV HOME=/work \
    TMPDIR=/work/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=0 \
    MPLCONFIGDIR=/work/tmp

RUN useradd --no-create-home --uid 1000 --user-group neml \
    && mkdir -p /work && chown neml:neml /work
USER 1000:1000
WORKDIR /work

# The caller passes the script path; there is no default program to run.
ENTRYPOINT ["python"]
