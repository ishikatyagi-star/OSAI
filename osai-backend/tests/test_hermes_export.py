"""Tests for the OSAI -> Hermes export bridge."""

from __future__ import annotations

import json

from evals.fixtures import FIXTURES
from evals.hermes_export import export_all


def test_export_writes_skill_and_dataset(tmp_path):
    paths = export_all(tmp_path)
    assert paths["skill"].exists()
    assert paths["skill"].name == "SKILL.md"

    data = json.loads(paths["dataset"].read_text())
    assert len(data) == len(FIXTURES)
    for ex in data:
        assert "question" in ex["inputs"]
        assert ex["expected_behavior"]
