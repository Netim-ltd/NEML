# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
from neml_brain.evolution.scripted import examples, remember


def test_a_working_script_comes_back_for_a_similar_part_and_the_closest_one_first(tmp_path):
    remember(tmp_path, "motor braketi", [40, 30, 20], "result = Box(40, 30, 20)")
    remember(tmp_path, "batarya kutusu", [80, 40, 30], "result = Box(80, 40, 30)")
    text = examples(tmp_path, "batarya yuvası kutusu", [82, 40, 30], n=1)
    assert "Box(80, 40, 30)" in text and "Box(40, 30, 20)" not in text


def test_no_memory_means_no_examples_and_a_repeat_is_not_stored_twice(tmp_path):
    assert examples(tmp_path, "x", [1, 2, 3]) == ""
    remember(tmp_path, "a", [1, 2, 3], "result = Box(1, 2, 3)")
    remember(tmp_path, "a", [1, 2, 3], "result = Box(1, 2, 3)")
    assert examples(tmp_path, "a", [1, 2, 3], n=5).count("result = Box") == 1
