# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import yaml

from foundry.town import compile_world, generate_town


def _boot(root: Path, visible: bool):
    if not visible:
        os.environ["SDL_VIDEODRIVER"] = "dummy"

    from tuxemon.user_config import CONFIG

    CONFIG.mods = ["tuxemon", "unmapped_province"]
    CONFIG.config_model.game.recompile_translations = False
    CONFIG.config_model.game.skip_titlescreen = True
    CONFIG.config_model.display.splash = False
    CONFIG.config_model.display.vsync = False
    if not visible:
        CONFIG.config_model.display.resolution_x = 640
        CONFIG.config_model.display.resolution_y = 360

    from tuxemon.constants.asset_loader import fetch_mod_asset_roots

    fetch_mod_asset_roots(CONFIG, force=True)
    from tuxemon.prepare import headless_init, pygame_init

    context = pygame_init() if visible else headless_init()
    from tuxemon.client import LocalPygameClient
    from tuxemon.database.management import ModMetadataLoader
    from tuxemon.launcher import GameLauncher
    from tuxemon.session import local_session

    client = LocalPygameClient.create(CONFIG, context)
    local_session.set_client(client)
    metadata = ModMetadataLoader(
        ["unmapped_province"], root / "mods"
    ).load_metadata()["unmapped_province"]
    GameLauncher(client).launch(local_session, metadata)
    return client, context, local_session


def runtime_probe(
    root: Path, screenshot: Path | None = None
) -> dict[str, Any]:
    root = root.resolve()
    build = compile_world(root)
    client, context, session = _boot(root, visible=False)
    for _ in range(12):
        client.update(1.0 / 60.0)
    client.draw()

    import pygame

    screenshot = screenshot or (
        root
        / "foundry"
        / "artifacts"
        / "unmapped_province.runtime.generated.png"
    )
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(context.screen, screenshot)
    current_map = client.map_manager.current_map
    expected = json.loads(
        Path(build["certificate"]).read_text(encoding="utf-8")
    )
    spec_path = root / "foundry" / "worlds" / "unmapped_province.seed.yaml"
    town = generate_town(yaml.safe_load(spec_path.read_text(encoding="utf-8")))
    occupied = {npc.tile_pos for npc in client.npc_manager.npcs.values()}
    path_lengths: dict[str, int | None] = {}
    for role, raw_cell in expected["witnesses"]["landmark_approaches"].items():
        x, y = raw_cell
        candidates = ((x, y), (x + 1, y), (x - 1, y), (x, y + 1))
        paths = [
            client.pathfinder.pathfind(
                session.player.tile_pos, candidate, session.player.facing
            )
            for candidate in candidates
            if candidate not in occupied
        ]
        valid_paths = [path for path in paths if path is not None]
        path_lengths[role] = min(map(len, valid_paths), default=None)
    blocked_door_paths = {
        landmark.role: client.pathfinder.pathfind(
            session.player.tile_pos, landmark.door, session.player.facing
        )
        for landmark in town.landmarks
    }
    opponent_party_size = len(client.get_npc("npc_test").monsters)
    client.event_engine.execute_action(
        "start_battle", ["player", "npc_test"], skip=True
    )
    battle_started = "CombatState" in client.active_state_names
    for _ in range(360):
        client.update(1.0 / 60.0)
    client.draw()
    battle_screenshot = screenshot.with_name(
        "unmapped_province.battle.generated.png"
    )
    pygame.image.save(context.screen, battle_screenshot)
    battle_state = client.get_state_by_name("CombatState")
    observed = {
        "map": client.get_map_name(),
        "dimensions": [current_map.width, current_map.height],
        "events": len(current_map.events),
        "collision_cells": len(current_map.collision_map),
        "active_states": client.active_state_names,
        "npcs_including_player": len(client.npc_manager.npcs),
        "starter_party_size": len(session.player.monsters),
        "opponent_party_size": opponent_party_size,
        "battle_started": battle_started,
        "battle_phase": str(getattr(battle_state, "phase", None)),
        "landmark_path_lengths": path_lengths,
        "blocked_landmark_doors_rejected": [
            role for role, path in blocked_door_paths.items() if path is None
        ],
        "screen": list(context.screen.get_size()),
        "screenshot_sha256": hashlib.sha256(
            screenshot.read_bytes()
        ).hexdigest(),
        "battle_screenshot_sha256": hashlib.sha256(
            battle_screenshot.read_bytes()
        ).hexdigest(),
    }
    proofs = [
        {
            "id": "tuxemon-loads-generated-map",
            "passed": observed["map"] == "unmapped_province.tmx",
            "detail": observed["map"],
        },
        {
            "id": "runtime-preserves-map-dimensions",
            "passed": observed["dimensions"] == expected["dimensions"],
            "detail": observed["dimensions"],
        },
        {
            "id": "runtime-preserves-derived-collisions",
            "passed": (
                observed["collision_cells"]
                == expected["counts"]["collision_cells"]
            ),
            "detail": observed["collision_cells"],
        },
        {
            "id": "runtime-materializes-actors",
            "passed": observed["npcs_including_player"] == 4,
            "detail": observed["npcs_including_player"],
        },
        {
            "id": "runtime-grants-starter-party",
            "passed": observed["starter_party_size"] == 1,
            "detail": observed["starter_party_size"],
        },
        {
            "id": "runtime-renders-frame",
            "passed": screenshot.stat().st_size > 0,
            "detail": screenshot.as_posix(),
        },
        {
            "id": "runtime-pathfinder-reaches-every-landmark",
            "passed": all(
                length is not None for length in path_lengths.values()
            ),
            "detail": path_lengths,
        },
        {
            "id": "runtime-collision-rejects-building-doors",
            "passed": all(
                path is None for path in blocked_door_paths.values()
            ),
            "detail": observed["blocked_landmark_doors_rejected"],
        },
        {
            "id": "runtime-enters-turn-based-battle",
            "passed": (
                observed["opponent_party_size"] == 1
                and observed["battle_started"]
                and battle_screenshot.stat().st_size > 0
            ),
            "detail": {
                "opponent_party_size": observed["opponent_party_size"],
                "phase": observed["battle_phase"],
            },
        },
    ]
    body = {
        "schema": "ai-native-runtime-certificate/v1",
        "world_fingerprint": build["fingerprint"],
        "observed": observed,
        "proofs": proofs,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    body["fingerprint"] = hashlib.sha256(canonical.encode()).hexdigest()
    certificate = (
        root
        / "foundry"
        / "artifacts"
        / "unmapped_province.runtime.generated.json"
    )
    certificate.write_text(
        json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if not all(proof["passed"] for proof in proofs):
        raise RuntimeError(f"Runtime admission failed; inspect {certificate}")
    return {
        "certificate": certificate.as_posix(),
        "screenshot": screenshot.as_posix(),
        "battle_screenshot": battle_screenshot.as_posix(),
        **body,
    }


def play(root: Path) -> None:
    root = root.resolve()
    compile_world(root)
    client, _, _ = _boot(root, visible=True)
    try:
        client.main()
    finally:
        import pygame

        pygame.quit()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the generated foundry world."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--play", action="store_true")
    mode.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    if args.play:
        play(args.root)
    else:
        result = runtime_probe(args.root)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
