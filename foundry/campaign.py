# SPDX-License-Identifier: GPL-3.0-or-later
"""Synthesize a campaign from proven ecology and semantic region atoms.

This module does not author a quest in sequence.  It enumerates whole campaign
organisms, rejects ones that violate structural constraints, and preserves the
lowest-cost admitted arrangement as a proof-carrying lock.
"""
from __future__ import annotations

import argparse
import colorsys
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


def _guardian_payload(
    actor: str, guardian: dict[str, Any]
) -> dict[str, Any]:
    return {
        "actor": actor,
        "monster": guardian["monster"],
        "level": int(guardian["level"]),
        "player_win_rate": guardian["player_win_rate"],
        "mean_turns": guardian["mean_turns"],
        "win_seed": _battle_witness(guardian, "player"),
        "loss_seed": _battle_witness(guardian, "opponent"),
    }


def _synthesize_branch_phenotypes(
    spec: dict[str, Any], region: dict[str, Any]
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Select maximally distinct visual/spatial branch projections."""
    alignments = sorted(map(str, region["alignment_values"]))
    if len(alignments) != 2:
        raise ValueError("The current phenotype search requires two branches.")

    overlays = []
    for index in range(12):
        red, green, blue = colorsys.hsv_to_rgb(index / 12, 0.72, 1.0)
        channels = tuple(round(channel * 255) for channel in (red, green, blue))
        overlays.append((*channels, 44))

    quadrant_positions = {
        "northwest": (0, 0),
        "northeast": (1, 0),
        "southwest": (0, 1),
        "southeast": (1, 1),
    }
    landmarks = sorted(
        (
            str(item["role"]),
            quadrant_positions[str(item["quadrant"])],
        )
        for item in spec["intent"]["required_landmarks"]
    )
    organisms = []
    for overlay_pair in itertools.combinations(overlays, 2):
        color_distance = sum(
            (left - right) ** 2
            for left, right in zip(overlay_pair[0][:3], overlay_pair[1][:3])
        ) ** 0.5
        for anchor_pair in itertools.combinations(landmarks, 2):
            spatial_distance = sum(
                abs(left - right)
                for left, right in zip(anchor_pair[0][1], anchor_pair[1][1])
            )
            organisms.append(
                {
                    "overlays": overlay_pair,
                    "anchors": tuple(item[0] for item in anchor_pair),
                    "color_distance": round(color_distance, 3),
                    "spatial_distance": spatial_distance,
                    "score": round(color_distance + spatial_distance * 64, 3),
                }
            )
    selected = min(
        organisms,
        key=lambda organism: (
            -organism["score"],
            organism["overlays"],
            organism["anchors"],
        ),
    )
    phenotypes = {
        alignment: {
            "overlay": ":".join(map(str, selected["overlays"][index])),
            "anchor_role": selected["anchors"][index],
        }
        for index, alignment in enumerate(alignments)
    }
    population = {
        "candidates_examined": len(organisms),
        "selection_score": selected["score"],
        "color_distance": selected["color_distance"],
        "spatial_distance": selected["spatial_distance"],
    }
    return phenotypes, population


def _region_contract(
    atom: dict[str, Any],
    guardian: dict[str, Any] | None,
    entry_state: str,
    final: bool,
) -> dict[str, Any]:
    slug = str(atom["slug"])
    complete_state = "archive_restored" if final else f"{slug}_attuned"
    contract = {
        **copy.deepcopy(atom),
        "entry_state": entry_state,
        "complete_state": complete_state,
        "recover_action": f"recover_{slug}_sigil",
    }
    if atom["mechanic"] == "survey":
        contract.update(
            {
                "alignment_key": f"{slug}_alignment",
                "alignment_values": ["chorus", "silence"],
                "observation_keys": [
                    f"{slug}_origin_seen",
                    f"{slug}_horizon_seen",
                    f"{slug}_root_seen",
                ],
            }
        )
        return contract
    if guardian is None:
        raise ValueError(f"Combat region {slug} has no guardian.")
    contract.update(
        {
            "open_state": f"{slug}_open",
            "defeat_action": f"defeat_{slug}_sentinel",
            "ecology": {
                "actor": atom["actor"],
                "selected": _guardian_payload(atom["actor"], guardian),
            },
        }
    )
    return contract


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
    combat_atoms = [atom for atom in atoms if atom["mechanic"] == "combat"]
    if len(admitted_guardians) < len(combat_atoms):
        raise RuntimeError(
            "Campaign synthesis needs one admitted guardian per combat region."
        )

    candidates_examined = 0
    rejected: Counter[str] = Counter()
    admitted: list[tuple[float, list[dict[str, Any]]]] = []
    maximum_deviation = float(
        spec["campaign"]["admission"]["maximum_guardian_turn_deviation"]
    )
    for assignment in itertools.permutations(
        admitted_guardians, len(combat_atoms)
    ):
        candidates_examined += 1
        identities = {
            (candidate["monster"], int(candidate["level"]))
            for candidate in assignment
        }
        if len(identities) != len(combat_atoms):
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
            for atom, guardian in zip(combat_atoms, assignment)
        ]
        if any(deviation > maximum_deviation for deviation in deviations):
            rejected["role_curve_outside_tolerance"] += 1
            continue

        regions: list[dict[str, Any]] = []
        state = "chartered"
        guardian_iterator = iter(assignment)
        for index, atom in enumerate(atoms):
            guardian = (
                next(guardian_iterator)
                if atom["mechanic"] == "combat"
                else None
            )
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
                    region["mechanic"],
                    region.get("ecology", {})
                    .get("selected", {})
                    .get("monster", ""),
                )
                for region in item[1]
            ],
        ),
    )
    for region in regions:
        if region["mechanic"] == "survey":
            phenotypes, population = _synthesize_branch_phenotypes(
                spec, region
            )
            region["phenotypes"] = phenotypes
            region["phenotype_population"] = population
    preceding_survey: dict[str, Any] | None = None
    guardians_used_before: set[tuple[str, int]] = set()
    for region in regions:
        if region["mechanic"] == "survey":
            preceding_survey = region
            continue
        base = region["ecology"]["selected"]
        base_identity = (base["monster"], int(base["level"]))
        if preceding_survey:
            alternatives = [
                guardian
                for guardian in admitted_guardians
                if (guardian["monster"], int(guardian["level"]))
                not in guardians_used_before | {base_identity}
            ]
            if not alternatives:
                raise RuntimeError(
                    f"No alternate guardian survives for {region['slug']}."
                )
            alternate = max(
                alternatives,
                key=lambda guardian: (
                    abs(float(guardian["mean_turns"]) - base["mean_turns"]),
                    guardian["monster"],
                    int(guardian["level"]),
                ),
            )
            alignments = sorted(preceding_survey["phenotypes"])
            region["conditional_ecologies"] = {
                "alignment_key": preceding_survey["alignment_key"],
                "selected": {
                    alignments[0]: copy.deepcopy(base),
                    alignments[1]: _guardian_payload(
                        region["actor"], alternate
                    ),
                },
            }
        guardians_used_before.add(base_identity)

    transitions: list[list[str]] = [
        ["arrival", "speak_to_archivist", "chartered"]
    ]
    for region in regions:
        if region["mechanic"] == "combat":
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
        else:
            transitions.append(
                [
                    region["entry_state"],
                    region["recover_action"],
                    region["complete_state"],
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
                    if region["mechanic"] == "combat"
                }
            )
            == len(combat_atoms),
            "detail": [
                region["ecology"]["selected"]["monster"]
                for region in regions
                if region["mechanic"] == "combat"
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
                if region["mechanic"] == "combat"
            ),
            "detail": [
                {
                    "region": region["slug"],
                    "win": region["ecology"]["selected"]["win_seed"],
                    "loss": region["ecology"]["selected"]["loss_seed"],
                }
                for region in regions
                if region["mechanic"] == "combat"
            ],
        },
        {
            "id": "campaign-mechanics-are-not-uniform",
            "passed": len({region["mechanic"] for region in regions}) > 1,
            "detail": [region["mechanic"] for region in regions],
        },
        {
            "id": "branch-phenotype-populations-were-enumerated",
            "passed": all(
                region["phenotype_population"]["candidates_examined"] > 1
                for region in regions
                if region["mechanic"] == "survey"
            ),
            "detail": {
                region["slug"]: region["phenotype_population"]
                for region in regions
                if region["mechanic"] == "survey"
            },
        },
        {
            "id": "branch-phenotypes-are-observably-distinct",
            "passed": all(
                len(
                    {
                        phenotype["overlay"]
                        for phenotype in region["phenotypes"].values()
                    }
                )
                == len(region["phenotypes"])
                and len(
                    {
                        phenotype["anchor_role"]
                        for phenotype in region["phenotypes"].values()
                    }
                )
                == len(region["phenotypes"])
                for region in regions
                if region["mechanic"] == "survey"
            ),
            "detail": {
                region["slug"]: region["phenotypes"]
                for region in regions
                if region["mechanic"] == "survey"
            },
        },
        {
            "id": "branches-select-distinct-downstream-combat-ecologies",
            "passed": all(
                len(
                    {
                        (ecology["monster"], ecology["level"])
                        for ecology in region["conditional_ecologies"][
                            "selected"
                        ].values()
                    }
                )
                == len(region["conditional_ecologies"]["selected"])
                for region in regions
                if "conditional_ecologies" in region
            ),
            "detail": {
                region["slug"]: region["conditional_ecologies"]
                for region in regions
                if "conditional_ecologies" in region
            },
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
