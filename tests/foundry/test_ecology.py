from __future__ import annotations

import json
from pathlib import Path

import yaml

from foundry.ecology import derive_species
from foundry.release import _canonical_fingerprint

ROOT = Path(__file__).parents[2]
SPEC = ROOT / "foundry" / "worlds" / "unmapped_province.seed.yaml"
LOCK = ROOT / "foundry" / "worlds" / "echo_wilds.ecology.lock.json"


def test_habitat_query_is_deterministic_and_diverse() -> None:
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    first, eligible = derive_species(ROOT, spec)
    second, _ = derive_species(ROOT, spec)

    assert first == second
    assert len(first) == min(
        eligible, spec["expedition"]["ecology"]["species_budget"]
    )
    assert len({item["primary_type"] for item in first}) >= 3
    assert spec["actors"]["starter_monster"] not in {
        item["slug"] for item in first
    }


def test_locked_ecology_is_an_admitted_actual_engine_survivor() -> None:
    certificate = json.loads(LOCK.read_text(encoding="utf-8"))
    selected = certificate["selected"]
    candidate = next(
        item
        for item in certificate["candidates"]
        if item["monster"] == selected["monster"]
        and item["level"] == selected["level"]
    )

    assert certificate["fingerprint"] == _canonical_fingerprint(certificate)
    assert all(proof["passed"] for proof in certificate["proofs"])
    assert candidate["admitted"]
    assert {item["winner"] for item in candidate["outcomes"]} == {
        "player",
        "opponent",
    }
