# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import random
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any

import yaml
from PIL import Image, ImageDraw

Coord = tuple[int, int]


class Tile(IntEnum):
    GRASS = 1
    FLOWERS = 2
    PATH = 3
    PLAZA = 4
    WATER = 5
    WATER_LIGHT = 6
    TREE = 7
    HEDGE = 8
    ROOF_AMBER_LEFT = 9
    ROOF_AMBER = 10
    ROOF_AMBER_RIGHT = 11
    WALL_AMBER = 12
    WINDOW_AMBER = 13
    DOOR_AMBER = 14
    AWNING = 15
    BRIDGE = 16
    ROOF_INDIGO_LEFT = 17
    ROOF_INDIGO = 18
    ROOF_INDIGO_RIGHT = 19
    WALL_INDIGO = 20
    WINDOW_INDIGO = 21
    DOOR_INDIGO = 22
    FOUNTAIN = 23
    STATUE = 24
    SIGN = 25
    GARDEN = 26
    LAMP = 27
    STALL = 28


@dataclass(frozen=True)
class Landmark:
    role: str
    quadrant: str
    roof: str
    x: int
    y: int
    width: int
    height: int

    @property
    def door(self) -> Coord:
        return (self.x + self.width // 2, self.y + self.height - 1)

    @property
    def approach(self) -> Coord:
        x, y = self.door
        return (x, y + 1)


@dataclass
class Town:
    slug: str
    title: str
    seed: int
    width: int
    height: int
    ground: list[list[int]]
    objects: list[list[int]]
    above: list[list[int]]
    blocked: set[Coord]
    roads: set[Coord]
    landmarks: list[Landmark]
    spawn: Coord
    shard: Coord
    actor_positions: dict[str, Coord]
    style: dict[str, str]
    spec: dict[str, Any]


class AdmissionRejected(RuntimeError):
    pass


def _blank(width: int, height: int, value: int = 0) -> list[list[int]]:
    return [[value for _ in range(width)] for _ in range(height)]


def _paint(cells: set[Coord], x: int, y: int, width: int, height: int) -> None:
    cells.update(
        (column, row)
        for row in range(y, y + height)
        for column in range(x, x + width)
    )


def _landmarks(spec: dict[str, Any], rng: random.Random) -> list[Landmark]:
    width = int(spec["geometry"]["width"])
    height = int(spec["geometry"]["height"])
    center_x, center_y = width // 2, height // 2
    anchors = {
        "northwest": (center_x - 17, center_y - 13),
        "northeast": (center_x + 6, center_y - 13),
        "southwest": (center_x - 17, center_y + 4),
        "southeast": (center_x + 6, center_y + 4),
    }
    output = []
    for intent in spec["intent"]["required_landmarks"]:
        x, y = anchors[intent["quadrant"]]
        output.append(
            Landmark(
                role=intent["role"],
                quadrant=intent["quadrant"],
                roof=intent["roof"],
                x=x + rng.choice((-1, 0, 1)),
                y=y + rng.choice((-1, 0, 1)),
                width=rng.choice((7, 8, 9)),
                height=rng.choice((6, 7)),
            )
        )
    return output


def _carve_spur(
    town: Town, start: Coord, target_rows: tuple[int, ...]
) -> None:
    x, y = start
    target_y = min(target_rows, key=lambda row: abs(row - y))
    step = 1 if target_y >= y else -1
    for row in range(y, target_y + step, step):
        town.roads.update(((x, row), (x + 1, row)))


def generate_town(spec: dict[str, Any]) -> Town:
    identity = spec["identity"]
    geometry = spec["geometry"]
    width, height = int(geometry["width"]), int(geometry["height"])
    seed = int(identity["seed"])
    if width < 44 or height < 34:
        raise ValueError("The town grammar requires at least a 44x34 lattice.")
    rng = random.Random(seed)
    center_x, center_y = width // 2, height // 2
    town = Town(
        slug=str(identity["slug"]),
        title=str(identity["title"]),
        seed=seed,
        width=width,
        height=height,
        ground=_blank(width, height, int(Tile.GRASS)),
        objects=_blank(width, height),
        above=_blank(width, height),
        blocked=set(),
        roads=set(),
        landmarks=_landmarks(spec, rng),
        spawn=(center_x + 1, center_y + 6),
        shard=(0, 0),
        actor_positions={},
        style=dict(spec["style_genome"]),
        spec=spec,
    )

    town.blocked.update((x, y) for x in range(width) for y in (0, height - 1))
    town.blocked.update((x, y) for y in range(height) for x in (0, width - 1))

    river_left: dict[int, int] = {}
    for y in range(1, height - 1):
        shore = width - 8 + round(1.4 * math.sin((y + seed % 17) / 5.2))
        river_left[y] = shore
        for x in range(shore, width - 1):
            tile = Tile.WATER_LIGHT if (x + y) % 5 == 0 else Tile.WATER
            town.ground[y][x] = int(tile)
            town.blocked.add((x, y))

    road_width = int(geometry["road_width"])
    half = road_width // 2
    _paint(town.roads, 2, center_y - half, width - 4, road_width)
    _paint(town.roads, center_x - half, 2, road_width, height - 4)
    left, right, top, bottom = 11, width - 15, 7, height - 8
    _paint(town.roads, left, top, right - left + 1, 2)
    _paint(town.roads, left, bottom, right - left + 1, 2)
    _paint(town.roads, left, top, 2, bottom - top + 1)
    _paint(town.roads, right, top, 2, bottom - top + 1)
    _paint(town.roads, center_x - 5, center_y - 4, 11, 9)

    for landmark in town.landmarks:
        _carve_spur(town, landmark.approach, (top + 1, center_y, bottom))

    for x, y in town.roads:
        if x >= river_left.get(y, width):
            town.ground[y][x] = int(Tile.BRIDGE)
        elif abs(x - center_x) <= 5 and abs(y - center_y) <= 4:
            town.ground[y][x] = int(Tile.PLAZA)
        else:
            town.ground[y][x] = int(Tile.PATH)
        town.blocked.discard((x, y))

    for landmark in town.landmarks:
        if landmark.roof == "amber":
            roof = (
                Tile.ROOF_AMBER_LEFT,
                Tile.ROOF_AMBER,
                Tile.ROOF_AMBER_RIGHT,
            )
            wall, window, door = (
                Tile.WALL_AMBER,
                Tile.WINDOW_AMBER,
                Tile.DOOR_AMBER,
            )
        else:
            roof = (
                Tile.ROOF_INDIGO_LEFT,
                Tile.ROOF_INDIGO,
                Tile.ROOF_INDIGO_RIGHT,
            )
            wall, window, door = (
                Tile.WALL_INDIGO,
                Tile.WINDOW_INDIGO,
                Tile.DOOR_INDIGO,
            )
        for y in range(landmark.y, landmark.y + landmark.height):
            for x in range(landmark.x, landmark.x + landmark.width):
                if y < landmark.y + 2:
                    tile = roof[0] if x == landmark.x else roof[1]
                    if x == landmark.x + landmark.width - 1:
                        tile = roof[2]
                else:
                    tile = window if (x + y) % 4 == 0 else wall
                if (x, y) == landmark.door:
                    tile = door
                town.objects[y][x] = int(tile)
                town.blocked.add((x, y))
        sign = (landmark.x + 1, landmark.y + landmark.height)
        town.objects[sign[1]][sign[0]] = int(Tile.SIGN)
        town.blocked.add(sign)

    fountain = (center_x, center_y)
    town.objects[fountain[1]][fountain[0]] = int(Tile.FOUNTAIN)
    town.blocked.add(fountain)
    observatory = next(
        item for item in town.landmarks if item.role == "observatory"
    )
    town.shard = (observatory.door[0] + 3, observatory.approach[1] + 1)
    shard_x, shard_y = town.shard
    town.objects[shard_y][shard_x] = int(Tile.STATUE)
    town.blocked.add(town.shard)
    _carve_spur(town, (shard_x, shard_y + 1), (center_y, bottom))
    for x, y in town.roads:
        if town.ground[y][x] == int(Tile.GRASS):
            town.ground[y][x] = int(Tile.PATH)

    for x, y in (
        (center_x - 5, center_y - 4),
        (center_x + 5, center_y - 4),
        (center_x - 5, center_y + 4),
        (center_x + 5, center_y + 4),
    ):
        town.objects[y][x] = int(Tile.STALL)
        town.blocked.add((x, y))

    protected = set(town.roads) | town.blocked
    for landmark in town.landmarks:
        ax, ay = landmark.approach
        protected.update(
            (x, y)
            for y in range(ay - 2, ay + 3)
            for x in range(ax - 2, ax + 3)
        )
    candidates = [
        (x, y)
        for y in range(2, height - 2)
        for x in range(2, width - 2)
        if (x, y) not in protected and x < river_left.get(y, width) - 1
    ]
    rng.shuffle(candidates)
    trees: list[Coord] = []
    tree_target = int(width * height * float(geometry["tree_density"]))
    for cell in candidates:
        if any(
            abs(cell[0] - x) <= 1 and abs(cell[1] - y) <= 1 for x, y in trees
        ):
            continue
        trees.append(cell)
        town.objects[cell[1]][cell[0]] = int(Tile.TREE)
        town.blocked.add(cell)
        if len(trees) >= tree_target:
            break

    for y in range(1, height - 1):
        for x in range(1, width - 1):
            if (
                town.ground[y][x] == int(Tile.GRASS)
                and town.objects[y][x] == 0
                and (x * 17 + y * 31 + seed) % 29 == 0
            ):
                town.ground[y][x] = int(Tile.FLOWERS)

    by_role = {item.role: item for item in town.landmarks}
    actors = spec["actors"]
    town.actor_positions = {
        actors["archivist"]: by_role["archive"].approach,
        actors["cartographer"]: (center_x - 4, center_y + 2),
        actors["duelist"]: by_role["guild"].approach,
    }
    for position in (*town.actor_positions.values(), town.spawn):
        town.blocked.discard(position)
    return town


def _reachable(town: Town) -> set[Coord]:
    queue = deque([town.spawn])
    seen = {town.spawn}
    while queue:
        x, y = queue.popleft()
        for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            nx, ny = neighbor
            if (
                0 <= nx < town.width
                and 0 <= ny < town.height
                and neighbor not in town.blocked
                and neighbor not in seen
            ):
                seen.add(neighbor)
                queue.append(neighbor)
    return seen


def _road_cycle_rank(town: Town) -> int:
    vertices = set(town.roads) - town.blocked
    edges = sum(
        neighbor in vertices
        for x, y in vertices
        for neighbor in ((x + 1, y), (x, y + 1))
    )
    components = 0
    remaining = set(vertices)
    while remaining:
        components += 1
        stack = [remaining.pop()]
        while stack:
            x, y = stack.pop()
            for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    stack.append(neighbor)
    return edges - len(vertices) + components


def _compress_rectangles(cells: set[Coord]) -> list[tuple[int, int, int, int]]:
    active: dict[tuple[int, int], tuple[int, int]] = {}
    output: list[tuple[int, int, int, int]] = []
    max_y = max((y for _, y in cells), default=-1)
    for y in range(max_y + 2):
        xs = sorted(x for x, row in cells if row == y)
        runs: list[tuple[int, int]] = []
        if xs:
            start = previous = xs[0]
            for x in xs[1:]:
                if x != previous + 1:
                    runs.append((start, previous - start + 1))
                    start = x
                previous = x
            runs.append((start, previous - start + 1))
        current = set(runs)
        for run in set(active) - current:
            start_y, run_height = active.pop(run)
            output.append((run[0], start_y, run[1], run_height))
        for run in runs:
            if run in active:
                start_y, run_height = active[run]
                active[run] = (start_y, run_height + 1)
            else:
                active[run] = (y, 1)
    return sorted(
        output, key=lambda item: (item[1], item[0], item[2], item[3])
    )


def _branch_projection_plan(town: Town) -> dict[str, dict[str, Any]]:
    campaign = town.spec.get("campaign", {}).get("selected")
    if not campaign:
        return {}
    reserved = {
        town.spawn,
        town.shard,
        *town.actor_positions.values(),
        *(landmark.approach for landmark in town.landmarks),
    }
    output: dict[str, dict[str, Any]] = {}
    for region in campaign["regions"]:
        if region.get("mechanic") != "survey":
            continue
        for alignment, phenotype in sorted(region["phenotypes"].items()):
            anchor = next(
                landmark
                for landmark in town.landmarks
                if landmark.role == phenotype["anchor_role"]
            )
            candidates = town.roads - town.blocked - reserved
            if not candidates:
                raise AdmissionRejected(
                    f"No free town response cell for {region['slug']}:{alignment}."
                )
            position = min(
                candidates,
                key=lambda cell: (
                    abs(
                        abs(cell[0] - anchor.approach[0])
                        + abs(cell[1] - anchor.approach[1])
                        - 4
                    ),
                    abs(cell[0] - anchor.approach[0])
                    + abs(cell[1] - anchor.approach[1]),
                    cell[1],
                    cell[0],
                ),
            )
            reserved.add(position)
            output[f"{region['slug']}:{alignment}"] = {
                "survey_slug": region["slug"],
                "alignment": alignment,
                "alignment_key": region["alignment_key"],
                "overlay": phenotype["overlay"],
                "anchor_role": phenotype["anchor_role"],
                "echo_actor": region["actor"],
                "echo_position": list(position),
                "echo_event": (
                    f"Read spatial echo {region['slug']}:{alignment}"
                ),
            }
    return output


def certify(
    town: Town, expeditions=None, *, require_ecology_lock: bool = False
) -> dict[str, Any]:
    from foundry.expedition import (
        certify_expedition,
        expedition_events,
        generate_expedition,
    )

    campaign = town.spec.get("campaign", {}).get("selected")
    region_contracts = (
        campaign["regions"] if campaign else [town.spec["expedition"]]
    )
    if expeditions is None:
        expedition_list = [
            generate_expedition(town.spec, contract)
            for contract in region_contracts
        ]
    elif isinstance(expeditions, (list, tuple)):
        expedition_list = list(expeditions)
    else:
        expedition_list = [expeditions]
    expedition_certificates = {
        expedition.slug: certify_expedition(expedition)
        for expedition in expedition_list
    }
    selected_ecologies = [
        expedition.contract.get("ecology", {}).get("selected")
        for expedition in expedition_list
        if expedition.contract.get("mechanic", "combat") == "combat"
    ]
    branch_projection = _branch_projection_plan(town)
    reachable = _reachable(town)
    walkable = {
        (x, y)
        for y in range(town.height)
        for x in range(town.width)
        if (x, y) not in town.blocked
    }
    fraction = len(reachable) / max(1, len(walkable))
    approaches = {item.role: item.approach for item in town.landmarks}
    failures = [
        role for role, cell in approaches.items() if cell not in reachable
    ]
    if (town.shard[0], town.shard[1] + 1) not in reachable:
        failures.append("echo_shard")
    separations = [
        abs(left.x - right.x) + abs(left.y - right.y)
        for index, left in enumerate(town.landmarks)
        for right in town.landmarks[index + 1 :]
    ]
    minimum_separation = min(separations)
    cycle_rank = _road_cycle_rank(town)
    admission = town.spec["admission"]
    threshold = float(admission["minimum_reachable_fraction"])
    required_separation = int(admission["minimum_landmark_separation"])
    quest = town.spec["narrative_automaton"]
    state, witness = quest["initial"], []
    for source, action, target in quest["transitions"]:
        if source != state:
            break
        witness.append(action)
        state = target
    quest_passed = state == quest["terminal"]
    town_events = _world_events(town)
    wild_events_by_slug = {
        expedition.slug: expedition_events(expedition, town)
        for expedition in expedition_list
    }
    regional_events = {
        town.slug: town_events,
        **wild_events_by_slug,
    }
    recovery_role = town.spec["resilience"]["battle_loss"]["recover_at"]
    recovery_event_name = f"Inspect {recovery_role}"
    recovery_event = town_events.get(recovery_event_name, {})
    recovery_compiled = "set_monster_health" in recovery_event.get(
        "actions", []
    )
    roundtrip_failures = []
    for expedition in expedition_list:
        entry_name = f"Enter {expedition.title}"
        return_name = f"Return from {expedition.slug}"
        if (
            entry_name not in town_events
            or f"transition_teleport player,{expedition.slug}.tmx"
            not in " ".join(town_events[entry_name]["actions"])
            or return_name not in wild_events_by_slug[expedition.slug]
            or f"transition_teleport player,{town.slug}.tmx"
            not in " ".join(
                wild_events_by_slug[expedition.slug][return_name]["actions"]
            )
        ):
            roundtrip_failures.append(expedition.slug)
    realized_transitions = []
    missing_transitions = []
    for source, action, target in quest["transitions"]:
        source_condition = f"is variable_set province_stage:{source}"
        target_action = f"set_variable province_stage:{target}"
        matching_events = [
            (region, name)
            for region, events in regional_events.items()
            for name, event in events.items()
            if source_condition in event.get("conditions", [])
            and target_action in event.get("actions", [])
        ]
        if matching_events:
            region, event_name = matching_events[0]
            realized_transitions.append(
                {
                    "transition": action,
                    "event": event_name,
                    "region": region,
                }
            )
        else:
            missing_transitions.append(action)
    proofs = [
        {
            "id": "spawn-is-walkable",
            "passed": town.spawn not in town.blocked,
            "detail": f"Spawn {town.spawn} is outside derived collision geometry.",
            "counterexamples": []
            if town.spawn not in town.blocked
            else [town.spawn],
        },
        {
            "id": "landmarks-reachable",
            "passed": not failures,
            "detail": f"Reached {len(approaches) + 1} required interaction fronts.",
            "counterexamples": failures,
        },
        {
            "id": "walkable-space-connected",
            "passed": fraction >= threshold,
            "detail": (
                f"{len(reachable)}/{len(walkable)} walkable cells connect to spawn "
                f"({fraction:.3f}; required {threshold:.3f})."
            ),
            "counterexamples": []
            if fraction >= threshold
            else ["isolated_cells"],
        },
        {
            "id": "road-network-has-cycle",
            "passed": cycle_rank >= 1,
            "detail": f"Road graph cycle rank is {cycle_rank}.",
            "counterexamples": [] if cycle_rank >= 1 else ["acyclic_roads"],
        },
        {
            "id": "landmarks-separated",
            "passed": minimum_separation >= required_separation,
            "detail": (
                f"Minimum anchor separation is {minimum_separation}; "
                f"required {required_separation}."
            ),
            "counterexamples": (
                []
                if minimum_separation >= required_separation
                else ["crowding"]
            ),
        },
        {
            "id": "quest-has-terminal-witness",
            "passed": quest_passed,
            "detail": f"Witness reaches {state}: {' -> '.join(witness)}.",
            "counterexamples": [] if quest_passed else [state],
        },
        {
            "id": "quest-automaton-compiles-to-events",
            "passed": not missing_transitions,
            "detail": f"Realized {len(realized_transitions)} quest transitions.",
            "counterexamples": missing_transitions,
        },
        {
            "id": "battle-loss-has-reachable-recovery",
            "passed": recovery_role in approaches and recovery_compiled,
            "detail": (
                f"{recovery_event_name} restores the party and its approach "
                "is included in the spatial reachability proof."
            ),
            "counterexamples": (
                []
                if recovery_role in approaches and recovery_compiled
                else [recovery_event_name]
            ),
        },
        {
            "id": "campaign-region-roundtrips-compile",
            "passed": not roundtrip_failures,
            "detail": [
                f"{town.slug} -> {expedition.slug} -> {town.slug}"
                for expedition in expedition_list
            ],
            "counterexamples": roundtrip_failures,
        },
        *(
            [
                {
                    "id": "branch-phenotypes-project-to-distinct-visible-town-states",
                    "passed": all(
                        tuple(projection["echo_position"]) in reachable
                        for projection in branch_projection.values()
                    )
                    and len(
                        {
                            projection["overlay"]
                            for projection in branch_projection.values()
                        }
                    )
                    == len(branch_projection)
                    and len(
                        {
                            tuple(projection["echo_position"])
                            for projection in branch_projection.values()
                        }
                    )
                    == len(branch_projection),
                    "detail": branch_projection,
                    "counterexamples": [
                        key
                        for key, projection in branch_projection.items()
                        if tuple(projection["echo_position"]) not in reachable
                    ],
                }
            ]
            if branch_projection
            else []
        ),
        *(
            [
                {
                    "id": "actual-engine-ecology-selection-is-locked",
                    "passed": all(selected_ecologies)
                    and bool(
                        town.spec.get("campaign", {}).get(
                            "selection_certificate"
                        )
                    ),
                    "detail": selected_ecologies,
                    "counterexamples": (
                        []
                        if all(selected_ecologies)
                        and town.spec.get("campaign", {}).get(
                            "selection_certificate"
                        )
                        else ["missing_campaign_or_ecology_selection"]
                    ),
                }
            ]
            if require_ecology_lock
            else []
        ),
        *[
            proof
            for certificate in expedition_certificates.values()
            for proof in certificate["proofs"]
        ],
    ]
    compiled_semantics = {
        world.slug: {
            "ground": world.ground,
            "objects": world.objects,
            "above": world.above,
            "blocked": sorted(world.blocked),
            "events": events,
        }
        for world, events in [
            (town, town_events),
            *[
                (expedition, wild_events_by_slug[expedition.slug])
                for expedition in expedition_list
            ],
        ]
    }
    seed_genome = copy.deepcopy(town.spec)
    seed_genome["expedition"]["ecology"].pop("selection_certificate", None)
    seed_genome.get("campaign", {}).pop("selection_certificate", None)
    campaign_region_witnesses = []
    for expedition in expedition_list:
        contract = expedition.contract
        region_witness = {
            **expedition_certificates[expedition.slug]["witnesses"],
            "slug": expedition.slug,
            "title": expedition.title,
            "mechanic": contract.get("mechanic", "combat"),
            "entry_state": contract.get("entry_state", "chartered"),
            "complete_state": contract.get(
                "complete_state", "shard_recovered"
            ),
            "recover_action": contract.get(
                "recover_action", "recover_echo_shard"
            ),
            "entry_event": f"Enter {expedition.title}",
            "return_event": f"Return from {expedition.slug}",
        }
        if contract.get("mechanic", "combat") == "combat":
            region_witness.update(
                {
                    "open_state": contract.get("open_state", "wilds_open"),
                    "defeat_action": contract.get(
                        "defeat_action", "defeat_echo_sentinel"
                    ),
                    "sentinel_event": (
                        f"Challenge {expedition.slug} sentinel"
                    ),
                    "ecology": contract.get("ecology", {}).get("selected"),
                    "ecologies": contract.get(
                        "conditional_ecologies", {}
                    ).get("selected", {}),
                }
            )
        else:
            projected_phenotypes = {
                projection["alignment"]: projection
                for projection in branch_projection.values()
                if projection["survey_slug"] == expedition.slug
            }
            region_witness.update(
                {
                    "alignment_key": contract["alignment_key"],
                    "alignment_values": contract["alignment_values"],
                    "observation_keys": contract["observation_keys"],
                    "choice_events": {
                        alignment: f"Choose {alignment} in {expedition.slug}"
                        for alignment in contract["alignment_values"]
                    },
                    "observation_events": [
                        f"Observe horizon in {expedition.slug}",
                        f"Observe root in {expedition.slug}",
                    ],
                    "completion_events": {
                        alignment: (
                            f"Recover {expedition.slug} sigil via {alignment}"
                        )
                        for alignment in contract["alignment_values"]
                    },
                    "consequence_events": {
                        alignment: f"Cartographer responds to {alignment}"
                        for alignment in contract["alignment_values"]
                    },
                    "phenotypes": projected_phenotypes,
                }
            )
        campaign_region_witnesses.append(region_witness)
    body = {
        "schema": "ai-native-admission-certificate/v1",
        "world": town.slug,
        "seed": town.seed,
        "seed_genome_sha256": hashlib.sha256(
            json.dumps(
                seed_genome, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest(),
        "compiled_semantics_sha256": hashlib.sha256(
            json.dumps(
                compiled_semantics, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest(),
        "dimensions": [town.width, town.height],
        "regions": {
            town.slug: {
                "dimensions": [town.width, town.height],
                "events": len(town_events),
            },
            **{
                expedition.slug: {
                    "dimensions": [expedition.width, expedition.height],
                    "events": len(wild_events_by_slug[expedition.slug]),
                    "collision_cells": expedition_certificates[
                        expedition.slug
                    ]["counts"]["collision_cells"],
                }
                for expedition in expedition_list
            },
        },
        "quest": {
            "initial": quest["initial"],
            "terminal": quest["terminal"],
            "transitions": quest["transitions"],
        },
        "counts": {
            "walkable_cells": len(walkable),
            "reachable_cells": len(reachable),
            "collision_cells": len(town.blocked),
            "collision_rectangles": len(_compress_rectangles(town.blocked)),
            "road_cells": len(town.roads),
            "road_cycle_rank": cycle_rank,
            "landmarks": len(town.landmarks),
            "actors": len(town.actor_positions),
            "quest_transitions": len(quest["transitions"]),
            "regions": len(regional_events),
            "runtime_events": sum(map(len, regional_events.values())),
            "regional_collision_cells": sum(
                certificate["counts"]["collision_cells"]
                for certificate in expedition_certificates.values()
            ),
            "regional_repair_cells": sum(
                certificate["counts"]["repair_cells"]
                for certificate in expedition_certificates.values()
            ),
        },
        "witnesses": {
            "quest": witness,
            "quest_event_bindings": realized_transitions,
            "battle_loss_recovery_event": recovery_event_name,
            "landmark_approaches": {
                role: list(cell) for role, cell in sorted(approaches.items())
            },
            "campaign_regions": campaign_region_witnesses,
        },
        "proofs": proofs,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    body["fingerprint"] = hashlib.sha256(canonical.encode()).hexdigest()
    return body


def _tile_atlas(style: dict[str, str], seed: int) -> Image.Image:
    size, columns = 16, 8
    atlas = Image.new("RGBA", (128, 64), (0, 0, 0, 0))
    rng = random.Random(seed)
    images: dict[Tile, Image.Image] = {}

    def canvas(
        background: str | None = None,
    ) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        image = Image.new("RGBA", (size, size), background or (0, 0, 0, 0))
        return image, ImageDraw.Draw(image)

    image, draw = canvas(style["grass"])
    for _ in range(12):
        x, y = rng.randrange(size), rng.randrange(size)
        color = style["grass_light"] if (x + y) % 2 else style["grass_dark"]
        draw.point((x, y), fill=color)
    images[Tile.GRASS] = image
    image = image.copy()
    draw = ImageDraw.Draw(image)
    for point, color in (
        ((4, 5), "#f5d76e"),
        ((11, 10), "#f4a5c4"),
        ((3, 12), "#d7eef2"),
    ):
        draw.point(point, fill=color)
    images[Tile.FLOWERS] = image

    image, draw = canvas(style["path"])
    for point in ((2, 3), (12, 4), (7, 9), (14, 13), (3, 14)):
        draw.point(point, fill=style["path_dark"])
    images[Tile.PATH] = image
    image, draw = canvas(style["stone"])
    for y in range(0, size, 5):
        draw.line((0, y, 15, y), fill=style["stone_dark"])
        x = 4 if (y // 5) % 2 else 9
        draw.line((x, y, x, min(15, y + 4)), fill=style["stone_dark"])
    images[Tile.PLAZA] = image
    for tile, offset in ((Tile.WATER, 0), (Tile.WATER_LIGHT, 3)):
        image, draw = canvas(style["water"])
        for y in (3 + offset % 2, 9, 14):
            draw.line(
                (offset, y, min(15, offset + 8), y), fill=style["water_light"]
            )
        images[tile] = image

    image, draw = canvas()
    draw.rectangle((7, 10, 9, 15), fill="#68452e")
    draw.ellipse(
        (1, 1, 14, 13), fill=style["grass_dark"], outline=style["ink"]
    )
    draw.ellipse((4, 0, 11, 7), fill=style["grass_light"])
    images[Tile.TREE] = image
    image, draw = canvas()
    draw.rectangle(
        (0, 5, 15, 15), fill=style["grass_dark"], outline=style["ink"]
    )
    images[Tile.HEDGE] = image

    def roofs(color: str, light: str, first: Tile) -> None:
        for offset, tile in enumerate(
            (first, Tile(first + 1), Tile(first + 2))
        ):
            roof, roof_draw = canvas(color)
            for y in (3, 8, 13):
                roof_draw.line((0, y, 15, y), fill=light)
            if offset == 0:
                roof_draw.line((0, 0, 0, 15), fill=style["ink"], width=2)
            if offset == 2:
                roof_draw.line((15, 0, 15, 15), fill=style["ink"], width=2)
            images[tile] = roof

    roofs(style["roof_amber"], style["roof_amber_light"], Tile.ROOF_AMBER_LEFT)
    roofs(
        style["roof_indigo"], style["roof_indigo_light"], Tile.ROOF_INDIGO_LEFT
    )

    def facade(tile: Tile, color: str, feature: str) -> None:
        wall, wall_draw = canvas(color)
        wall_draw.line((0, 0, 15, 0), fill=style["ink"])
        if feature == "window":
            wall_draw.rectangle(
                (4, 4, 11, 11), fill="#8ed0d5", outline=style["ink"]
            )
            wall_draw.line((8, 4, 8, 11), fill=style["ink"])
        if feature == "door":
            wall_draw.rectangle(
                (4, 3, 12, 15), fill="#67483c", outline=style["ink"]
            )
            wall_draw.point((10, 9), fill="#f6d26b")
        images[tile] = wall

    for tile, color, feature in (
        (Tile.WALL_AMBER, style["wall"], "wall"),
        (Tile.WINDOW_AMBER, style["wall"], "window"),
        (Tile.DOOR_AMBER, style["wall"], "door"),
        (Tile.WALL_INDIGO, style["wall_blue"], "wall"),
        (Tile.WINDOW_INDIGO, style["wall_blue"], "window"),
        (Tile.DOOR_INDIGO, style["wall_blue"], "door"),
    ):
        facade(tile, color, feature)

    image, draw = canvas()
    draw.rectangle((1, 5, 14, 13), fill="#f0d2a3", outline=style["ink"])
    images[Tile.AWNING] = image
    image, draw = canvas("#8c5d3b")
    for x in range(1, 16, 4):
        draw.line((x, 0, x, 15), fill="#c69056")
    draw.line((0, 1, 15, 1), fill=style["ink"])
    draw.line((0, 14, 15, 14), fill=style["ink"])
    images[Tile.BRIDGE] = image
    image, draw = canvas()
    draw.ellipse((1, 6, 14, 15), fill=style["stone"], outline=style["ink"])
    draw.ellipse((3, 8, 12, 13), fill=style["water_light"])
    draw.rectangle((7, 1, 9, 10), fill=style["stone_dark"])
    images[Tile.FOUNTAIN] = image
    image, draw = canvas()
    draw.rectangle((3, 12, 13, 15), fill=style["stone_dark"])
    draw.polygon(
        (8, 1, 12, 8, 8, 13, 4, 8), fill="#8de0dc", outline=style["ink"]
    )
    images[Tile.STATUE] = image
    image, draw = canvas()
    draw.rectangle((2, 3, 13, 10), fill="#b77a45", outline=style["ink"])
    draw.rectangle((7, 10, 9, 15), fill="#69462d")
    images[Tile.SIGN] = image
    image, draw = canvas("#795a3d")
    for x in (3, 8, 13):
        draw.line((x, 1, x, 14), fill=style["grass_light"])
    images[Tile.GARDEN] = image
    image, draw = canvas()
    draw.rectangle((7, 6, 8, 15), fill=style["ink"])
    draw.rectangle((4, 1, 11, 7), fill="#ffe28a", outline=style["ink"])
    images[Tile.LAMP] = image
    image, draw = canvas()
    draw.rectangle((2, 7, 13, 14), fill="#8e5a3c", outline=style["ink"])
    for x in range(1, 15, 4):
        draw.rectangle((x, 2, min(x + 2, 14), 7), fill="#efc759")
    images[Tile.STALL] = image

    for tile in Tile:
        index = int(tile) - 1
        image = images.get(tile, Image.new("RGBA", (size, size), (0, 0, 0, 0)))
        atlas.alpha_composite(
            image, ((index % columns) * size, (index // columns) * size)
        )
    return atlas


def _tmx_layer(
    parent: ET.Element, layer_id: int, name: str, rows: list[list[int]]
) -> None:
    layer = ET.SubElement(
        parent,
        "layer",
        {
            "id": str(layer_id),
            "name": name,
            "width": str(len(rows[0])),
            "height": str(len(rows)),
        },
    )
    data = ET.SubElement(layer, "data", {"encoding": "csv"})
    data.text = (
        "\n"
        + ",\n".join(",".join(str(value) for value in row) for row in rows)
        + "\n"
    )


def _write_tmx(town: Town, path: Path) -> None:
    root = ET.Element(
        "map",
        {
            "version": "1.10",
            "tiledversion": "1.11.0",
            "orientation": "orthogonal",
            "renderorder": "right-down",
            "width": str(town.width),
            "height": str(town.height),
            "tilewidth": "16",
            "tileheight": "16",
            "infinite": "0",
            "nextlayerid": "4",
            "nextobjectid": "1",
        },
    )
    properties = ET.SubElement(root, "properties")
    for name, value in (
        ("edges", "clamped"),
        ("map_type", getattr(town, "map_type", "town")),
        ("slug", town.slug),
    ):
        ET.SubElement(properties, "property", {"name": name, "value": value})
    ET.SubElement(
        root,
        "tileset",
        {"firstgid": "1", "source": f"../gfx/tilesets/{town.slug}.tsx"},
    )
    _tmx_layer(root, 1, "Ground", town.ground)
    _tmx_layer(root, 2, "Objects", town.objects)
    _tmx_layer(root, 3, "Above Player", town.above)
    ET.indent(root, space=" ")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _write_tsx(town: Town, path: Path) -> None:
    root = ET.Element(
        "tileset",
        {
            "version": "1.10",
            "tiledversion": "1.11.0",
            "name": town.slug,
            "tilewidth": "16",
            "tileheight": "16",
            "tilecount": "32",
            "columns": "8",
        },
    )
    ET.SubElement(
        root,
        "image",
        {"source": f"{town.slug}.png", "width": "128", "height": "64"},
    )
    ET.indent(root, space=" ")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _landmark_event(
    landmark: Landmark, recovery_role: str
) -> dict[str, Any]:
    x, y = landmark.door
    title = landmark.role.replace("_", " ").title()
    actions = [
        f"translated_dialog {title}. Its sealed door hums with map-light."
    ]
    if landmark.role == recovery_role:
        actions = [
            "translated_dialog The clinic tunes every tired creature back to its remembered shape.",
            "set_monster_health",
        ]
    return {
        "type": "event",
        "x": x,
        "y": y,
        "conditions": [
            "is char_facing_tile player",
            "is button_pressed INTERACT",
        ],
        "actions": actions,
    }


def _world_events(town: Town) -> dict[str, Any]:
    actors = town.spec["actors"]
    recovery_role = town.spec["resilience"]["battle_loss"]["recover_at"]
    archivist, cartographer, duelist = (
        actors["archivist"],
        actors["cartographer"],
        actors["duelist"],
    )
    events: dict[str, Any] = {}
    selected_campaign = town.spec.get("campaign", {}).get("selected")
    branch_projection = _branch_projection_plan(town)
    duel_source_state = (
        selected_campaign.get("duel_source_state", "archive_restored")
        if selected_campaign
        else "shard_recovered"
    )
    for slug, position in sorted(town.actor_positions.items()):
        events[f"Materialize {slug}"] = {
            "type": "event",
            "conditions": [f"not char_exists {slug}"],
            "actions": [f"create_npc {slug},{position[0]},{position[1]}"],
        }
    for alignment_key in sorted(
        {item["alignment_key"] for item in branch_projection.values()}
    ):
        events[f"Clear unaligned projection for {alignment_key}"] = {
            "type": "init",
            "conditions": [f"not variable_set {alignment_key}"],
            "actions": ["set_layer none"],
        }
    for key, projection in sorted(branch_projection.items()):
        alignment = projection["alignment"]
        alignment_key = projection["alignment_key"]
        actor = projection["echo_actor"]
        position = projection["echo_position"]
        events[f"Project visible phenotype {key}"] = {
            "type": "init",
            "conditions": [
                f"is variable_set {alignment_key}:{alignment}"
            ],
            "actions": [f"set_layer {projection['overlay']}"],
        }
        events[f"Materialize spatial echo {key}"] = {
            "type": "event",
            "conditions": [
                f"is variable_set {alignment_key}:{alignment}",
                f"not char_exists {actor}",
            ],
            "actions": [
                f"create_npc {actor},{position[0]},{position[1]}"
            ],
        }
        events[projection["echo_event"]] = {
            "type": "event",
            "behav": [f"talk {actor}"],
            "conditions": [
                f"is variable_set {alignment_key}:{alignment}"
            ],
            "actions": [
                f"translated_dialog The {alignment} echo has occupied a different place in town."
            ],
        }
    events["Initialize semantic slice"] = {
        "type": "event",
        "conditions": ["not variable_set foundry_initialized"],
        "actions": [
            "set_environment grass",
            (
                "add_monster "
                f"{actors['starter_monster']},{actors['starter_level']}"
            ),
            "set_variable province_stage:arrival",
            "set_variable foundry_initialized:yes",
            "translated_dialog The province has no map yet. Find the archivist beneath the northern slate roof.",
        ],
    }
    events["Arm the duelist"] = {
        "type": "event",
        "conditions": [
            f"is char_exists {duelist}",
            f"is party_size {duelist},equals,0",
        ],
        "actions": [
            (
                "add_monster "
                f"{actors['duelist_monster']},{actors['duelist_level']},"
                f"{duelist}"
            ),
        ],
    }
    events["Archivist offers charter"] = {
        "type": "event",
        "behav": [f"talk {archivist}"],
        "conditions": ["is variable_set province_stage:arrival"],
        "actions": [
            "translated_dialog Three missing sigils keep the province from remembering itself. The eastern gate will compile one route at a time.",
            "set_variable province_stage:chartered",
        ],
    }
    events["Archivist reminder"] = {
        "type": "event",
        "behav": [f"talk {archivist}"],
        "conditions": ["is variable_set province_stage:chartered"],
        "actions": [
            "translated_dialog Begin at the eastern gate. Survive each region, recover its sigil, and return for the next."
        ],
    }
    shard_x, shard_y = town.shard
    region_contracts = (
        selected_campaign["regions"]
        if selected_campaign
        else [town.spec["expedition"]]
    )
    for region in region_contracts:
        spawn = (3, int(region["geometry"]["height"]) // 2)
        entry_state = region.get("entry_state", "chartered")
        open_state = region.get("open_state", "wilds_open")
        events[f"Enter {region['title']}"] = {
            "type": "event",
            "x": shard_x,
            "y": shard_y,
            "conditions": [
                "is char_facing_tile player",
                "is button_pressed INTERACT",
                f"is variable_set province_stage:{entry_state}",
            ],
            "actions": [
                f"translated_dialog The gate compiles {region['title']} from the next unresolved promise.",
                (
                    "transition_teleport player,"
                    f"{region['slug']}.tmx,{spawn[0]},{spawn[1]},0.3"
                ),
            ],
        }
        if region.get("mechanic", "combat") == "combat":
            events[f"Reenter {region['title']}"] = {
                "type": "event",
                "x": shard_x,
                "y": shard_y,
                "conditions": [
                    "is char_facing_tile player",
                    "is button_pressed INTERACT",
                    f"is variable_set province_stage:{open_state}",
                ],
                "actions": [
                    (
                        "transition_teleport player,"
                        f"{region['slug']}.tmx,{spawn[0]},{spawn[1]},0.3"
                    ),
                ],
            }
    survey_region = next(
        (
            region
            for region in region_contracts
            if region.get("mechanic") == "survey"
        ),
        None,
    )
    events["Cartographer observes"] = {
        "type": "event",
        "behav": [f"talk {cartographer}"],
        "conditions": (
            [f"not variable_set {survey_region['alignment_key']}"]
            if survey_region
            else []
        ),
        "actions": [
            "translated_dialog This town was compiled from promises. Its walls are consequences rather than drawings."
        ],
    }
    if survey_region:
        for alignment in survey_region["alignment_values"]:
            events[f"Cartographer responds to {alignment}"] = {
                "type": "event",
                "behav": [f"talk {cartographer}"],
                "conditions": [
                    f"is variable_set {survey_region['alignment_key']}:{alignment}"
                ],
                "actions": [
                    f"translated_dialog Your {alignment} survey changed what the atlas believes about every later path."
                ],
            }
    events["Duel for the map seal"] = {
        "type": "event",
        "behav": [f"talk {duelist}"],
        "conditions": [
            "is variable_set province_stage:"
            + duel_source_state,
            f"not char_defeated {duelist}",
        ],
        "actions": [
            "translated_dialog A map is only true if it survives resistance. Show me your turncraft.",
            f"start_battle player,{duelist}",
        ],
    }
    events["Record duel victory"] = {
        "type": "event",
        "conditions": [
            f"is battle_outcome player,won,{duelist}",
            "is current_state WorldState",
            f"is variable_set province_stage:{duel_source_state}",
        ],
        "actions": [
            "translated_dialog The map seal answers. Return to the archivist.",
            "set_variable province_stage:trial_won",
        ],
    }
    events["Archivist completes map"] = {
        "type": "event",
        "behav": [f"talk {archivist}"],
        "conditions": ["is variable_set province_stage:trial_won"],
        "actions": [
            "translated_dialog The province remembers its name. You are its first true Cartographer.",
            "set_variable province_stage:province_mapped",
        ],
    }
    events["Archivist epilogue"] = {
        "type": "event",
        "behav": [f"talk {archivist}"],
        "conditions": ["is variable_set province_stage:province_mapped"],
        "actions": [
            "translated_dialog The atlas is complete. Walk freely; every path you proved remains open."
        ],
    }
    for landmark in town.landmarks:
        events[f"Inspect {landmark.role}"] = _landmark_event(
            landmark, recovery_role
        )
    return events


def _render_preview(town: Town, atlas: Image.Image, path: Path) -> None:
    canvas = Image.new(
        "RGBA", (town.width * 16, town.height * 16), (0, 0, 0, 255)
    )
    for layer in (town.ground, town.objects, town.above):
        for y, row in enumerate(layer):
            for x, gid in enumerate(row):
                if not gid:
                    continue
                index = gid - 1
                box = (
                    (index % 8) * 16,
                    (index // 8) * 16,
                    (index % 8 + 1) * 16,
                    (index // 8 + 1) * 16,
                )
                canvas.alpha_composite(atlas.crop(box), (x * 16, y * 16))
    draw = ImageDraw.Draw(canvas)
    sx, sy = town.spawn
    draw.ellipse(
        (sx * 16 + 4, sy * 16 + 3, sx * 16 + 12, sy * 16 + 13),
        fill="#f8f3d4",
        outline=town.style["ink"],
        width=2,
    )
    canvas.resize(
        (town.width * 32, town.height * 32), Image.Resampling.NEAREST
    ).save(path)


def compile_world(
    root: Path,
    spec_path: Path | None = None,
    output_root: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    spec_path = (
        spec_path
        or root / "foundry" / "worlds" / "unmapped_province.seed.yaml"
    )
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    ecology_lock = (
        root / "foundry" / "worlds" / "echo_wilds.ecology.lock.json"
    )
    ecology_selection = None
    if ecology_lock.is_file():
        ecology_selection = json.loads(
            ecology_lock.read_text(encoding="utf-8")
        )
        selection_body = dict(ecology_selection)
        expected_fingerprint = selection_body.pop("fingerprint", None)
        observed_fingerprint = hashlib.sha256(
            json.dumps(
                selection_body, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        if expected_fingerprint != observed_fingerprint:
            raise AdmissionRejected("The ecology lock fingerprint is invalid.")
        if not all(
            proof["passed"]
            for proof in ecology_selection.get("proofs", [])
        ):
            raise AdmissionRejected("The ecology lock contains failed proofs.")
        ecology = spec["expedition"]["ecology"]
        ecology["selected"] = ecology_selection["selected"]
        ecology["selection_certificate"] = ecology_selection["fingerprint"]

    campaign_lock = root / "foundry" / "worlds" / "campaign.lock.json"
    if not campaign_lock.is_file():
        raise AdmissionRejected("The campaign selection lock is missing.")
    campaign_selection = json.loads(
        campaign_lock.read_text(encoding="utf-8")
    )
    campaign_body = dict(campaign_selection)
    campaign_fingerprint = campaign_body.pop("fingerprint", None)
    observed_campaign_fingerprint = hashlib.sha256(
        json.dumps(
            campaign_body, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    if campaign_fingerprint != observed_campaign_fingerprint:
        raise AdmissionRejected("The campaign lock fingerprint is invalid.")
    if not all(
        proof["passed"] for proof in campaign_selection.get("proofs", [])
    ):
        raise AdmissionRejected("The campaign lock contains failed proofs.")
    if (
        ecology_selection is None
        or campaign_selection.get("ecology_fingerprint")
        != ecology_selection.get("fingerprint")
    ):
        raise AdmissionRejected("Campaign and ecology locks disagree.")
    spec["campaign"]["selected"] = campaign_selection["selected"]
    spec["campaign"]["selection_certificate"] = campaign_fingerprint
    spec["narrative_automaton"] = campaign_selection["selected"][
        "narrative_automaton"
    ]
    town = generate_town(spec)
    from foundry.expedition import expedition_events, generate_expedition

    expeditions = [
        generate_expedition(spec, contract)
        for contract in campaign_selection["selected"]["regions"]
    ]
    certificate = certify(town, expeditions, require_ecology_lock=True)
    failures = [
        proof for proof in certificate["proofs"] if not proof["passed"]
    ]
    if failures:
        raise AdmissionRejected(json.dumps(failures, indent=2))

    output_root = output_root or root / "mods" / town.slug
    maps = output_root / "maps"
    tilesets = output_root / "gfx" / "tilesets"
    artifacts = root / "foundry" / "artifacts"
    maps.mkdir(parents=True, exist_ok=True)
    tilesets.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)
    worlds = [
        (town, _world_events(town)),
        *[
            (expedition, expedition_events(expedition, town))
            for expedition in expeditions
        ],
    ]
    preview_paths: dict[str, str] = {}
    for world, events in worlds:
        atlas = _tile_atlas(world.style, world.seed)
        atlas.save(tilesets / f"{world.slug}.png")
        _write_tsx(world, tilesets / f"{world.slug}.tsx")
        _write_tmx(world, maps / f"{world.slug}.tmx")
        collisions = [
            {
                "type": "collision",
                "x": x,
                "y": y,
                "width": width,
                "height": height,
            }
            for x, y, width, height in _compress_rectangles(world.blocked)
        ]
        (maps / f"{world.slug}.yaml").write_text(
            yaml.safe_dump(
                {"collisions": collisions, "events": events},
                sort_keys=False,
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        preview_path = artifacts / f"{world.slug}.preview.generated.png"
        _render_preview(world, atlas, preview_path)
        preview_paths[world.slug] = preview_path.as_posix()
    (output_root / "mod.yaml").write_text(
        yaml.safe_dump(
            {
                "slug": town.slug,
                "description": "A proof-carrying multi-region RPG compiled by the AI-native foundry.",
                "name": town.title,
                "version": "0.7.0",
                "authors": ["AI Native Foundry"],
                "startup_rules": [],
                "starting_players": ["npc_red"],
                "starting_map": f"{town.slug}.tmx",
                "starting_position": list(town.spawn),
                "starting_money": [120, 120],
                "starting_names": ["Cartographer"],
                "sprite": "adventurer",
                "combat_sheet": "adventurer",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    certificate_path = artifacts / f"{town.slug}.admission.generated.json"
    certificate_path.write_text(
        json.dumps(certificate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "foundry-admission.json").write_text(
        json.dumps(certificate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "mod": output_root.as_posix(),
        "map": (maps / f"{town.slug}.tmx").as_posix(),
        "maps": [
            (maps / f"{world.slug}.tmx").as_posix()
            for world, _ in worlds
        ],
        "preview": preview_paths[town.slug],
        "previews": preview_paths,
        "certificate": certificate_path.as_posix(),
        "fingerprint": certificate["fingerprint"],
        "counts": certificate["counts"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compile a proof-carrying Tuxemon town."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(compile_world(args.root, args.spec, args.output), indent=2)
    )


if __name__ == "__main__":
    main()
