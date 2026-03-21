# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2014-2026 William Edwards <shadowapex@gmail.com>, Benjamin Bean <superman2k5@gmail.com>
from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Mapping, MutableMapping
from typing import TYPE_CHECKING

from tuxemon.map.region import RegionProperties

if TYPE_CHECKING:
    from tuxemon.entity.entity import Entity
    from tuxemon.entity.npc import NPC
    from tuxemon.map.manager import MapManager
    from tuxemon.npc_manager import NPCManager

logger = logging.getLogger(__name__)


CollisionMap = Mapping[
    tuple[int, int],
    RegionProperties | None,
]


class CollisionManager:
    """
    Manages collision data and performs collision checks within the game world.
    """

    def __init__(
        self, map_manager: MapManager, npc_manager: NPCManager
    ) -> None:
        self._map_manager = map_manager
        self._npc_manager = npc_manager

    def check_collision_zones(
        self,
        collision_map: MutableMapping[
            tuple[int, int], RegionProperties | None
        ],
        label: str,
    ) -> list[tuple[int, int]]:
        """
        Returns coordinates of specific collision zones.

        Parameters:
            collision_map: The collision map.
            label: The label to filter collision zones by.

        Returns:
            A list of coordinates of collision zones with the specific label.
        """
        return [
            coords
            for coords, props in collision_map.items()
            if props and props.key == label
        ]

    def add_collision(
        self,
        entity: Entity,
        coords: tuple[int, int],
    ) -> None:
        """
        Registers the given entity's position within the collision zone.

        Parameters:
            entity: The entity object to be added to the collision zone.
            pos: The X, Y coordinates (as floats) indicating the entity's position.
        """
        region = (
            self._map_manager.collision_map.get(coords) or RegionProperties()
        )
        self._map_manager.collision_map[coords] = region.with_overrides(
            entity=entity
        )

    def remove_collision(self, tile_pos: tuple[int, int]) -> None:
        """
        Removes the specified tile position from the collision zone.

        Parameters:
            tile_pos: The X, Y tile coordinates to be removed from the collision map.
        """
        region = self._map_manager.collision_map.get(tile_pos)
        if not region:
            return  # Nothing to remove

        if region.enter_from or region.exit_from or region.endure:
            self._map_manager.collision_map[tile_pos] = region.with_overrides(
                entity=None
            )
        else:
            # Remove region
            del self._map_manager.collision_map[tile_pos]

    def get_collision_map(self) -> CollisionMap:
        """
        Return dictionary for collision testing.

        Returns a dictionary where keys are (x, y) tile tuples
        and the values are tiles or NPCs.

        # NOTE:
        This will not respect map changes to collisions
        after the map has been loaded!

        Returns:
            A dictionary of collision tiles.
        """
        collision_dict: defaultdict[
            tuple[int, int], RegionProperties | None
        ] = defaultdict(RegionProperties)

        # Get all the NPCs' tile positions
        for npc in self._npc_manager.get_all_entities():
            collision_dict[npc.tile_pos] = self._get_region_properties(
                npc.tile_pos, npc
            )

        # Add surface map entries to the collision dictionary
        for coords, surface in self._map_manager.surface_map.items():
            for label, value in surface.items():
                if float(value) == 0:
                    collision_dict[coords] = self._get_region_properties(
                        coords, label
                    )

        collision_dict.update(
            {k: v for k, v in self._map_manager.collision_map.items()}
        )

        return dict(collision_dict)

    def _get_region_properties(
        self, coords: tuple[int, int], entity_or_label: NPC | str
    ) -> RegionProperties:
        """
        Constructs a RegionProperties object for the given tile coordinates,
        using either an NPC entity or a string label.

        Parameters:
            coords: The (x, y) tile position.
            entity_or_label: Either an NPC or a label string.

        Returns:
            A RegionProperties object representing the collision state.
        """
        region = (
            self._map_manager.collision_map.get(coords) or RegionProperties()
        )
        if isinstance(entity_or_label, str):
            return region.with_overrides(key=entity_or_label)
        else:
            return region.with_overrides(entity=entity_or_label)
