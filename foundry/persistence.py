# SPDX-License-Identifier: GPL-3.0-or-later
"""Prove that a compiled semantic campaign survives Tuxemon persistence."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
from pathlib import Path
from typing import Any

from foundry.playthrough import (
    _dismiss_transient_states,
    _events_by_name,
    _pump_until_map,
    _run_event,
    _stage,
)
from foundry.runtime import _boot
from foundry.town import compile_world


def _facts(client, session) -> dict[str, Any]:
    return {
        "map": client.get_map_name(),
        "position": list(session.player.tile_pos),
        "province_stage": _stage(session),
        "party": [
            {
                "slug": monster.slug,
                "level": monster.level,
                "current_hp": monster.current_hp,
            }
            for monster in session.player.monsters
        ],
    }


def run(root: Path) -> dict[str, Any]:
    root = root.resolve()
    build = compile_world(root)
    admission = json.loads(
        Path(build["certificate"]).read_text(encoding="utf-8")
    )
    first_region = admission["witnesses"]["campaign_regions"][0]
    event_bindings = {
        binding["transition"]: binding["event"]
        for binding in admission["witnesses"]["quest_event_bindings"]
    }
    save_path = root / "foundry" / "artifacts" / "campaign-replay.save.json"
    certificate_path = (
        root / "foundry" / "artifacts" / "persistence.generated.json"
    )
    save_path.parent.mkdir(parents=True, exist_ok=True)

    previous_logging_threshold = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    random.seed(int(admission["seed"]))
    client, _, session = _boot(root, visible=False)
    try:
        for _ in range(20):
            client.update(0.05)
            _dismiss_transient_states(client)
        events = _events_by_name(client)
        _run_event(
            client,
            session,
            events[event_bindings["speak_to_archivist"]],
        )
        _run_event(
            client, session, events[first_region["entry_event"]]
        )
        _pump_until_map(client, f"{first_region['slug']}.tmx")

        from tuxemon.save_system.save import (
            SaveMethod,
            dump_data,
            get_save_data,
            load,
        )

        before = _facts(client, session)
        dump_data(
            get_save_data(session),
            save_path,
            SaveMethod.JSON,
            serializer_kwargs={"indent": 2, "sort_keys": True},
        )

        session.player.game_variables.set("province_stage", "corrupted")
        session.player.set_position((4.0, 4.0))
        session.player.monsters[0].current_hp = 1
        mutated = _facts(client, session)

        loaded = load(save_path)
        if loaded is None:
            raise RuntimeError("Tuxemon rejected its own serialized save.")
        session.load_state(loaded)
        after = _facts(client, session)

        events = _events_by_name(client)
        resumed = _run_event(
            client, session, events[first_region["return_event"]]
        )
        resumed["transition_frames"] = _pump_until_map(
            client, "unmapped_province.tmx"
        )
        resumed["map_after"] = client.get_map_name()
    finally:
        logging.disable(previous_logging_threshold)
        import pygame

        pygame.quit()

    proofs = [
        {
            "id": "real-runtime-state-serializes",
            "passed": save_path.is_file() and save_path.stat().st_size > 0,
            "detail": {"format": "json", "schema": "Tuxemon SaveData"},
        },
        {
            "id": "fault-injection-changes-authoritative-state",
            "passed": mutated != before,
            "detail": {
                "stage_before": before["province_stage"],
                "stage_mutated": mutated["province_stage"],
            },
        },
        {
            "id": "save-load-restores-authoritative-facts",
            "passed": after == before,
            "detail": {"before": before, "after": after},
        },
        {
            "id": "loaded-campaign-resumes-through-compiled-event",
            "passed": resumed["map_after"] == "unmapped_province.tmx"
            and all(
                condition["passed"] for condition in resumed["conditions"]
            ),
            "detail": resumed,
        },
    ]
    body = {
        "schema": "ai-native-persistence-replay/v1",
        "world_fingerprint": build["fingerprint"],
        "checkpoint": before,
        "restored": after,
        "resume": resumed,
        "proofs": proofs,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    body["fingerprint"] = hashlib.sha256(canonical.encode()).hexdigest()
    certificate_path.write_text(
        json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if not all(proof["passed"] for proof in proofs):
        raise RuntimeError(
            f"Persistence admission failed; inspect {certificate_path}"
        )
    return {"output": certificate_path.as_posix(), **body}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay a generated campaign checkpoint through Tuxemon."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(json.dumps(run(args.root), indent=2))


if __name__ == "__main__":
    main()
