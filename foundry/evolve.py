# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import statistics
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from foundry.town import Tile, Town, certify, generate_town

Coord = tuple[int, int]


@dataclass(frozen=True)
class Candidate:
    seed: int
    score: float
    descriptor: tuple[int, int, int]
    features: dict[str, float | int]
    fingerprint: str

    def serializable(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "score": round(self.score, 4),
            "descriptor": list(self.descriptor),
            "features": self.features,
            "fingerprint": self.fingerprint,
        }


def _distances(town: Town) -> dict[Coord, int]:
    distances = {town.spawn: 0}
    queue = deque([town.spawn])
    while queue:
        x, y = queue.popleft()
        for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            nx, ny = neighbor
            if (
                0 <= nx < town.width
                and 0 <= ny < town.height
                and neighbor not in town.blocked
                and neighbor not in distances
            ):
                distances[neighbor] = distances[(x, y)] + 1
                queue.append(neighbor)
    return distances


def evaluate(town: Town) -> Candidate:
    certificate = certify(town)
    passed = all(proof["passed"] for proof in certificate["proofs"])
    distances = _distances(town)
    landmark_distances = [distances[item.approach] for item in town.landmarks]
    mean_distance = statistics.fmean(landmark_distances)
    spread = statistics.pstdev(landmark_distances)
    tree_count = sum(
        value == int(Tile.TREE) for row in town.objects for value in row
    )
    collision_cells = certificate["counts"]["collision_cells"]
    collision_rectangles = certificate["counts"]["collision_rectangles"]
    compression = collision_cells / max(1, collision_rectangles)
    landmark_separation = min(
        abs(left.x - right.x) + abs(left.y - right.y)
        for index, left in enumerate(town.landmarks)
        for right in town.landmarks[index + 1 :]
    )
    # A target rather than a monotonic maximum prevents the search from
    # preferring either tiny toy maps or exhausting walking distances.
    score = (
        (1000.0 if passed else -1000.0)
        - abs(mean_distance - 22.0) * 8.0
        - abs(spread - 5.0) * 3.0
        + landmark_separation * 2.0
        + compression * 4.0
    )
    features: dict[str, float | int] = {
        "mean_landmark_distance": round(mean_distance, 3),
        "path_length_spread": round(spread, 3),
        "tree_count": tree_count,
        "collision_rectangles": collision_rectangles,
        "collision_compression": round(compression, 3),
        "landmark_separation": landmark_separation,
    }
    descriptor = (
        int(mean_distance // 4),
        int(spread // 2),
        int(collision_rectangles // 20),
    )
    return Candidate(
        seed=town.seed,
        score=score,
        descriptor=descriptor,
        features=features,
        fingerprint=certificate["fingerprint"],
    )


def evolve(spec: dict[str, Any], population: int = 128) -> dict[str, Any]:
    if population < 1:
        raise ValueError("Population must be positive.")
    origin = int(spec["identity"]["seed"])
    archive: dict[tuple[int, int, int], Candidate] = {}
    rejected = 0
    for index in range(population):
        candidate_spec = copy.deepcopy(spec)
        candidate_spec["identity"]["seed"] = origin + index * 7919
        town = generate_town(candidate_spec)
        candidate = evaluate(town)
        if candidate.score < 0:
            rejected += 1
            continue
        incumbent = archive.get(candidate.descriptor)
        if incumbent is None or candidate.score > incumbent.score:
            archive[candidate.descriptor] = candidate
    if not archive:
        raise RuntimeError("Every candidate failed admission.")
    elites = sorted(
        archive.values(), key=lambda item: (-item.score, item.seed)
    )
    champion = elites[0]
    body = {
        "schema": "ai-native-quality-diversity-archive/v1",
        "population": population,
        "admitted": population - rejected,
        "rejected": rejected,
        "occupied_behavior_cells": len(archive),
        "champion": champion.serializable(),
        "elites": [candidate.serializable() for candidate in elites],
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    body["fingerprint"] = hashlib.sha256(canonical.encode()).hexdigest()
    return body


def run(root: Path, population: int = 128) -> dict[str, Any]:
    root = root.resolve()
    spec_path = root / "foundry" / "worlds" / "unmapped_province.seed.yaml"
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    archive = evolve(spec, population)
    output = root / "foundry" / "artifacts" / "town-population.generated.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(archive, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {"output": output.as_posix(), **archive}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search a quality-diversity population of semantic towns."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--population", type=int, default=128)
    args = parser.parse_args()
    print(json.dumps(run(args.root, args.population), indent=2))


if __name__ == "__main__":
    main()
