# SPDX-License-Identifier: GPL-3.0-or-later
"""Execute counterfactual campaign choices and prove terminal convergence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from foundry.playthrough import run as run_playthrough


def _canonical(document: dict[str, Any]) -> str:
    body = dict(document)
    body.pop("fingerprint", None)
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _summary(document: dict[str, Any], path: Path) -> dict[str, Any]:
    return {
        "policy": document["survey_policy"],
        "certificate": path.as_posix(),
        "certificate_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "fingerprint": document["fingerprint"],
        "world_fingerprint": document["world_fingerprint"],
        "terminal": document["transcript"][-1]["stage_after"],
        "phenotype": document["branch_phenotypes"][0],
        "combat_ecologies": document["combat_ecologies"],
        "consequence": next(
            step["event"]
            for step in document["execution_steps"]
            if step.get("kind") == "persistent_branch_consequence"
        ),
    }


def _run_and_load(root: Path, policy: str) -> tuple[dict[str, Any], Path]:
    result = run_playthrough(root, policy)
    path = Path(result["output"])
    return json.loads(path.read_text(encoding="utf-8")), path


def run(root: Path) -> dict[str, Any]:
    root = root.resolve()
    chorus_path = root / "foundry" / "artifacts" / "playthrough.generated.json"
    if not chorus_path.is_file():
        chorus = run_playthrough(root, "chorus")
    else:
        chorus = json.loads(chorus_path.read_text(encoding="utf-8"))
    silence, silence_path = _run_and_load(root, "silence")
    if (
        chorus.get("fingerprint") != _canonical(chorus)
        or not all(proof["passed"] for proof in chorus.get("proofs", []))
        or chorus.get("world_fingerprint")
        != silence.get("world_fingerprint")
    ):
        chorus, chorus_path = _run_and_load(root, "chorus")
    branches = {
        "chorus": _summary(chorus, chorus_path),
        "silence": _summary(silence, silence_path),
    }
    proofs = [
        {
            "id": "both-survey-branches-execute-in-real-runtime",
            "passed": all(
                document.get("fingerprint") == _canonical(document)
                and all(proof["passed"] for proof in document["proofs"])
                for document in (chorus, silence)
            ),
            "detail": {
                policy: branch["fingerprint"]
                for policy, branch in branches.items()
            },
        },
        {
            "id": "branches-share-one-compiled-world",
            "passed": len(
                {branch["world_fingerprint"] for branch in branches.values()}
            )
            == 1,
            "detail": [
                branch["world_fingerprint"] for branch in branches.values()
            ],
        },
        {
            "id": "branch-consequences-are-observably-distinct",
            "passed": branches["chorus"]["consequence"]
            != branches["silence"]["consequence"],
            "detail": {
                policy: branch["consequence"]
                for policy, branch in branches.items()
            },
        },
        {
            "id": "branch-phenotypes-render-as-distinct-spatial-states",
            "passed": (
                branches["chorus"]["phenotype"]["screenshot_sha256"]
                != branches["silence"]["phenotype"]["screenshot_sha256"]
                and branches["chorus"]["phenotype"]["observed_overlay"]
                != branches["silence"]["phenotype"]["observed_overlay"]
                and branches["chorus"]["phenotype"][
                    "observed_echo_position"
                ]
                != branches["silence"]["phenotype"][
                    "observed_echo_position"
                ]
            ),
            "detail": {
                policy: branch["phenotype"]
                for policy, branch in branches.items()
            },
        },
        {
            "id": "branches-alter-downstream-combat-ecology-and-location",
            "passed": any(
                (
                    (
                        branches["chorus"]["combat_ecologies"][slug][
                            "observed"
                        ]["monster"],
                        branches["chorus"]["combat_ecologies"][slug][
                            "observed"
                        ]["level"],
                    )
                    != (
                        branches["silence"]["combat_ecologies"][slug][
                            "observed"
                        ]["monster"],
                        branches["silence"]["combat_ecologies"][slug][
                            "observed"
                        ]["level"],
                    )
                    and branches["chorus"]["combat_ecologies"][slug][
                        "observed"
                    ]["position"]
                    != branches["silence"]["combat_ecologies"][slug][
                        "observed"
                    ]["position"]
                )
                for slug in branches["chorus"]["combat_ecologies"]
            ),
            "detail": {
                policy: branch["combat_ecologies"]
                for policy, branch in branches.items()
            },
        },
        {
            "id": "both-branches-reach-the-terminal-state",
            "passed": {
                branch["terminal"] for branch in branches.values()
            }
            == {"province_mapped"},
            "detail": {
                policy: branch["terminal"]
                for policy, branch in branches.items()
            },
        },
    ]
    body = {
        "schema": "ai-native-counterfactual-branch-proof/v1",
        "world_fingerprint": branches["chorus"]["world_fingerprint"],
        "branches": branches,
        "proofs": proofs,
    }
    body["fingerprint"] = _canonical(body)
    output = root / "foundry" / "artifacts" / "branching.generated.json"
    output.write_text(
        json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if not all(proof["passed"] for proof in proofs):
        raise RuntimeError(f"Counterfactual branch proof failed: {output}")
    return {"output": output.as_posix(), **body}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Execute every admitted campaign branch counterfactually."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(json.dumps(run(args.root), indent=2))


if __name__ == "__main__":
    main()
