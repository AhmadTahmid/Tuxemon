# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
from pathlib import Path
from typing import Any

from foundry.runtime import _boot
from foundry.town import compile_world

TRANSIENT_STATES = (
    "DialogState",
    "WaitForInputState",
    "LevelUpSummaryState",
)


def _dismiss_transient_states(client) -> None:
    for state_name in TRANSIENT_STATES:
        if state_name in client.active_state_names:
            client.remove_state_by_name(state_name)


def _stage(session) -> str | None:
    return session.player.game_variables.get("province_stage")


def _events_by_name(client) -> dict[str, Any]:
    events = [
        *client.map_manager.inits,
        *client.map_manager.events,
    ]
    return {event.name: event for event in events}


def _approach(client, session, target: tuple[int, int]) -> dict[str, Any]:
    from tuxemon.map.map import get_coords, get_direction

    player = session.player
    occupied = {
        npc.tile_pos
        for npc in client.npc_manager.npcs.values()
        if npc is not player
    }
    candidates = [
        cell
        for cell in get_coords(target, client.map_manager.map_size)
        if cell not in occupied
    ]
    routes = [
        (cell, client.pathfinder.pathfind(player.tile_pos, cell, player.facing))
        for cell in candidates
    ]
    reachable = [(cell, path) for cell, path in routes if path is not None]
    if not reachable:
        raise RuntimeError(f"No runtime path reaches interaction target {target}.")
    destination, path = min(reachable, key=lambda item: len(item[1]))
    start = player.tile_pos
    player.pathfind(destination)
    frames = 0
    while (player.moving or player.path) and frames < 4000:
        client.update(0.25)
        _dismiss_transient_states(client)
        frames += 1
    if player.tile_pos != destination:
        raise RuntimeError(
            f"Path execution stopped at {player.tile_pos}, not {destination}."
        )
    player.set_facing(get_direction(player.tile_pos, target))
    return {
        "from": list(start),
        "to": list(destination),
        "target": list(target),
        "path_steps": len(path),
        "runtime_frames": frames,
    }


def _position_for_event(client, session, event) -> dict[str, Any] | None:
    if event.behavs:
        behavior = event.behavs[0]
        if behavior.type == "talk":
            target = client.get_npc(behavior.args[0])
            if target is None:
                raise RuntimeError(f"Talk target {behavior.args[0]} is absent.")
            return _approach(client, session, target.tile_pos)
    if any(condition.type == "char_facing_tile" for condition in event.conds):
        return _approach(client, session, (event.box.x, event.box.y))
    return None


def _evaluate_event_conditions(client, event) -> list[dict[str, Any]]:
    from tuxemon.platform.const.intentions import constants
    from tuxemon.platform.events import PlayerInput

    client.input_cache.clear_frame_state()
    client.input_cache.handle_input_event(
        PlayerInput(constants["INTERACT"], value=1, hold_time=1)
    )
    behavior_conditions, _ = client.event_engine._get_behavior_expansion(event)
    conditions = [*event.conds, *behavior_conditions]
    evidence = [
        {
            "name": condition.name,
            "type": condition.type,
            "passed": client.event_engine.evaluator.evaluate(condition),
        }
        for condition in conditions
    ]
    client.input_cache.clear_frame_state()
    return evidence


def _run_event(
    client,
    session,
    event,
    *,
    battle_seed: int | None = None,
) -> dict[str, Any]:
    route = _position_for_event(client, session, event)
    conditions = _evaluate_event_conditions(client, event)
    if not all(item["passed"] for item in conditions):
        raise RuntimeError(
            f"Runtime conditions rejected event {event.name}: {conditions}"
        )
    if battle_seed is not None:
        random.seed(battle_seed)
    stage_before = _stage(session)
    client.event_engine.start_event(event)
    frames = 0
    maximum_turn = 0
    battle_seen = False
    player_was_human = session.player.is_player
    try:
        while event.id in client.event_engine.running_events and frames < 6000:
            if "CombatState" in client.active_state_names:
                battle_seen = True
                session.player.is_player = False
                maximum_turn = max(
                    maximum_turn,
                    client.combat_session.turn,
                )
            _dismiss_transient_states(client)
            client.update(0.25)
            frames += 1
    finally:
        session.player.is_player = player_was_human
    if frames >= 6000:
        raise RuntimeError(f"Event {event.name} failed to terminate.")
    _dismiss_transient_states(client)
    client.update(0.25)
    return {
        "event": event.name,
        "stage_before": stage_before,
        "stage_after": _stage(session),
        "conditions": conditions,
        "route": route,
        "runtime_frames": frames,
        "battle_seen": battle_seen,
        "battle_turns": maximum_turn,
    }


def _pump_until_stage(client, session, expected: str) -> int:
    frames = 0
    while _stage(session) != expected and frames < 1000:
        _dismiss_transient_states(client)
        client.update(0.25)
        frames += 1
    if _stage(session) != expected:
        outcome = session.player.battle_handler.get_last_battle_outcome(
            "npc_test"
        )
        raise RuntimeError(
            f"Quest stalled at {_stage(session)!r}; expected {expected!r}; "
            f"last battle outcome was {outcome!r}."
        )
    return frames


def run(root: Path) -> dict[str, Any]:
    root = root.resolve()
    build = compile_world(root)
    admission = json.loads(
        Path(build["certificate"]).read_text(encoding="utf-8")
    )
    event_bindings = {
        item["transition"]: item["event"]
        for item in admission["witnesses"]["quest_event_bindings"]
    }
    previous_logging_threshold = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    client, _, session = _boot(root, visible=False)
    transcript: list[dict[str, Any]] = []
    execution_steps: list[dict[str, Any]] = []
    try:
        for _ in range(20):
            client.update(0.05)
        events = _events_by_name(client)

        charter = _run_event(
            client,
            session,
            events[event_bindings["speak_to_archivist"]],
        )
        charter["transition"] = "speak_to_archivist"
        transcript.append(charter)
        execution_steps.append(charter)
        shard = _run_event(
            client,
            session,
            events[event_bindings["recover_echo_shard"]],
        )
        shard["transition"] = "recover_echo_shard"
        transcript.append(shard)
        execution_steps.append(shard)

        duel_event = next(
            event
            for event in events.values()
            if any(action.type == "start_battle" for action in event.acts)
        )
        recovery_event = events[
            admission["witnesses"]["battle_loss_recovery_event"]
        ]
        battle_attempts = []
        recovery_steps = []
        duel = None
        for attempt in range(12):
            battle = _run_event(
                client,
                session,
                duel_event,
                battle_seed=1_040_001 + attempt,
            )
            battle["kind"] = "battle_attempt"
            battle["outcome"] = (
                session.player.battle_handler.get_last_battle_outcome(
                    "npc_test"
                )
            )
            battle_attempts.append(battle)
            execution_steps.append(battle)
            if battle["outcome"] == "won":
                duel = battle
                break
            recovery = _run_event(client, session, recovery_event)
            recovery["kind"] = "battle_loss_recovery"
            recovery_steps.append(recovery)
            execution_steps.append(recovery)
        if duel is None:
            raise RuntimeError("The retry policy exhausted twelve duel attempts.")
        duel["transition"] = "win_cartographers_duel"
        duel["post_battle_frames"] = _pump_until_stage(
            client, session, "trial_won"
        )
        duel["stage_after"] = _stage(session)
        duel["attempts"] = len(battle_attempts)
        transcript.append(duel)

        completion = _run_event(
            client,
            session,
            events[event_bindings["report_to_archivist"]],
        )
        completion["transition"] = "report_to_archivist"
        transcript.append(completion)
        execution_steps.append(completion)
        final_stage = _stage(session)
        player_outcome = session.player.battle_handler.get_last_battle_outcome(
            "npc_test"
        )
    finally:
        logging.disable(previous_logging_threshold)
        import pygame

        pygame.quit()

    expected_stages = [
        "chartered",
        "shard_recovered",
        "trial_won",
        "province_mapped",
    ]
    observed_stages = [entry["stage_after"] for entry in transcript]
    proofs = [
        {
            "id": "compiled-quest-transitions-in-real-runtime",
            "passed": observed_stages == expected_stages,
            "detail": observed_stages,
        },
        {
            "id": "all-interaction-conditions-evaluate-true",
            "passed": all(
                all(condition["passed"] for condition in entry["conditions"])
                for entry in execution_steps
            ),
            "detail": [entry["event"] for entry in execution_steps],
        },
        {
            "id": "actual-pathfinder-executes-every-route",
            "passed": all(
                entry["route"] is not None for entry in execution_steps
            ),
            "detail": [entry["route"] for entry in execution_steps],
        },
        {
            "id": "battle-loss-recovery-loop-is-executable",
            "passed": bool(recovery_steps)
            and len(recovery_steps)
            == sum(
                entry["outcome"] == "lost" for entry in battle_attempts
            ),
            "detail": {
                "battle_attempts": len(battle_attempts),
                "recoveries": len(recovery_steps),
            },
        },
        {
            "id": "campaign-battle-is-won-and-terminates",
            "passed": player_outcome == "won"
            and any(entry["battle_seen"] for entry in transcript),
            "detail": {
                "outcome": player_outcome,
                "turns": max(entry["battle_turns"] for entry in transcript),
            },
        },
        {
            "id": "terminal-quest-state-is-reached",
            "passed": final_stage == admission["quest"]["terminal"],
            "detail": final_stage,
        },
    ]
    body = {
        "schema": "ai-native-tuxemon-playthrough/v1",
        "world_fingerprint": build["fingerprint"],
        "quest_witness": admission["witnesses"]["quest"],
        "transcript": transcript,
        "execution_steps": execution_steps,
        "proofs": proofs,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    body["fingerprint"] = hashlib.sha256(canonical.encode()).hexdigest()
    output = root / "foundry" / "artifacts" / "playthrough.generated.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if not all(proof["passed"] for proof in proofs):
        raise RuntimeError(
            f"Playthrough admission failed; inspect {output.as_posix()}"
        )
    return {"output": output.as_posix(), **body}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Execute the compiled quest as a real-engine witness."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    result = run(args.root)
    summary = {
        "output": result["output"],
        "schema": result["schema"],
        "world_fingerprint": result["world_fingerprint"],
        "quest_witness": result["quest_witness"],
        "transcript": [
            {
                key: entry[key]
                for key in (
                    "event",
                    "stage_after",
                    "outcome",
                    "attempts",
                )
                if key in entry
            }
            for entry in result["transcript"]
        ],
        "proofs": result["proofs"],
        "fingerprint": result["fingerprint"],
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
