-- Copyright (c) 2026 Mustafa Gulsoy.
-- SPDX-License-Identifier: AGPL-3.0-or-later
--
-- NEML_SPEC.md 17.4 step 2:  psql -f scripts/db/seed.sql
-- Run AFTER `alembic -c brain/alembic.ini upgrade head`. Idempotent: re-running changes nothing.
--
-- NOT seeded here: the reference worlds. SPEC 7 declares no table for them -- worlds are
-- referenced by `sim_runs.world_id` as a free TEXT id and live as files under
-- ros2_ws/src/neml_sim (SPEC 15). There is nothing to insert.

BEGIN;

-- ---------------------------------------------------------------------------
-- Owner user (neml_cloud only -- SPEC 7). Harmless no-op where `users` is absent
-- is NOT possible in plain SQL, so run this file against neml_cloud as well as
-- neml_local; the migration creates `users` in both.
--
-- CHANGEME: `password_hash` below is a placeholder, not a valid argon2id hash.
-- Nobody can log in with it. Replace it before the API is reachable:
--     UPDATE users SET email = '<real>', password_hash = '<argon2id hash>'
--      WHERE role = 'owner';
-- SPEC 9.3/5.5: hashes are produced by neml-api (Argon2), never by hand.
-- ---------------------------------------------------------------------------
INSERT INTO users (email, password_hash, role)
VALUES ('owner@neml.local', 'CHANGEME_argon2id_hash', 'owner')
ON CONFLICT (email) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Initial genome: quadruped_v2 (SPEC 13.3).
-- `parent_id` is NULL on purpose: SPEC 13.3 names the parent quadruped_v1@8e2bd40 but gives
-- no body for it, and genomes.parent_id is a FK. The lineage stays recorded in body->>'parent'.
-- `limits` is the L4-immutable block (SPEC 13.3) and is enforced in code, not only here.
-- ---------------------------------------------------------------------------
INSERT INTO genomes (id, name, version, hash, parent_id, status, body, limits, fitness_score)
VALUES (
    'quadruped_v2@a3f91c7',
    'quadruped_v2',
    2,
    'a3f91c7',
    NULL,
    'active',
    $genome${
      "schema_version": 1,
      "genome_id": "quadruped_v2",
      "hash": "a3f91c7",
      "parent": "quadruped_v1@8e2bd40",
      "created": "2026-02-08",
      "status": "active",
      "morphology": {
        "body_type": "quadruped",
        "leg_count": 4,
        "dof_per_leg": 4,
        "total_dof": 16
      },
      "mechanical": {
        "material": "PA6-CF",
        "material_density_g_cm3": 1.17,
        "body_mass_kg": 2.40,
        "body_mass_cad_kg": 2.31,
        "cad_templates": {
          "leg_link": {
            "template": "leg_link_v1",
            "params": {"length_mm": 120, "width_mm": 28, "wall_mm": 2.0, "rib_count": 3}
          },
          "foot_pad": {
            "template": "foot_pad_v1",
            "params": {"diameter_mm": 32, "wall_mm": 2.4, "material": "TPU"}
          }
        },
        "param_ranges": {
          "leg_link.length_mm": [100, 145],
          "leg_link.wall_mm": [1.6, 3.2],
          "leg_link.rib_count": [0, 5]
        }
      },
      "electronics": {
        "compute": {"model": "raspberry_pi_5_8gb"},
        "motion_controller": {"model": "stm32f446", "firmware": "firmware/stm32_motion@v1.4.2"},
        "aux_mcu": {"model": "esp32s3", "firmware": "firmware/esp32_aux@v1.1.0"},
        "safety_mcu": {"model": "atmega328p", "firmware": "firmware/safety_watchdog@v1.0.3"},
        "actuators": {"model": "sts3215", "count": 16, "stall_torque_nm": 2.9},
        "sensors": [
          {"type": "imu", "model": "bno085", "rate_hz": 100},
          {"type": "depth_camera", "model": "realsense_d405", "rate_hz": 15},
          {"type": "current", "model": "ina226", "count": 2}
        ]
      },
      "power": {
        "battery": {"chemistry": "lipo", "cells": 4, "capacity_mah": 5200, "c_rating": 25},
        "bms": "required",
        "rails": [
          {"v": 5.0, "a_max": 5.0, "converter": "buck_5v5a"},
          {"v": 3.3, "a_max": 2.0, "converter": "ldo_3v3"}
        ]
      },
      "manufacturing": {
        "print_time_h": 18.5,
        "material_cost_try": 640,
        "bom_cost_try": 9800,
        "assembly_time_h": 4.0
      },
      "performance": {
        "max_speed_mps": 0.42,
        "endurance_min": 34,
        "mtbf_h": 11.2
      },
      "fitness": {
        "score": 0.7140,
        "campaign": "campaign_003",
        "weights_ref": "evolution/experiments/campaign_003/weights.yaml"
      }
    }$genome$::jsonb,
    $limits${
      "joint_torque_nm_max": 2.5,
      "joint_velocity_rads_max": 6.0,
      "body_current_a_max": 20.0,
      "body_temp_c_max": 70.0
    }$limits$::jsonb,
    0.7140
)
ON CONFLICT (id) DO NOTHING;

COMMIT;
