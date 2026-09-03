# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from foundry.runtime import _boot


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _payload_fingerprint(root: Path) -> str:
    from tuxemon.constants.paths import mods_folder

    certificate = mods_folder / "unmapped_province" / "foundry-admission.json"
    return json.loads(certificate.read_text(encoding="utf-8"))["fingerprint"]


def smoke_test(root: Path) -> dict[str, Any]:
    client, context, session = _boot(root, visible=False)
    try:
        for _ in range(20):
            client.update(0.05)
        client.draw()
        observed = {
            "map": client.get_map_name(),
            "screen": list(context.screen.get_size()),
            "events": len(client.map_manager.current_map.events),
            "npcs_including_player": len(client.npc_manager.npcs),
            "starter_party_size": len(session.player.monsters),
            "opponent_party_size": len(client.get_npc("npc_test").monsters),
        }
        proofs = [
            {
                "id": "frozen-runtime-loads-generated-map",
                "passed": observed["map"] == "unmapped_province.tmx",
                "detail": observed["map"],
            },
            {
                "id": "frozen-runtime-loads-campaign-events",
                "passed": observed["events"] == 17,
                "detail": observed["events"],
            },
            {
                "id": "frozen-runtime-materializes-parties",
                "passed": observed["starter_party_size"] == 1
                and observed["opponent_party_size"] == 1,
                "detail": {
                    "player": observed["starter_party_size"],
                    "opponent": observed["opponent_party_size"],
                },
            },
        ]
    finally:
        import pygame

        pygame.quit()
    body = {
        "schema": "ai-native-frozen-smoke/v1",
        "world_fingerprint": _payload_fingerprint(root),
        "observed": observed,
        "proofs": proofs,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    body["fingerprint"] = hashlib.sha256(canonical.encode()).hexdigest()
    output = (
        root / "release-smoke.generated.json"
        if getattr(sys, "frozen", False)
        else root / "foundry" / "artifacts" / "release-smoke.generated.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if not all(proof["passed"] for proof in proofs):
        raise RuntimeError(f"Frozen smoke admission failed; inspect {output}")
    return body


def play(root: Path) -> None:
    client, _, _ = _boot(root, visible=True)
    try:
        client.main()
    finally:
        import pygame

        pygame.quit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch The Unmapped Province.")
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()
    root = application_root()
    if args.smoke_test:
        smoke_test(root)
    else:
        play(root)


if __name__ == "__main__":
    main()
