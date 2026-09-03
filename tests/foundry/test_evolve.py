from __future__ import annotations

from pathlib import Path

import yaml

from foundry.evolve import evolve

ROOT = Path(__file__).parents[2]
SPEC = ROOT / "foundry" / "worlds" / "unmapped_province.seed.yaml"


def test_quality_diversity_search_is_deterministic() -> None:
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    first = evolve(spec, population=8)
    second = evolve(spec, population=8)
    assert first == second
    assert first["admitted"] > 0
    assert first["occupied_behavior_cells"] > 0
