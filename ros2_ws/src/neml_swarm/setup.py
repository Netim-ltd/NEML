# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

from setuptools import setup

package_name = "neml_swarm"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Mustafa Gulsoy",
    maintainer_email="mustafa.gulsoy@neml.local",
    description="Lease-based swarm coordination and link guard (NEML_SPEC.md T-082, T-083).",
    license="AGPL-3.0-or-later",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "swarm_coordinator = neml_swarm.coordinator_node:main",
            "lease_agent = neml_swarm.lease_agent_node:main",
            "link_guard = neml_swarm.link_guard_node:main",
            "feedback_monitor = neml_swarm.feedback_node:main",
        ],
    },
)
