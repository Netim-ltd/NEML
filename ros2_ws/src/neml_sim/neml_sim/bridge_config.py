# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Render config/gz_bridge.yaml into something ros_gz_bridge can load.

NEML_SPEC.md SS11.1 points the bridge at config/gz_bridge.yaml. That file is
written for humans and for the whole fleet: it carries <ns> and <world>
placeholders and a `qos_profiles` block that states the SS17.2 intent. The
bridge itself wants a plain list of entries for one robot in one world, and
Jazzy's ros_gz_bridge has no per-entry QoS field at all, so the qos keys are
declarations, not settings.

This module does the substitution and hands back the entry list. Pure text in,
pure data out - no ROS, no filesystem - so the launch file stays a wiring file
and the mapping is testable on any machine.
"""

import re

import yaml

# Anything left looking like <name> after substitution is a typo in the config
# (<robot> instead of <ns>, say). Catching the shape rather than the two known
# names is what turns that typo into an error instead of a bridge that maps a
# topic nobody publishes.
PLACEHOLDER_RE = re.compile(r"<[a-z_]+>")


def render_bridge_config(raw_yaml: str, namespace: str, world: str) -> list[dict]:
    """Substitute the placeholders and strip the non-bridge keys.

    Raises ValueError when a placeholder survives, which is the only failure
    mode that would otherwise show up as a bridge that silently carries no
    traffic at all.
    """
    if not namespace or not world:
        raise ValueError("namespace and world are required")

    doc = yaml.safe_load(raw_yaml) or {}
    entries = doc.get("bridges", [])

    rendered = []
    for entry in entries:
        out = {
            key: (
                value.replace("<ns>", namespace).replace("<world>", world)
                if isinstance(value, str)
                else value
            )
            for key, value in entry.items()
            # `qos` is NEML's own annotation, not a ros_gz_bridge key.
            if key != "qos"
        }
        leftover = [
            v for v in out.values()
            if isinstance(v, str) and PLACEHOLDER_RE.search(v)
        ]
        if leftover:
            raise ValueError(f"unsubstituted placeholder in {leftover}")
        rendered.append(out)

    if not rendered:
        raise ValueError("bridge config has no `bridges` entries")
    return rendered


def qos_class_of(raw_yaml: str, ros_topic_name: str) -> str | None:
    """The SS17.2 QoS class the config declares for a topic template, or None.

    Used by the launch file for its log line and by the tests. It is read-only
    documentation until ros_gz_bridge grows a QoS setting upstream.
    """
    doc = yaml.safe_load(raw_yaml) or {}
    for entry in doc.get("bridges", []):
        if entry.get("ros_topic_name") == ros_topic_name:
            return entry.get("qos")
    return None
