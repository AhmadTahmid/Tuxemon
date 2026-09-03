from __future__ import annotations

import json
from pathlib import Path

import yaml

from foundry.campaign import synthesize

ROOT = Path(__file__).parents[2]
SPEC = ROOT / "foundry" / "worlds" / "unmapped_province.seed.yaml"
ECOLOGY = ROOT / "foundry" / "worlds" / "echo_wilds.ecology.lock.json"


def test_campaign_population_is_deterministic_and_admitted() -> None:
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    ecology = json.loads(ECOLOGY.read_text(encoding="utf-8"))
    first = synthesize(spec, ecology)
    second = synthesize(spec, ecology)

    assert first == second
    assert all(proof["passed"] for proof in first["proofs"])
    assert first["population"]["candidates_examined"] > 1
    assert len(first["selected"]["regions"]) == 3


def test_campaign_assigns_proven_guardians_to_dramatic_roles() -> None:
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    ecology = json.loads(ECOLOGY.read_text(encoding="utf-8"))
    result = synthesize(spec, ecology)
    regions = result["selected"]["regions"]

    assert [region["narrative_role"] for region in regions] == [
        "ordeal",
        "respite",
        "culmination",
    ]
    assert [region["ecology"]["selected"]["monster"] for region in regions] == [
        "metesaur",
        "toucanary",
        "vivipere",
    ]
    transitions = result["selected"]["narrative_automaton"]["transitions"]
    assert transitions[0][0] == "arrival"
    assert transitions[-1][2] == "province_mapped"
    assert all(
        left[2] == right[0] for left, right in zip(transitions, transitions[1:])
    )
