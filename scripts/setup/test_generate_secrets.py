# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
from pathlib import Path

import check_control_env
import generate_secrets


def test_full_flags_pass_both_env_checks(tmp_path: Path) -> None:
    generate_secrets.main(
        [
            "--out", str(tmp_path), "--owner-email", "me@firm.com", "--namespace", "firm",
            "--tenant", "firm", "--db-host", "db.firm.com", "--api-db-password", "a" * 20,
            "--brain-db-password", "b" * 20, "--llm-url", "https://gpu.firm.com/v1",
            "--embed-url", "https://emb.firm.com", "--mcp-base", "https://lab.firm.com",
        ]
    )
    brain = check_control_env.read_env(tmp_path / "NEML_BRAIN_ENV.txt")
    api = check_control_env.read_env(tmp_path / "NEML_API_ENV.txt")
    assert check_control_env.validate(brain) == []
    assert brain["NEML_API_KEY"] == api["Bridge__ApiKey"]
    assert brain["NEML_OWNERS"] == api["NEML_OWNER_EMAIL"] == "me@firm.com"


def test_missing_values_stay_markers_so_the_check_fails(tmp_path: Path, capsys) -> None:
    generate_secrets.main(["--out", str(tmp_path)])
    brain = check_control_env.read_env(tmp_path / "NEML_BRAIN_ENV.txt")
    assert check_control_env.validate(brain) != []
    assert "still to fill" in capsys.readouterr().out
