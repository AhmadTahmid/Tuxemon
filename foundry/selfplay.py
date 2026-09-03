# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from foundry.runtime import _boot
from foundry.town import compile_world


def _dismiss_non_decisions(client) -> None:
    for state_name in ("WaitForInputState", "LevelUpSummaryState"):
        if state_name in client.active_state_names:
            client.remove_state_by_name(state_name)


def _run_battle(
    client,
    session,
    player_monster: str,
    player_level: int,
    opponent_monster: str,
    opponent_level: int,
    seed: int,
) -> dict[str, Any]:
    random.seed(seed)
    player = session.player
    opponent = client.get_npc("npc_test")
    player.is_player = True
    player.party.clear_party()
    opponent.party.clear_party()
    client.event_engine.execute_action(
        "add_monster", [player_monster, player_level]
    )
    client.event_engine.execute_action(
        "add_monster",
        [opponent_monster, opponent_level, opponent.slug],
    )
    client.event_engine.execute_action(
        "start_battle", ["player", opponent.slug], skip=True
    )
    if "CombatState" not in client.active_state_names:
        raise RuntimeError(
            "The actual Tuxemon combat state rejected the trial."
        )

    # CombatSession decides human/AI control dynamically. Toggling only this
    # runtime role lets Tuxemon's own AI choose both sides without forking or
    # approximating its damage/status implementation.
    player.is_player = False
    frames = 0
    maximum_turn = 0
    while "CombatState" in client.active_state_names and frames < 5000:
        client.update(0.25)
        _dismiss_non_decisions(client)
        maximum_turn = max(maximum_turn, client.combat_session.turn)
        frames += 1
    player.is_player = True
    if frames >= 5000:
        raise RuntimeError("Combat failed to terminate within 5000 frames.")
    winner = "player" if not player.party.is_fainted else "opponent"
    return {
        "seed": seed,
        "winner": winner,
        "turns": maximum_turn,
        "frames": frames,
        "player_hp": [monster.current_hp for monster in player.monsters],
        "opponent_hp": [monster.current_hp for monster in opponent.monsters],
    }


def run(
    root: Path,
    trials_per_level: int | None = None,
    opponent_levels: tuple[int, ...] | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    spec_path = root / "foundry" / "worlds" / "unmapped_province.seed.yaml"
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    actors = spec["actors"]
    contract = spec["admission"]["combat"]
    if trials_per_level is None:
        trials_per_level = int(contract["trials_per_level"])
    if opponent_levels is None:
        opponent_levels = tuple(
            int(level) for level in contract["opponent_levels"]
        )
    if trials_per_level < 1:
        raise ValueError("trials_per_level must be positive")
    if not opponent_levels:
        raise ValueError("opponent_levels must not be empty")
    selected_level = int(actors["duelist_level"])
    if selected_level not in opponent_levels:
        raise ValueError(
            "The selected duelist level must occur in the evaluated cohorts."
        )
    build = compile_world(root)
    previous_logging_threshold = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    client, _, session = _boot(root, visible=False)
    try:
        for _ in range(20):
            client.update(0.05)
        client.event_engine.suspend()

        cohorts = []
        all_trials = []
        seed_origin = 990_001
        for level in opponent_levels:
            trials = [
                _run_battle(
                    client,
                    session,
                    str(actors["starter_monster"]),
                    int(actors["starter_level"]),
                    str(actors["duelist_monster"]),
                    level,
                    seed_origin + level * 10_000 + index,
                )
                for index in range(trials_per_level)
            ]
            all_trials.extend(trials)
            wins = Counter(trial["winner"] for trial in trials)
            turns = [trial["turns"] for trial in trials]
            cohorts.append(
                {
                    "opponent_level": level,
                    "trials": len(trials),
                    "player_wins": wins["player"],
                    "opponent_wins": wins["opponent"],
                    "player_win_rate": wins["player"] / len(trials),
                    "mean_turns": round(statistics.fmean(turns), 3),
                    "min_turns": min(turns),
                    "max_turns": max(turns),
                }
            )
    finally:
        logging.disable(previous_logging_threshold)
        import pygame

        pygame.quit()

    curve = [cohort["player_win_rate"] for cohort in cohorts]
    monotonic = all(left >= right for left, right in zip(curve, curve[1:]))
    selected = next(
        cohort
        for cohort in cohorts
        if cohort["opponent_level"] == selected_level
    )
    win_rate_low, win_rate_high = map(
        float, contract["target_player_win_rate"]
    )
    turn_low, turn_high = map(int, contract["target_turns"])
    proofs = [
        {
            "id": "all-self-play-battles-terminate",
            "passed": len(all_trials)
            == trials_per_level * len(opponent_levels),
            "detail": f"Completed {len(all_trials)} actual-engine battles.",
        },
        {
            "id": "difficulty-curve-is-monotonic",
            "passed": monotonic
            if contract["require_monotonic_difficulty"]
            else True,
            "detail": curve,
        },
        {
            "id": "selected-duel-win-rate-is-admitted",
            "passed": win_rate_low
            <= selected["player_win_rate"]
            <= win_rate_high,
            "detail": {
                "observed": selected["player_win_rate"],
                "required": [win_rate_low, win_rate_high],
            },
        },
        {
            "id": "selected-duel-duration-is-admitted",
            "passed": turn_low <= selected["min_turns"]
            and selected["max_turns"] <= turn_high,
            "detail": selected,
        },
    ]
    body = {
        "schema": "ai-native-tuxemon-self-play/v1",
        "world_fingerprint": build["fingerprint"],
        "policy": "Tuxemon built-in trainer AI controls both teams",
        "contract": contract,
        "selected_duel": {
            "player": {
                "monster": actors["starter_monster"],
                "level": actors["starter_level"],
            },
            "opponent": {
                "monster": actors["duelist_monster"],
                "level": selected_level,
            },
        },
        "cohorts": cohorts,
        "proofs": proofs,
        "trials": all_trials,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    body["fingerprint"] = hashlib.sha256(canonical.encode()).hexdigest()
    output = root / "foundry" / "artifacts" / "combat-selfplay.generated.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if not all(proof["passed"] for proof in proofs):
        raise RuntimeError(
            f"Combat admission failed; inspect {output.as_posix()}"
        )
    return {"output": output.as_posix(), **body}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run actual Tuxemon combat as deterministic AI self-play."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--trials", type=int)
    parser.add_argument(
        "--levels",
        type=lambda value: tuple(int(item) for item in value.split(",")),
        help="Comma-separated opponent levels; defaults to the world contract.",
    )
    args = parser.parse_args()
    result = run(args.root, args.trials, args.levels)
    summary = {
        key: value for key, value in result.items() if key != "trials"
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
