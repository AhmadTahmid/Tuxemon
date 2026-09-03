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


def _pump_until_map(client, expected: str) -> int:
    frames = 0
    while client.get_map_name() != expected and frames < 1000:
        _dismiss_transient_states(client)
        client.update(0.05)
        frames += 1
    if client.get_map_name() != expected:
        raise RuntimeError(
            f"Map transition stalled at {client.get_map_name()!r}; "
            f"expected {expected!r}."
        )
    for _ in range(20):
        _dismiss_transient_states(client)
        client.update(0.05)
    return frames


def _execute_combat_region(
    client,
    session,
    region: dict[str, Any],
    region_index: int,
    admission: dict[str, Any],
    execution_steps: list[dict[str, Any]],
    visited_regions: list[str],
) -> dict[str, Any]:
    slug = region["slug"]
    expected_map = f"{slug}.tmx"
    events = _events_by_name(client)
    ecology = region["ecology"]
    sentinel_actor = ecology["actor"]
    sentinel_event = events[region["sentinel_event"]]
    attempts: list[dict[str, Any]] = []
    recoveries: list[dict[str, Any]] = []
    winner = None
    battle_seeds = [
        int(ecology["loss_seed"]),
        *(int(ecology["win_seed"]) + offset for offset in range(16)),
    ]
    for attempt, battle_seed in enumerate(battle_seeds):
        if region_index == 0 and attempt == 0:
            session.player.monsters[0].current_hp = 1
        battle = _run_event(
            client, session, sentinel_event, battle_seed=battle_seed
        )
        battle["kind"] = "sentinel_battle_attempt"
        battle["region"] = slug
        if region_index == 0 and attempt == 0:
            battle["fault_injection"] = "player_party_health=1"
        battle["outcome"] = (
            session.player.battle_handler.get_last_battle_outcome(
                sentinel_actor
            )
        )
        attempts.append(battle)
        execution_steps.append(battle)
        if battle["outcome"] == "won":
            winner = battle
            break

        retreat = _run_event(
            client, session, events[region["return_event"]]
        )
        retreat["kind"] = "sentinel_loss_retreat"
        retreat["region"] = slug
        retreat["transition_frames"] = _pump_until_map(
            client, "unmapped_province.tmx"
        )
        retreat["map_after"] = client.get_map_name()
        execution_steps.append(retreat)
        visited_regions.append(retreat["map_after"])

        events = _events_by_name(client)
        recovery = _run_event(
            client,
            session,
            events[admission["witnesses"]["battle_loss_recovery_event"]],
        )
        recovery["kind"] = "sentinel_loss_recovery"
        recovery["region"] = slug
        recoveries.append(recovery)
        execution_steps.append(recovery)

        reentry = _run_event(
            client, session, events[region["entry_event"]]
        )
        reentry["kind"] = "sentinel_retry_transition"
        reentry["region"] = slug
        reentry["transition_frames"] = _pump_until_map(client, expected_map)
        reentry["map_after"] = client.get_map_name()
        execution_steps.append(reentry)
        visited_regions.append(reentry["map_after"])
        events = _events_by_name(client)
        sentinel_event = events[region["sentinel_event"]]
    if winner is None:
        raise RuntimeError(
            f"The selected sentinel for {slug} has no winning witness."
        )
    winner["transition"] = region["defeat_action"]
    winner["post_battle_frames"] = _pump_until_stage(
        client, session, region["open_state"]
    )
    winner["stage_after"] = _stage(session)
    winner["attempts"] = len(attempts)
    events = _events_by_name(client)
    sigil = _run_event(
        client,
        session,
        events[
            next(
                binding["event"]
                for binding in admission["witnesses"][
                    "quest_event_bindings"
                ]
                if binding["transition"] == region["recover_action"]
            )
        ],
    )
    sigil["transition"] = region["recover_action"]
    sigil["region"] = slug
    execution_steps.append(sigil)
    return {
        "slug": slug,
        "mechanic": "combat",
        "ecology": ecology,
        "attempts": attempts,
        "recoveries": recoveries,
        "roundtrips": len(recoveries),
        "winner": winner,
        "completion": sigil,
        "transitions": [winner, sigil],
    }


def _execute_survey_region(
    client,
    session,
    region: dict[str, Any],
    alignment: str,
    execution_steps: list[dict[str, Any]],
    visited_regions: list[str],
    root: Path,
    context,
) -> dict[str, Any]:
    slug = region["slug"]
    if alignment not in region["alignment_values"]:
        raise ValueError(f"Unknown {slug} alignment policy: {alignment}")
    events = _events_by_name(client)
    choice = _run_event(
        client, session, events[region["choice_events"][alignment]]
    )
    choice["kind"] = "survey_alignment_choice"
    choice["region"] = slug
    choice["alignment"] = alignment
    execution_steps.append(choice)

    # Deliberately leave mid-survey. Partial observations must survive a map
    # roundtrip and the same semantic entry gate must admit re-entry.
    retreat = _run_event(client, session, events[region["return_event"]])
    retreat["kind"] = "survey_partial_roundtrip"
    retreat["transition_frames"] = _pump_until_map(
        client, "unmapped_province.tmx"
    )
    retreat["map_after"] = client.get_map_name()
    execution_steps.append(retreat)
    visited_regions.append(retreat["map_after"])

    events = _events_by_name(client)
    consequence = _run_event(
        client,
        session,
        events[region["consequence_events"][alignment]],
    )
    consequence["kind"] = "persistent_branch_consequence"
    consequence["alignment"] = alignment
    execution_steps.append(consequence)
    events = _events_by_name(client)
    echo = _run_event(
        client,
        session,
        events[region["phenotypes"][alignment]["echo_event"]],
    )
    echo["kind"] = "spatial_branch_consequence"
    echo["alignment"] = alignment
    execution_steps.append(echo)

    import pygame

    client.draw()
    phenotype_screenshot = (
        root
        / "foundry"
        / "artifacts"
        / f"unmapped_province.{alignment}.runtime.generated.png"
    )
    pygame.image.save(context.screen, phenotype_screenshot)
    layer_color = client.map_renderer.layer_color
    observed_overlay = (
        ":".join(map(str, tuple(layer_color))) if layer_color else None
    )
    echo_actor = client.get_npc(
        region["phenotypes"][alignment]["echo_actor"]
    )
    if echo_actor is None:
        raise RuntimeError(f"The {alignment} spatial echo did not materialize.")
    phenotype = {
        **region["phenotypes"][alignment],
        "alignment": alignment,
        "observed_overlay": observed_overlay,
        "observed_echo_position": list(echo_actor.tile_pos),
        "screenshot": phenotype_screenshot.as_posix(),
        "screenshot_sha256": hashlib.sha256(
            phenotype_screenshot.read_bytes()
        ).hexdigest(),
    }
    reentry = _run_event(client, session, events[region["entry_event"]])
    reentry["kind"] = "survey_reentry"
    reentry["transition_frames"] = _pump_until_map(client, f"{slug}.tmx")
    reentry["map_after"] = client.get_map_name()
    execution_steps.append(reentry)
    visited_regions.append(reentry["map_after"])

    events = _events_by_name(client)
    observations = []
    for event_name in region["observation_events"]:
        observation = _run_event(client, session, events[event_name])
        observation["kind"] = "survey_observation"
        observation["region"] = slug
        observations.append(observation)
        execution_steps.append(observation)
    completion = _run_event(
        client,
        session,
        events[region["completion_events"][alignment]],
    )
    completion["transition"] = region["recover_action"]
    completion["region"] = slug
    completion["alignment"] = alignment
    execution_steps.append(completion)
    return {
        "slug": slug,
        "mechanic": "survey",
        "ecology": None,
        "attempts": [],
        "recoveries": [],
        "roundtrips": 1,
        "winner": None,
        "completion": completion,
        "transitions": [completion],
        "choice": choice,
        "observations": observations,
        "consequence": consequence,
        "echo": echo,
        "phenotype": phenotype,
        "alignment": alignment,
    }


def run(root: Path, survey_policy: str = "chorus") -> dict[str, Any]:
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
    random.seed(int(admission["seed"]))
    client, context, session = _boot(root, visible=False)
    transcript: list[dict[str, Any]] = []
    execution_steps: list[dict[str, Any]] = []
    try:
        for _ in range(20):
            client.update(0.05)
            _dismiss_transient_states(client)
        events = _events_by_name(client)

        charter = _run_event(
            client,
            session,
            events[event_bindings["speak_to_archivist"]],
        )
        charter["transition"] = "speak_to_archivist"
        transcript.append(charter)
        execution_steps.append(charter)

        import pygame
        visited_regions = ["unmapped_province.tmx"]
        region_runs: list[dict[str, Any]] = []
        region_screenshots: dict[str, Path] = {}
        all_sentinel_recoveries: list[dict[str, Any]] = []

        for region_index, region in enumerate(
            admission["witnesses"]["campaign_regions"]
        ):
            slug = region["slug"]
            expected_map = f"{slug}.tmx"
            gateway = _run_event(
                client, session, events[region["entry_event"]]
            )
            gateway["kind"] = "region_transition"
            gateway["region"] = slug
            gateway["transition_frames"] = _pump_until_map(
                client, expected_map
            )
            gateway["map_after"] = client.get_map_name()
            execution_steps.append(gateway)
            visited_regions.append(gateway["map_after"])

            client.draw()
            screenshot = (
                root
                / "foundry"
                / "artifacts"
                / f"{slug}.runtime.generated.png"
            )
            pygame.image.save(context.screen, screenshot)
            region_screenshots[slug] = screenshot

            if region["mechanic"] == "combat":
                region_run = _execute_combat_region(
                    client,
                    session,
                    region,
                    region_index,
                    admission,
                    execution_steps,
                    visited_regions,
                )
                all_sentinel_recoveries.extend(region_run["recoveries"])
            else:
                region_run = _execute_survey_region(
                    client,
                    session,
                    region,
                    survey_policy,
                    execution_steps,
                    visited_regions,
                    root,
                    context,
                )
            transcript.extend(region_run["transitions"])

            events = _events_by_name(client)
            return_step = _run_event(
                client, session, events[region["return_event"]]
            )
            return_step["kind"] = "region_transition"
            return_step["region"] = slug
            return_step["transition_frames"] = _pump_until_map(
                client, "unmapped_province.tmx"
            )
            return_step["map_after"] = client.get_map_name()
            execution_steps.append(return_step)
            visited_regions.append(return_step["map_after"])
            events = _events_by_name(client)
            region_runs.append(region_run)

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
        target
        for _, _, target in admission["quest"]["transitions"]
    ]
    observed_stages = [entry["stage_after"] for entry in transcript]
    expected_visits = ["unmapped_province.tmx"]
    for region in region_runs:
        region_map = f"{region['slug']}.tmx"
        expected_visits.append(region_map)
        for _ in range(region["roundtrips"]):
            expected_visits.extend(["unmapped_province.tmx", region_map])
        expected_visits.append("unmapped_province.tmx")
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
            "id": "campaign-crosses-every-generated-region-and-returns",
            "passed": visited_regions == expected_visits,
            "detail": visited_regions,
        },
        {
            "id": "every-generated-region-renders-in-real-runtime",
            "passed": len(region_screenshots) == len(region_runs)
            and all(path.stat().st_size > 0 for path in region_screenshots.values()),
            "detail": {
                slug: {
                    "path": path.as_posix(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
                for slug, path in region_screenshots.items()
            },
        },
        {
            "id": "selected-ecologies-all-execute-and-terminate",
            "passed": all(
                region["attempts"][-1]["outcome"] == "won"
                and region["winner"]["stage_after"]
                == next(
                    witness["open_state"]
                    for witness in admission["witnesses"]["campaign_regions"]
                    if witness["slug"] == region["slug"]
                )
                for region in region_runs
                if region["mechanic"] == "combat"
            ),
            "detail": [
                {
                    "region": region["slug"],
                    "guardian": region["ecology"]["monster"],
                    "outcomes": [
                        attempt["outcome"] for attempt in region["attempts"]
                    ],
                }
                for region in region_runs
                if region["mechanic"] == "combat"
            ],
        },
        {
            "id": "survey-choice-persists-and-changes-town-response",
            "passed": all(
                region["choice"]["alignment"] == survey_policy
                and region["completion"]["stage_after"]
                == next(
                    witness["complete_state"]
                    for witness in admission["witnesses"]["campaign_regions"]
                    if witness["slug"] == region["slug"]
                )
                and all(
                    condition["passed"]
                    for condition in region["consequence"]["conditions"]
                )
                for region in region_runs
                if region["mechanic"] == "survey"
            ),
            "detail": [
                {
                    "region": region["slug"],
                    "alignment": region["alignment"],
                    "consequence": region["consequence"]["event"],
                }
                for region in region_runs
                if region["mechanic"] == "survey"
            ],
        },
        {
            "id": "survey-choice-projects-a-visible-spatial-phenotype",
            "passed": all(
                region["phenotype"]["observed_overlay"]
                == region["phenotype"]["overlay"]
                and region["phenotype"]["observed_echo_position"]
                == region["phenotype"]["echo_position"]
                and Path(region["phenotype"]["screenshot"]).is_file()
                and hashlib.sha256(
                    Path(region["phenotype"]["screenshot"]).read_bytes()
                ).hexdigest()
                == region["phenotype"]["screenshot_sha256"]
                for region in region_runs
                if region["mechanic"] == "survey"
            ),
            "detail": [
                region["phenotype"]
                for region in region_runs
                if region["mechanic"] == "survey"
            ],
        },
        {
            "id": "battle-loss-recovery-loop-is-executable",
            "passed": bool(all_sentinel_recoveries)
            and len(all_sentinel_recoveries)
            == sum(
                attempt["outcome"] == "lost"
                for region in region_runs
                for attempt in region["attempts"]
            )
            and len(recovery_steps)
            == sum(entry["outcome"] == "lost" for entry in battle_attempts),
            "detail": {
                "regional_recoveries": len(all_sentinel_recoveries),
                "duel_recoveries": len(recovery_steps),
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
        "survey_policy": survey_policy,
        "branch_phenotypes": [
            region["phenotype"]
            for region in region_runs
            if region["mechanic"] == "survey"
        ],
        "transcript": transcript,
        "execution_steps": execution_steps,
        "region_screenshots": {
            slug: path.as_posix() for slug, path in region_screenshots.items()
        },
        "proofs": proofs,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    body["fingerprint"] = hashlib.sha256(canonical.encode()).hexdigest()
    filename = (
        "playthrough.generated.json"
        if survey_policy == "chorus"
        else f"playthrough.{survey_policy}.generated.json"
    )
    output = root / "foundry" / "artifacts" / filename
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
    parser.add_argument(
        "--survey-policy", choices=("chorus", "silence"), default="chorus"
    )
    args = parser.parse_args()
    result = run(args.root, args.survey_policy)
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
