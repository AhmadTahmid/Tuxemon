from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from foundry.town import certify, compile_world, generate_town

ROOT = Path(__file__).parents[2]
SPEC = ROOT / "foundry" / "worlds" / "unmapped_province.seed.yaml"


def load_town():
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    return generate_town(spec)


def test_world_is_admitted() -> None:
    certificate = certify(load_town())
    assert all(proof["passed"] for proof in certificate["proofs"])


def test_geometry_is_deterministic() -> None:
    first = load_town()
    second = load_town()
    assert first.ground == second.ground
    assert first.objects == second.objects
    assert first.blocked == second.blocked


def test_compiler_outputs_are_deterministic(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first = compile_world(ROOT, SPEC, first_root)
    second = compile_world(ROOT, SPEC, second_root)

    for relative in (
        "maps/unmapped_province.tmx",
        "maps/unmapped_province.yaml",
        "gfx/tilesets/unmapped_province.tsx",
        "gfx/tilesets/unmapped_province.png",
        "mod.yaml",
        "foundry-admission.json",
    ):
        first_bytes = (first_root / relative).read_bytes()
        second_bytes = (second_root / relative).read_bytes()
        assert (
            hashlib.sha256(first_bytes).digest()
            == hashlib.sha256(second_bytes).digest()
        )
    assert first["fingerprint"] == second["fingerprint"]
