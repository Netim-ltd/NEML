# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

from setuptools import setup

package_name = "neml_perception"

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
    description="Depth camera pipeline with the SS17.2 camera egress gate.",
    license="AGPL-3.0-or-later",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "camera_gate = neml_perception.camera_gate_node:main",
        ],
    },
)
