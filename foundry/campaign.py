# SPDX-License-Identifier: GPL-3.0-or-later
"""Synthesize a campaign from proven ecology and semantic region atoms.

This module does not author a quest in sequence.  It enumerates whole campaign
organisms, rejects ones that violate structural constraints, and preserves the
lowest-cost admitted arrangement as a proof-carrying lock.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


def _fingerprint(document: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _validate_fingerprint(document: dict[str, Any], label: str) -> None:
    body = copy.deepcopy(document)
    expected = body.pop("fingerprint", None)
    if expected != _fingerprint(body):
        raise RuntimeError(f"{label} fingerprint is invalid.")


def _battle_witness(candidate: dict[str, Any], winner: str) -> int:
    outcomes = [
        outcome
        for outcome in candidate["outcomes"]
        if outcome["winner"] == winner
    ]
    if not outcomes:
        raise ValueError(
            f"{candidate['monster']} level {candidate['level']} lacks a "
            f"{winner} witness."
        )
    return int(min(outcomes, key=lambda outcome: outcome["seed"])["seed"])


def _region_contract(
    atom: dict[str, Any],
    guardian: dict[str, Any],
    entry_state: str,
    final: bool,
) -> dict[str, Any]:
    slug = str(atom["slug"])
    open_state = f"{slug}_open"
    complete_state = "archive_restored" if final else f"{slug}_attuned"
    return {
        **copy.deepcopy(atom),
        "entry_state": entry_state,
        "open_state": open_state,
        "complete_state": complete_state,
        "defeat_action": f"defeat_{slug}_sentinel",
        "recover_action": f"recover_{slug}_sigil",
        "ecology": {
            "actor": atom["actor"],
            "selected": {
                "actor": atom["actor"],
                "monster": guardian["monster"],
                "level": int(guardian["level"]),
                "player_win_rate": guardian["player_win_rate"],
                "mean_turns": guardian["mean_turns"],
                "win_seed": _battle_witness(guardian, "player"),
                "loss_seed": _battle_witness(guardian, "opponent"),
            },
        },
    }


def synthesize(
    spec: dict[str, Any], ecology_lock: dict[str, Any]
) -> dict[str, Any]:
    """Search campaign-level arrangements and return a canonical certificate."""
    _validate_fingerprint(ecology_lock, "Ecology lock")
    atoms = copy.deepcopy(spec["campaign"]["region_atoms"])
    admitted_guardians = [
        candidate
        for candidate in ecology_lock["candidates"]
        if candidate.get("admitted")
    ]
    if len(admitted_guardians) < len(atoms):
        raise RuntimeError(
            "Campaign synthesis needs at least one admitted guardian per region."
        )

    candidates_examined = 0
    rejected: Counter[str] = Counter()
    admitted: list[tuple[float, list[dict[str, Any]]]] = []
    maximum_deviation = float(
        spec["campaign"]["admission"]["maximum_guardian_turn_deviation"]
    )
    for assignment in itertools.permutations(admitted_guardians, len(atoms)):
        candidates_examined += 1
        identities = {
            (candidate["monster"], int(candidate["level"]))
            for candidate in assignment
        }
        if len(identities) != len(atoms):
            rejected["guardian_identity_reused"] += 1
            continue
        roles = {atom["narrative_role"] for atom in atoms}
        if len(roles) != len(atoms):
            rejected["narrative_role_reused"] += 1
            continue
        deviations = [
            abs(
                float(atom["target_mean_turns"])
                - float(guardian["mean_turns"])
            )
            for atom, guardian in zip(atoms, assignment)
        ]
        if any(deviation > maximum_deviation for deviation in deviations):
            rejected["role_curve_outside_tolerance"] += 1
            continue

        regions: list[dict[str, Any]] = []
        state = "chartered"
        for index, (atom, guardian) in enumerate(zip(atoms, assignment)):
            region = _region_contract(
                atom, guardian, state, index == len(atoms) - 1
            )
            regions.append(region)
            state = region["complete_state"]
        cost = round(sum(deviations), 6)
        admitted.append((cost, regions))

    if not admitted:
        raise RuntimeError(f"No campaign organism survived: {dict(rejected)}")
    cost, regions = min(
        admitted,
        key=lambda item: (
            item[0],
            [
                (
                    region["ecology"]["selected"]["monster"],
                    region["ecology"]["selected"]["level"],
                )
                for region in item[1]
            ],
        ),
    )

    transitions: list[list[str]] = [
        ["arrival", "speak_to_archivist", "chartered"]
    ]
    for region in regions:
        transitions.extend(
            [
                [
                    region["entry_state"],
                    region["defeat_action"],
                    region["open_state"],
                ],
                [
                    region["open_state"],
                    region["recover_action"],
                    region["complete_state"],
                ],
            ]
        )
    transitions.extend(
        [
            ["archive_restored", "win_cartographers_duel", "trial_won"],
            ["trial_won", "report_to_archivist", "province_mapped"],
        ]
    )
    state = "arrival"
    witness: list[str] = []
    for source, action, target in transitions:
        if source != state:
            break
        witness.append(action)
        state = target

    selected = {
        "regions": regions,
        "narrative_automaton": {
            "initial": "arrival",
            "terminal": "province_mapped",
            "transitions": transitions,
        },
        "duel_source_state": "archive_restored",
    }
    proofs = [
        {
            "id": "campaign-population-was-enumerated",
            "passed": candidates_examined > 1,
            "detail": {
                "examined": candidates_examined,
                "admitted": len(admitted),
                "rejected": dict(sorted(rejected.items())),
            },
        },
        {
            "id": "campaign-guardians-are-unique",
            "passed": len(
                {
                    (
                        region["ecology"]["selected"]["monster"],
                        region["ecology"]["selected"]["level"],
                    )
                    for region in regions
                }
            )
            == len(regions),
            "detail": [
                region["ecology"]["selected"]["monster"]
                for region in regions
            ],
        },
        {
            "id": "campaign-roles-are-distinct",
            "passed": len({region["narrative_role"] for region in regions})
            == len(regions),
            "detail": [region["narrative_role"] for region in regions],
        },
        {
            "id": "campaign-quest-has-terminal-witness",
            "passed": state == "province_mapped",
            "detail": witness,
        },
        {
            "id": "every-guardian-has-win-and-loss-witnesses",
            "passed": all(
                region["ecology"]["selected"]["win_seed"]
                != region["ecology"]["selected"]["loss_seed"]
                for region in regions
            ),
            "detail": [
                {
                    "region": region["slug"],
                    "win": region["ecology"]["selected"]["win_seed"],
                    "loss": region["ecology"]["selected"]["loss_seed"],
                }
                for region in regions
            ],
        },
    ]
    body = {
        "schema": "ai-native-campaign-selection/v1",
        "source_genome_sha256": _fingerprint(spec),
        "ecology_fingerprint": ecology_lock["fingerprint"],
        "population": {
            "candidates_examined": candidates_examined,
            "admitted": len(admitted),
            "selection_cost": cost,
        },
        "selected": selected,
        "proofs": proofs,
    }
    body["fingerprint"] = _fingerprint(body)
    return body


def run(root: Path) -> dict[str, Any]:
    root = root.resolve()
    spec_path = root / "foundry" / "worlds" / "unmapped_province.seed.yaml"
    ecology_path = (
        root / "foundry" / "worlds" / "echo_wilds.ecology.lock.json"
    )
    output = root / "foundry" / "worlds" / "campaign.lock.json"
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    ecology = json.loads(ecology_path.read_text(encoding="utf-8"))
    result = synthesize(spec, ecology)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {"output": output.as_posix(), **result}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Select a proof-carrying multi-region campaign organism."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(json.dumps(run(args.root), indent=2))


if __name__ == "__main__":
    main()
