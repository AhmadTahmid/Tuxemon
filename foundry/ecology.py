# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

from foundry.runtime import _boot
from foundry.selfplay import _run_battle
from foundry.town import compile_world


def _stable_rank(seed: int, value: str) -> str:
    return hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()


def _boot_tournament(root: Path):
    client, _, session = _boot(root, visible=False)
    for _ in range(20):
        client.update(0.05)
        for state_name in ("DialogState", "WaitForInputState"):
            if state_name in client.active_state_names:
                client.remove_state_by_name(state_name)
    client.event_engine.suspend()
    return client, session


def derive_species(
    root: Path, spec: dict[str, Any]
) -> tuple[list[dict[str, Any]], int]:
    ecology = spec["expedition"]["ecology"]
    habitat = set(map(str, ecology["habitat"]))
    required_stage = str(ecology["stage"])
    excluded = {
        str(spec["actors"]["starter_monster"]),
        str(spec["actors"]["duelist_monster"]),
    }
    records: list[dict[str, Any]] = []
    for path in sorted((root / "mods" / "tuxemon" / "db" / "monster").glob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            continue
        slug = document.get("slug")
        terrains = set(map(str, document.get("terrains", [])))
        types = list(map(str, document.get("types", [])))
        if (
            not slug
            or slug in excluded
            or document.get("stage") != required_stage
            or not terrains & habitat
            or not types
        ):
            continue
        records.append(
            {
                "slug": str(slug),
                "primary_type": types[0],
                "habitat_overlap": len(terrains & habitat),
            }
        )

    seed = int(spec["identity"]["seed"])
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[record["primary_type"]].append(record)
    for group in groups.values():
        group.sort(
            key=lambda item: (
                -item["habitat_overlap"],
                _stable_rank(seed, item["slug"]),
            )
        )

    type_order = sorted(groups, key=lambda item: _stable_rank(seed, item))
    budget = int(ecology["species_budget"])
    selected: list[dict[str, Any]] = []
    depth = 0
    while len(selected) < budget:
        added = False
        for element_type in type_order:
            group = groups[element_type]
            if depth < len(group):
                selected.append(group[depth])
                added = True
                if len(selected) == budget:
                    break
        if not added:
            break
        depth += 1
    return selected, len(records)


def _evaluate_candidate(
    client,
    session,
    spec: dict[str, Any],
    monster: str,
    level: int,
    trials: int,
    seed_origin: int,
) -> dict[str, Any]:
    actors = spec["actors"]
    outcomes = [
        _run_battle(
            client,
            session,
            str(actors["starter_monster"]),
            int(actors["starter_level"]),
            monster,
            level,
            seed_origin + index,
        )
        for index in range(trials)
    ]
    wins = Counter(outcome["winner"] for outcome in outcomes)
    turns = [int(outcome["turns"]) for outcome in outcomes]
    return {
        "monster": monster,
        "level": level,
        "trials": trials,
        "player_wins": wins["player"],
        "opponent_wins": wins["opponent"],
        "player_win_rate": wins["player"] / trials,
        "mean_turns": round(statistics.fmean(turns), 3),
        "min_turns": min(turns),
        "max_turns": max(turns),
        "outcomes": outcomes,
    }


def run(root: Path) -> dict[str, Any]:
    root = root.resolve()
    spec_path = root / "foundry" / "worlds" / "unmapped_province.seed.yaml"
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    ecology = spec["expedition"]["ecology"]
    species, eligible_count = derive_species(root, spec)
    if not species:
        raise RuntimeError("The semantic habitat query found no candidates.")

    trials = int(ecology["trials_per_candidate"])
    levels = list(map(int, ecology["levels"]))
    rejection_path = (
        root
        / "foundry"
        / "artifacts"
        / "ecology-rejection.generated.json"
    )
    progress_path = (
        root / "foundry" / "artifacts" / "ecology-progress.generated.json"
    )
    cached_candidates: dict[tuple[str, int], dict[str, Any]] = {}
    for cache_path in (rejection_path, progress_path):
        if cache_path.is_file():
            previous = json.loads(cache_path.read_text(encoding="utf-8"))
            cached_candidates.update(
                {
                    (candidate["monster"], int(candidate["level"])): candidate
                    for candidate in previous.get("candidates", [])
                    if int(candidate.get("trials", -1)) == trials
                }
            )
    previous_logging_threshold = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    client, session = _boot_tournament(root)
    try:
        candidates = []
        for species_index, record in enumerate(species):
            for level_index, level in enumerate(levels):
                seed_origin = (
                    2_000_000
                    + species_index * 100_000
                    + level_index * 10_000
                )
                cached = cached_candidates.get((record["slug"], level))
                expected_seeds = {
                    seed_origin + index for index in range(trials)
                }
                cached_outcomes = cached.get("outcomes", []) if cached else []
                reusable = bool(cached) and (
                    {
                        outcome["seed"] for outcome in cached_outcomes
                    }
                    == expected_seeds
                    or (
                        cached.get("seed_origin") == seed_origin
                        and bool(cached.get("error"))
                    )
                )
                if reusable:
                    cached["seed_origin"] = seed_origin
                    if cached.get("error") and ":" not in cached["error"]:
                        cached["error"] = f"RuntimeError: {cached['error']}"
                    candidates.append(cached)
                else:
                    try:
                        candidate = _evaluate_candidate(
                            client,
                            session,
                            spec,
                            record["slug"],
                            level,
                            trials,
                            seed_origin,
                        )
                        candidate["seed_origin"] = seed_origin
                    except Exception as error:
                        candidate = {
                            "monster": record["slug"],
                            "level": level,
                            "trials": trials,
                            "seed_origin": seed_origin,
                            "outcomes": [],
                            "error": f"{type(error).__name__}: {error}",
                        }
                        while "CombatState" in client.active_state_names:
                            client.remove_state_by_name("CombatState")
                        session.player.is_player = True
                        import pygame

                        pygame.quit()
                        client, session = _boot_tournament(root)
                    candidates.append(candidate)
                progress_path.parent.mkdir(parents=True, exist_ok=True)
                progress_path.write_text(
                    json.dumps(
                        {
                            "schema": "ai-native-ecology-progress/v1",
                            "candidates": candidates,
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
    finally:
        logging.disable(previous_logging_threshold)
        import pygame

        pygame.quit()

    win_low, win_high = map(float, ecology["target_player_win_rate"])
    turn_low, turn_high = map(int, ecology["target_turns"])
    target_win = (win_low + win_high) / 2
    target_turns = (turn_low + turn_high) / 2
    for candidate in candidates:
        if candidate.get("error"):
            candidate["admitted"] = False
            candidate["fitness"] = None
            continue
        candidate["admitted"] = (
            win_low <= candidate["player_win_rate"] <= win_high
            and turn_low <= candidate["min_turns"]
            and candidate["max_turns"] <= turn_high
            and candidate["player_wins"] > 0
            and candidate["opponent_wins"] > 0
        )
        candidate["fitness"] = round(
            abs(candidate["player_win_rate"] - target_win) * 100
            + abs(candidate["mean_turns"] - target_turns) * 3,
            4,
        )
    admitted = [candidate for candidate in candidates if candidate["admitted"]]
    if not admitted:
        rejection = {
            "schema": "ai-native-ecology-rejection/v1",
            "contract": {
                "target_player_win_rate": [win_low, win_high],
                "target_turns": [turn_low, turn_high],
            },
            "candidates": candidates,
            "counterexample": "no_candidate_satisfies_all_constraints",
        }
        rejection_path.parent.mkdir(parents=True, exist_ok=True)
        rejection_path.write_text(
            json.dumps(rejection, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raise RuntimeError(
            "Actual-engine ecology tournament admitted no sentinel; inspect "
            f"{rejection_path.as_posix()}."
        )
    champion = min(
        admitted,
        key=lambda item: (item["fitness"], item["monster"], item["level"]),
    )
    win_seed = next(
        outcome["seed"]
        for outcome in champion["outcomes"]
        if outcome["winner"] == "player"
    )
    loss_seed = next(
        outcome["seed"]
        for outcome in champion["outcomes"]
        if outcome["winner"] == "opponent"
    )
    selected = {
        "actor": str(ecology["actor"]),
        "monster": champion["monster"],
        "level": champion["level"],
        "player_win_rate": champion["player_win_rate"],
        "mean_turns": champion["mean_turns"],
        "win_seed": win_seed,
        "loss_seed": loss_seed,
    }
    evaluated_types = {record["primary_type"] for record in species}
    proofs = [
        {
            "id": "habitat-query-produces-candidates",
            "passed": eligible_count >= len(species) > 0,
            "detail": {
                "eligible": eligible_count,
                "sampled": len(species),
            },
        },
        {
            "id": "candidate-pool-is-type-diverse",
            "passed": len(evaluated_types) >= 3,
            "detail": sorted(evaluated_types),
        },
        {
            "id": "candidate-failures-are-isolated-and-retained",
            "passed": all(
                len(candidate["outcomes"]) == trials
                or bool(candidate.get("error"))
                for candidate in candidates
            ),
            "detail": {
                "completed_trials": sum(
                    len(item["outcomes"]) for item in candidates
                ),
                "isolated_failures": [
                    {
                        "monster": item["monster"],
                        "level": item["level"],
                        "error": item["error"],
                    }
                    for item in candidates
                    if item.get("error")
                ],
            },
        },
        {
            "id": "ecology-has-admitted-survivor",
            "passed": bool(admitted),
            "detail": len(admitted),
        },
        {
            "id": "selected-sentinel-has-win-and-loss-witnesses",
            "passed": bool(win_seed) and bool(loss_seed),
            "detail": {"win_seed": win_seed, "loss_seed": loss_seed},
        },
    ]
    body: dict[str, Any] = {
        "schema": "ai-native-ecology-selection/v1",
        "source_genome_sha256": hashlib.sha256(spec_path.read_bytes()).hexdigest(),
        "derivation": {
            "habitat": ecology["habitat"],
            "stage": ecology["stage"],
            "eligible_species": eligible_count,
            "sampled_species": species,
            "levels": levels,
            "trials_per_candidate": trials,
        },
        "contract": {
            "target_player_win_rate": [win_low, win_high],
            "target_turns": [turn_low, turn_high],
        },
        "selected": selected,
        "candidates": candidates,
        "proofs": proofs,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    body["fingerprint"] = hashlib.sha256(canonical.encode()).hexdigest()
    output = root / "foundry" / "worlds" / "echo_wilds.ecology.lock.json"
    output.write_text(
        json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    build = compile_world(root)
    return {
        "output": output.as_posix(),
        "world_fingerprint": build["fingerprint"],
        **body,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Select a region ecology using actual-engine self-play."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    result = run(args.root)
    print(
        json.dumps(
            {
                "output": result["output"],
                "schema": result["schema"],
                "world_fingerprint": result["world_fingerprint"],
                "selected": result["selected"],
                "proofs": result["proofs"],
                "fingerprint": result["fingerprint"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
