# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import colorsys
import random
from dataclasses import dataclass
from typing import Any

from foundry.town import (
    Coord,
    Tile,
    Town,
    _blank,
    _compress_rectangles,
    _paint,
    _reachable,
    _road_cycle_rank,
)


@dataclass
class Expedition:
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
    landmarks: list[Any]
    spawn: Coord
    shard: Coord
    actor_positions: dict[str, Coord]
    style: dict[str, str]
    spec: dict[str, Any]
    map_type: str
    return_gate: Coord
    repaired_cells: int


def _mutate_style(style: dict[str, str], seed: int) -> dict[str, str]:
    """Project a related palette from the parent style without new artwork."""
    output: dict[str, str] = {}
    hue_shift = 0.055 + (seed % 17) / 1000
    for name, value in style.items():
        red, green, blue = (
            int(value[index : index + 2], 16) / 255
            for index in (1, 3, 5)
        )
        hue, saturation, brightness = colorsys.rgb_to_hsv(red, green, blue)
        hue = (hue + hue_shift) % 1.0
        saturation = min(1.0, saturation * 1.18 + 0.04)
        brightness = max(0.14, brightness * 0.82)
        red, green, blue = colorsys.hsv_to_rgb(hue, saturation, brightness)
        red_byte, green_byte, blue_byte = (
            round(red * 255),
            round(green * 255),
            round(blue * 255),
        )
        output[name] = f"#{red_byte:02x}{green_byte:02x}{blue_byte:02x}"
    return output


def generate_expedition(spec: dict[str, Any]) -> Expedition:
    contract = spec["expedition"]
    geometry = contract["geometry"]
    width, height = int(geometry["width"]), int(geometry["height"])
    if width < 32 or height < 24:
        raise ValueError("The expedition grammar requires at least 32x24 cells.")
    seed = int(spec["identity"]["seed"]) + int(contract["seed_offset"])
    rng = random.Random(seed)
    center_y = height // 2
    entry = (3, center_y)
    return_gate = (1, center_y)

    expedition = Expedition(
        slug=str(contract["slug"]),
        title=str(contract["title"]),
        seed=seed,
        width=width,
        height=height,
        ground=_blank(width, height, int(Tile.GRASS)),
        objects=_blank(width, height),
        above=_blank(width, height),
        blocked=set(),
        roads=set(),
        landmarks=[],
        spawn=entry,
        shard=(0, 0),
        actor_positions={},
        style=_mutate_style(dict(spec["style_genome"]), seed),
        spec=spec,
        map_type="route",
        return_gate=return_gate,
        repaired_cells=0,
    )

    expedition.blocked.update(
        (x, y) for x in range(width) for y in (0, height - 1)
    )
    expedition.blocked.update(
        (x, y) for y in range(height) for x in (0, width - 1)
    )

    # A stochastic central trace is intersected by a rectangular echo circuit.
    # Their overlap guarantees a loop while retaining seed-specific topology.
    trace_y = center_y
    for x in range(1, width - 1):
        if x % 5 == 0:
            trace_y = max(
                center_y - 3,
                min(center_y + 3, trace_y + rng.choice((-1, 0, 1))),
            )
        _paint(expedition.roads, x, trace_y - 1, 1, 3)
    ring_left, ring_right = 10, width - 11
    ring_top, ring_bottom = center_y - 8, center_y + 8
    _paint(
        expedition.roads,
        ring_left,
        ring_top,
        ring_right - ring_left + 1,
        2,
    )
    _paint(
        expedition.roads,
        ring_left,
        ring_bottom,
        ring_right - ring_left + 1,
        2,
    )
    _paint(
        expedition.roads,
        ring_left,
        ring_top,
        2,
        ring_bottom - ring_top + 1,
    )
    _paint(
        expedition.roads,
        ring_right,
        ring_top,
        2,
        ring_bottom - ring_top + 1,
    )
    expedition.shard = (width - 4, trace_y)
    _paint(expedition.roads, width - 7, trace_y - 1, 5, 3)
    _paint(expedition.roads, 1, center_y - 1, 4, 3)

    for x, y in expedition.roads:
        if 0 < x < width - 1 and 0 < y < height - 1:
            expedition.ground[y][x] = int(Tile.PATH)
            expedition.blocked.discard((x, y))

    protected = set(expedition.roads)
    density = float(geometry["obstacle_density"])
    candidates = [
        (x, y)
        for y in range(1, height - 1)
        for x in range(1, width - 1)
        if (x, y) not in protected
    ]
    rng.shuffle(candidates)
    target = int(width * height * density)
    trees: list[Coord] = []
    for cell in candidates:
        if any(
            abs(cell[0] - x) <= 1 and abs(cell[1] - y) <= 1
            for x, y in trees
        ):
            continue
        trees.append(cell)
        expedition.objects[cell[1]][cell[0]] = int(Tile.TREE)
        expedition.blocked.add(cell)
        if len(trees) >= target:
            break

    for y in range(1, height - 1):
        for x in range(1, width - 1):
            if (
                expedition.ground[y][x] == int(Tile.GRASS)
                and expedition.objects[y][x] == 0
                and (x * 23 + y * 41 + seed) % 19 == 0
            ):
                expedition.ground[y][x] = int(Tile.FLOWERS)

    # Smallest-atom repair: any pocket isolated by the sampled forest becomes
    # solid vegetation instead of forcing a designer to reconnect it by hand.
    reachable = _reachable(expedition)  # type: ignore[arg-type]
    repaired = 0
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            cell = (x, y)
            if cell not in expedition.blocked and cell not in reachable:
                expedition.objects[y][x] = int(Tile.TREE)
                expedition.blocked.add(cell)
                repaired += 1
    expedition.repaired_cells = repaired

    shrine_x, shrine_y = expedition.shard
    expedition.objects[shrine_y][shrine_x] = int(Tile.STATUE)
    expedition.blocked.add(expedition.shard)
    expedition.objects[return_gate[1]][return_gate[0]] = int(Tile.STATUE)
    expedition.blocked.add(return_gate)
    expedition.blocked.discard(expedition.spawn)
    return expedition


def expedition_events(
    expedition: Expedition, town: Town
) -> dict[str, dict[str, Any]]:
    shrine_x, shrine_y = expedition.shard
    return_x, return_y = expedition.return_gate
    town_return = (town.shard[0], town.shard[1] + 1)
    ecology = expedition.spec["expedition"]["ecology"]
    selected = ecology.get(
        "selected",
        {
            "monster": "aardorn",
            "level": min(map(int, ecology["levels"])),
        },
    )
    sentinel = str(ecology["actor"])
    sentinel_position = min(
        expedition.roads,
        key=lambda cell: (
            abs(cell[0] - expedition.width // 2)
            + abs(cell[1] - expedition.height // 2),
            cell,
        ),
    )
    return {
        "Initialize echo wilds": {
            "type": "event",
            "conditions": ["not variable_set echo_wilds_initialized"],
            "actions": [
                "set_environment grass",
                "set_variable echo_wilds_initialized:yes",
            ],
        },
        "Materialize echo sentinel": {
            "type": "event",
            "conditions": [f"not char_exists {sentinel}"],
            "actions": [
                f"create_npc {sentinel},{sentinel_position[0]},{sentinel_position[1]}"
            ],
        },
        "Arm echo sentinel": {
            "type": "event",
            "conditions": [
                f"is char_exists {sentinel}",
                f"is party_size {sentinel},equals,0",
            ],
            "actions": [
                "add_monster "
                f"{selected['monster']},{selected['level']},{sentinel}"
            ],
        },
        "Challenge echo sentinel": {
            "type": "event",
            "behav": [f"talk {sentinel}"],
            "conditions": [
                "is variable_set province_stage:chartered",
                f"not char_defeated {sentinel}",
            ],
            "actions": [
                "translated_dialog The forest has chosen its own answer. Pass through it, not around it.",
                f"start_battle player,{sentinel}",
            ],
        },
        "Record echo sentinel victory": {
            "type": "event",
            "conditions": [
                f"is battle_outcome player,won,{sentinel}",
                "is current_state WorldState",
                "is variable_set province_stage:chartered",
            ],
            "actions": [
                "translated_dialog The sentinel yields. The eastern circuit opens toward the shard.",
                "set_variable province_stage:wilds_open",
            ],
        },
        "Echo sentinel remembers": {
            "type": "event",
            "behav": [f"talk {sentinel}"],
            "conditions": ["is variable_set province_stage:wilds_open"],
            "actions": [
                "translated_dialog The path ahead is yours because you survived its reply."
            ],
        },
        "Recover echo shard": {
            "type": "event",
            "x": shrine_x,
            "y": shrine_y,
            "conditions": [
                "is char_facing_tile player",
                "is button_pressed INTERACT",
                "is variable_set province_stage:wilds_open",
            ],
            "actions": [
                "translated_dialog The wild circuit resolves into one memory: every path can return.",
                "set_variable province_stage:shard_recovered",
            ],
        },
        "Echo shrine remembered": {
            "type": "event",
            "x": shrine_x,
            "y": shrine_y,
            "conditions": [
                "is char_facing_tile player",
                "is button_pressed INTERACT",
                "is variable_set province_stage:shard_recovered",
            ],
            "actions": [
                "translated_dialog The empty shrine points west, toward the monolith that remembers home."
            ],
        },
        "Return to Unmapped Province": {
            "type": "event",
            "x": return_x,
            "y": return_y,
            "conditions": [
                "is char_facing_tile player",
                "is button_pressed INTERACT",
            ],
            "actions": [
                "translated_dialog The monolith folds the Echo Wilds back into town.",
                (
                    "transition_teleport player,"
                    f"{town.slug}.tmx,{town_return[0]},{town_return[1]},0.3"
                ),
            ],
        },
    }


def certify_expedition(expedition: Expedition) -> dict[str, Any]:
    reachable = _reachable(expedition)  # type: ignore[arg-type]
    walkable = {
        (x, y)
        for y in range(expedition.height)
        for x in range(expedition.width)
        if (x, y) not in expedition.blocked
    }
    shrine_fronts = {
        (expedition.shard[0] - 1, expedition.shard[1]),
        (expedition.shard[0] + 1, expedition.shard[1]),
        (expedition.shard[0], expedition.shard[1] - 1),
        (expedition.shard[0], expedition.shard[1] + 1),
    }
    return_front = (expedition.return_gate[0] + 1, expedition.return_gate[1])
    sentinel_position = min(
        expedition.roads,
        key=lambda cell: (
            abs(cell[0] - expedition.width // 2)
            + abs(cell[1] - expedition.height // 2),
            cell,
        ),
    )
    fraction = len(reachable) / max(1, len(walkable))
    threshold = float(
        expedition.spec["expedition"]["admission"][
            "minimum_reachable_fraction"
        ]
    )
    cycle_rank = _road_cycle_rank(expedition)  # type: ignore[arg-type]
    proofs = [
        {
            "id": "expedition-entry-is-walkable",
            "passed": expedition.spawn in reachable,
            "detail": list(expedition.spawn),
            "counterexamples": []
            if expedition.spawn in reachable
            else [list(expedition.spawn)],
        },
        {
            "id": "expedition-shrine-is-reachable",
            "passed": bool(shrine_fronts & reachable),
            "detail": sorted(shrine_fronts & reachable),
            "counterexamples": []
            if shrine_fronts & reachable
            else [list(expedition.shard)],
        },
        {
            "id": "expedition-return-is-reachable",
            "passed": return_front in reachable,
            "detail": list(return_front),
            "counterexamples": []
            if return_front in reachable
            else [list(return_front)],
        },
        {
            "id": "expedition-sentinel-is-reachable",
            "passed": sentinel_position in reachable,
            "detail": list(sentinel_position),
            "counterexamples": []
            if sentinel_position in reachable
            else [list(sentinel_position)],
        },
        {
            "id": "expedition-walkable-space-connected",
            "passed": fraction >= threshold,
            "detail": (
                f"{len(reachable)}/{len(walkable)} cells connect to entry "
                f"({fraction:.3f}; required {threshold:.3f})."
            ),
            "counterexamples": []
            if fraction >= threshold
            else ["isolated_cells"],
        },
        {
            "id": "expedition-road-network-has-cycle",
            "passed": cycle_rank >= 1,
            "detail": f"Expedition route cycle rank is {cycle_rank}.",
            "counterexamples": [] if cycle_rank >= 1 else ["acyclic_route"],
        },
    ]
    return {
        "counts": {
            "walkable_cells": len(walkable),
            "reachable_cells": len(reachable),
            "collision_cells": len(expedition.blocked),
            "collision_rectangles": len(
                _compress_rectangles(expedition.blocked)
            ),
            "road_cells": len(expedition.roads),
            "road_cycle_rank": cycle_rank,
            "repair_cells": expedition.repaired_cells,
        },
        "proofs": proofs,
        "witnesses": {
            "spawn": list(expedition.spawn),
            "shrine": list(expedition.shard),
            "return_gate": list(expedition.return_gate),
            "sentinel": list(sentinel_position),
        },
    }
