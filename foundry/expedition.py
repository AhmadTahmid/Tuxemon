# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import colorsys
import itertools
import random
from collections import deque
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
    contract: dict[str, Any]
    map_type: str
    return_gate: Coord
    repaired_cells: int
    survey_sites: dict[str, Coord]
    sentinel_positions: dict[str, Coord]
    sentinel_population: dict[str, int]


def _mutate_style(
    style: dict[str, str], seed: int, hue_shift: float | None = None
) -> dict[str, str]:
    """Project a related palette from the parent style without new artwork."""
    output: dict[str, str] = {}
    hue_shift = (
        float(hue_shift)
        if hue_shift is not None
        else 0.055 + (seed % 17) / 1000
    )
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


def _distances_from(
    expedition: Expedition, start: Coord
) -> dict[Coord, int]:
    distances = {start: 0}
    queue = deque([start])
    while queue:
        x, y = queue.popleft()
        for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            nx, ny = neighbor
            if (
                0 <= nx < expedition.width
                and 0 <= ny < expedition.height
                and neighbor not in expedition.blocked
                and neighbor not in distances
            ):
                distances[neighbor] = distances[(x, y)] + 1
                queue.append(neighbor)
    return distances


def _synthesize_sentinel_positions(
    expedition: Expedition,
) -> tuple[dict[str, Coord], dict[str, int]]:
    central = min(
        expedition.roads,
        key=lambda cell: (
            abs(cell[0] - expedition.width // 2)
            + abs(cell[1] - expedition.height // 2),
            cell,
        ),
    )
    conditional = expedition.contract.get("conditional_ecologies")
    if not conditional:
        return {"default": central}, {"candidates_examined": 1}
    alignments = sorted(conditional["selected"])
    spawn_distances = _distances_from(expedition, expedition.spawn)
    shrine_distances = _distances_from(expedition, expedition.shard)
    candidates = sorted(
        cell
        for cell in expedition.roads
        if cell in spawn_distances
        and cell in shrine_distances
        and spawn_distances[cell] >= expedition.width // 3
        and shrine_distances[cell] >= max(6, expedition.height // 5)
    )
    organisms = []
    for pair in itertools.combinations(candidates, 2):
        separation = abs(pair[0][0] - pair[1][0]) + abs(
            pair[0][1] - pair[1][1]
        )
        route_costs = [
            spawn_distances[cell] + shrine_distances[cell] for cell in pair
        ]
        organisms.append(
            (
                separation,
                abs(route_costs[0] - route_costs[1]),
                pair,
            )
        )
    if not organisms:
        raise ValueError(
            f"No conditional sentinel position pair for {expedition.slug}."
        )
    separation, route_cost_delta, selected = min(
        organisms,
        key=lambda organism: (
            -organism[0],
            -organism[1],
            organism[2],
        ),
    )
    return dict(zip(alignments, selected)), {
        "candidates_examined": len(organisms),
        "selected_separation": separation,
        "selected_route_cost_delta": route_cost_delta,
    }


def generate_expedition(
    spec: dict[str, Any], contract: dict[str, Any] | None = None
) -> Expedition:
    contract = contract or spec["expedition"]
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
        style=_mutate_style(
            dict(spec["style_genome"]), seed, contract.get("palette_shift")
        ),
        spec=spec,
        contract=contract,
        map_type="route",
        return_gate=return_gate,
        repaired_cells=0,
        survey_sites={},
        sentinel_positions={},
        sentinel_population={},
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

    if contract.get("mechanic") == "survey":
        expedition.survey_sites = {
            "chorus": (ring_left + 4, ring_top),
            "silence": (ring_right - 4, ring_bottom),
            "horizon": (ring_right - 4, ring_top),
            "root": (ring_left + 4, ring_bottom),
        }
        for cell in expedition.survey_sites.values():
            expedition.objects[cell[1]][cell[0]] = int(Tile.STATUE)
            expedition.blocked.add(cell)

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
    if contract.get("mechanic", "combat") == "combat":
        (
            expedition.sentinel_positions,
            expedition.sentinel_population,
        ) = _synthesize_sentinel_positions(expedition)
    return expedition


def _phenotype_projection_events(town: Town) -> dict[str, dict[str, Any]]:
    campaign = town.spec.get("campaign", {}).get("selected")
    survey_regions = (
        [
            region
            for region in campaign["regions"]
            if region.get("mechanic") == "survey"
        ]
        if campaign
        else []
    )
    events: dict[str, dict[str, Any]] = {}
    for region in survey_regions:
        alignment_key = region["alignment_key"]
        events[f"Clear unaligned projection for {alignment_key}"] = {
            "type": "init",
            "conditions": [f"not variable_set {alignment_key}"],
            "actions": ["set_layer none"],
        }
        for alignment, phenotype in sorted(region["phenotypes"].items()):
            events[f"Project visible phenotype {region['slug']}:{alignment}"] = {
                "type": "init",
                "conditions": [
                    f"is variable_set {alignment_key}:{alignment}"
                ],
                "actions": [f"set_layer {phenotype['overlay']}"],
            }
    return events


def expedition_events(
    expedition: Expedition, town: Town
) -> dict[str, dict[str, Any]]:
    shrine_x, shrine_y = expedition.shard
    return_x, return_y = expedition.return_gate
    town_return = (town.shard[0], town.shard[1] + 1)
    contract = expedition.contract
    if contract.get("mechanic") == "survey":
        events = _survey_events(expedition, town)
        events.update(_phenotype_projection_events(town))
        return events
    ecology = contract["ecology"]
    selected = ecology.get("selected")
    if selected is None:
        selected = {
            "monster": "aardorn",
            "level": min(map(int, ecology["levels"])),
        }
    sentinel = str(ecology["actor"])
    slug = expedition.slug
    title = expedition.title
    entry_state = str(contract.get("entry_state", "chartered"))
    open_state = str(contract.get("open_state", "wilds_open"))
    complete_state = str(contract.get("complete_state", "shard_recovered"))
    sentinel_setup_events: dict[str, dict[str, Any]] = {}
    conditional = contract.get("conditional_ecologies")
    if conditional:
        alignment_key = conditional["alignment_key"]
        for alignment, branch_ecology in sorted(
            conditional["selected"].items()
        ):
            position = expedition.sentinel_positions[alignment]
            sentinel_setup_events[
                f"Materialize {slug} {alignment} sentinel"
            ] = {
                "type": "event",
                "conditions": [
                    f"is variable_set {alignment_key}:{alignment}",
                    f"not char_exists {sentinel}",
                ],
                "actions": [
                    f"create_npc {sentinel},{position[0]},{position[1]}"
                ],
            }
            sentinel_setup_events[f"Arm {slug} {alignment} sentinel"] = {
                "type": "event",
                "conditions": [
                    f"is variable_set {alignment_key}:{alignment}",
                    f"is char_exists {sentinel}",
                    f"is party_size {sentinel},equals,0",
                ],
                "actions": [
                    "add_monster "
                    f"{branch_ecology['monster']},{branch_ecology['level']},{sentinel}"
                ],
            }
    else:
        position = expedition.sentinel_positions["default"]
        sentinel_setup_events[f"Materialize {slug} sentinel"] = {
            "type": "event",
            "conditions": [f"not char_exists {sentinel}"],
            "actions": [
                f"create_npc {sentinel},{position[0]},{position[1]}"
            ],
        }
        sentinel_setup_events[f"Arm {slug} sentinel"] = {
            "type": "event",
            "conditions": [
                f"is char_exists {sentinel}",
                f"is party_size {sentinel},equals,0",
            ],
            "actions": [
                "add_monster "
                f"{selected['monster']},{selected['level']},{sentinel}"
            ],
        }
    events = {
        f"Initialize {slug}": {
            "type": "event",
            "conditions": [f"not variable_set {slug}_initialized"],
            "actions": [
                "set_environment grass",
                f"set_variable {slug}_initialized:yes",
            ],
        },
        **sentinel_setup_events,
        f"Challenge {slug} sentinel": {
            "type": "event",
            "behav": [f"talk {sentinel}"],
            "conditions": [
                f"is variable_set province_stage:{entry_state}",
                f"not char_defeated {sentinel}",
            ],
            "actions": [
                f"translated_dialog {title} has chosen its own answer. Pass through it, not around it.",
                f"start_battle player,{sentinel}",
            ],
        },
        f"Record {slug} sentinel victory": {
            "type": "event",
            "conditions": [
                f"is battle_outcome player,won,{sentinel}",
                "is current_state WorldState",
                f"is variable_set province_stage:{entry_state}",
            ],
            "actions": [
                f"translated_dialog The sentinel yields. {title} opens toward its sigil.",
                f"set_variable province_stage:{open_state}",
            ],
        },
        f"{title} sentinel remembers": {
            "type": "event",
            "behav": [f"talk {sentinel}"],
            "conditions": [f"is variable_set province_stage:{open_state}"],
            "actions": [
                "translated_dialog The path ahead is yours because you survived its reply."
            ],
        },
        f"Recover {slug} sigil": {
            "type": "event",
            "x": shrine_x,
            "y": shrine_y,
            "conditions": [
                "is char_facing_tile player",
                "is button_pressed INTERACT",
                f"is variable_set province_stage:{open_state}",
            ],
            "actions": [
                f"translated_dialog {title} resolves into a sigil the archive can remember.",
                f"set_variable province_stage:{complete_state}",
            ],
        },
        f"{title} shrine remembered": {
            "type": "event",
            "x": shrine_x,
            "y": shrine_y,
            "conditions": [
                "is char_facing_tile player",
                "is button_pressed INTERACT",
                f"is variable_set province_stage:{complete_state}",
            ],
            "actions": [
                "translated_dialog The empty shrine points west, toward the monolith that remembers home."
            ],
        },
        f"Return from {slug}": {
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
    events.update(_phenotype_projection_events(town))
    return events


def _survey_events(
    expedition: Expedition, town: Town
) -> dict[str, dict[str, Any]]:
    contract = expedition.contract
    slug, title = expedition.slug, expedition.title
    return_x, return_y = expedition.return_gate
    town_return = (town.shard[0], town.shard[1] + 1)
    entry_state = str(contract["entry_state"])
    complete_state = str(contract["complete_state"])
    alignment_key = str(contract["alignment_key"])
    origin_key, horizon_key, root_key = contract["observation_keys"]
    actor = str(contract["actor"])
    guide_position = min(
        expedition.roads,
        key=lambda cell: (
            abs(cell[0] - expedition.width // 2)
            + abs(cell[1] - expedition.height // 2),
            cell,
        ),
    )
    events: dict[str, dict[str, Any]] = {
        f"Initialize {slug}": {
            "type": "event",
            "conditions": [f"not variable_set {slug}_initialized"],
            "actions": [
                "set_environment grass",
                f"set_variable {slug}_initialized:yes",
            ],
        },
        f"Materialize {slug} witness": {
            "type": "event",
            "conditions": [f"not char_exists {actor}"],
            "actions": [
                f"create_npc {actor},{guide_position[0]},{guide_position[1]}"
            ],
        },
        f"{title} witness explains": {
            "type": "event",
            "behav": [f"talk {actor}"],
            "conditions": [
                f"is variable_set province_stage:{entry_state}"
            ],
            "actions": [
                "translated_dialog A survey cannot be won. Choose how to listen, then let the horizon and root answer."
            ],
        },
    }
    for alignment in contract["alignment_values"]:
        x, y = expedition.survey_sites[alignment]
        events[f"Choose {alignment} in {slug}"] = {
            "type": "event",
            "x": x,
            "y": y,
            "conditions": [
                "is char_facing_tile player",
                "is button_pressed INTERACT",
                f"is variable_set province_stage:{entry_state}",
                f"not variable_set {alignment_key}",
            ],
            "actions": [
                f"translated_dialog You tune the first lens through {alignment}.",
                f"set_variable {alignment_key}:{alignment}",
                f"set_variable {origin_key}:yes",
            ],
        }
    for label, key in (("horizon", horizon_key), ("root", root_key)):
        x, y = expedition.survey_sites[label]
        events[f"Observe {label} in {slug}"] = {
            "type": "event",
            "x": x,
            "y": y,
            "conditions": [
                "is char_facing_tile player",
                "is button_pressed INTERACT",
                f"is variable_set province_stage:{entry_state}",
                f"not variable_set {key}",
            ],
            "actions": [
                f"translated_dialog The {label} returns a fact no battle could reveal.",
                f"set_variable {key}:yes",
            ],
        }
    shrine_x, shrine_y = expedition.shard
    for alignment in contract["alignment_values"]:
        events[f"Recover {slug} sigil via {alignment}"] = {
            "type": "event",
            "x": shrine_x,
            "y": shrine_y,
            "conditions": [
                "is char_facing_tile player",
                "is button_pressed INTERACT",
                f"is variable_set province_stage:{entry_state}",
                f"is variable_set {alignment_key}:{alignment}",
                f"is variable_set {origin_key}:yes",
                f"is variable_set {horizon_key}:yes",
                f"is variable_set {root_key}:yes",
            ],
            "actions": [
                f"translated_dialog {title} preserves your {alignment} reading as a sigil.",
                f"set_variable province_stage:{complete_state}",
            ],
        }
    events[f"Return from {slug}"] = {
        "type": "event",
        "x": return_x,
        "y": return_y,
        "conditions": [
            "is char_facing_tile player",
            "is button_pressed INTERACT",
        ],
        "actions": [
            f"translated_dialog {title} folds back into town without erasing your reading.",
            (
                "transition_teleport player,"
                f"{town.slug}.tmx,{town_return[0]},{town_return[1]},0.3"
            ),
        ],
    }
    return events


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
    survey_fronts = {
        label: {
            (cell[0] - 1, cell[1]),
            (cell[0] + 1, cell[1]),
            (cell[0], cell[1] - 1),
            (cell[0], cell[1] + 1),
        }
        & reachable
        for label, cell in expedition.survey_sites.items()
    }
    fraction = len(reachable) / max(1, len(walkable))
    threshold = float(
        expedition.contract["admission"]["minimum_reachable_fraction"]
    )
    cycle_rank = _road_cycle_rank(expedition)  # type: ignore[arg-type]
    if expedition.contract.get("mechanic", "combat") == "survey":
        mechanic_proofs = [
            {
                "id": f"{expedition.slug}-survey-sites-are-reachable",
                "passed": all(survey_fronts.values()),
                "detail": {
                    label: sorted(fronts)
                    for label, fronts in survey_fronts.items()
                },
                "counterexamples": [
                    label
                    for label, fronts in survey_fronts.items()
                    if not fronts
                ],
            }
        ]
        mechanic_witness = {
            "survey_sites": {
                label: list(cell)
                for label, cell in expedition.survey_sites.items()
            }
        }
    else:
        sentinel_positions = expedition.sentinel_positions
        mechanic_proofs = [
            {
                "id": f"{expedition.slug}-conditional-sentinels-are-reachable",
                "passed": all(
                    position in reachable
                    for position in sentinel_positions.values()
                )
                and len(set(sentinel_positions.values()))
                == len(sentinel_positions)
                and (
                    len(sentinel_positions) == 1
                    or expedition.sentinel_population["candidates_examined"]
                    > 1
                ),
                "detail": {
                    "positions": {
                        alignment: list(position)
                        for alignment, position in sentinel_positions.items()
                    },
                    "population": expedition.sentinel_population,
                },
                "counterexamples": [
                    alignment
                    for alignment, position in sentinel_positions.items()
                    if position not in reachable
                ],
            }
        ]
        mechanic_witness = {
            "sentinel": list(next(iter(sentinel_positions.values()))),
            "sentinel_positions": {
                alignment: list(position)
                for alignment, position in sentinel_positions.items()
            },
            "sentinel_population": expedition.sentinel_population,
        }
    proofs = [
        {
            "id": f"{expedition.slug}-entry-is-walkable",
            "passed": expedition.spawn in reachable,
            "detail": list(expedition.spawn),
            "counterexamples": []
            if expedition.spawn in reachable
            else [list(expedition.spawn)],
        },
        {
            "id": f"{expedition.slug}-shrine-is-reachable",
            "passed": bool(shrine_fronts & reachable),
            "detail": sorted(shrine_fronts & reachable),
            "counterexamples": []
            if shrine_fronts & reachable
            else [list(expedition.shard)],
        },
        {
            "id": f"{expedition.slug}-return-is-reachable",
            "passed": return_front in reachable,
            "detail": list(return_front),
            "counterexamples": []
            if return_front in reachable
            else [list(return_front)],
        },
        *mechanic_proofs,
        {
            "id": f"{expedition.slug}-walkable-space-connected",
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
            "id": f"{expedition.slug}-road-network-has-cycle",
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
            **mechanic_witness,
        },
    }
