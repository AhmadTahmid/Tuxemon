# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2014-2026 William Edwards <shadowapex@gmail.com>, Benjamin Bean <superman2k5@gmail.com>
from unittest.mock import MagicMock, patch

import pytest

from tuxemon.entity.entity import Entity
from tuxemon.map.collision_manager import CollisionManager
from tuxemon.map.manager import MapManager
from tuxemon.map.region import RegionProperties
from tuxemon.npc_manager import NPCManager


@pytest.fixture
def map_manager():
    return MagicMock(spec=MapManager)


@pytest.fixture
def npc_manager():
    return MagicMock(spec=NPCManager)


@pytest.fixture
def collision_manager(map_manager, npc_manager):
    return CollisionManager(map_manager, npc_manager)


def test_check_collision_zones(collision_manager, map_manager):
    collision_map = {
        (0, 0): RegionProperties([], [], [], None, "label1"),
        (1, 1): RegionProperties([], [], [], None, "label2"),
    }
    map_manager.collision_map = collision_map

    result = collision_manager.check_collision_zones(collision_map, "label1")
    assert result == [(0, 0)]


def test_add_collision(collision_manager, map_manager):
    entity = MagicMock(spec=Entity)
    entity.is_player = True
    entity.tile_pos = (0, 0)

    region = RegionProperties([], [], [], None, "label1")
    map_manager.collision_map = {(0, 0): region}

    collision_manager.add_collision(entity, (0, 0))

    assert map_manager.collision_map[(0, 0)].entity is not None


def test_remove_collision(collision_manager, map_manager):
    region = RegionProperties([], [], [], None, "label1")
    map_manager.collision_map = {(0, 0): region}

    collision_manager.remove_collision((0, 0))

    assert (0, 0) not in map_manager.collision_map


def test_get_collision_map(collision_manager, map_manager, npc_manager):
    map_manager.collision_map = {
        (0, 0): RegionProperties([], [], [], None, "label1")
    }
    map_manager.surface_map = {(0, 0): {"label1": 0.0}}

    npc = MagicMock(spec=Entity)
    npc.tile_pos = (0, 0)
    npc_manager.get_all_entities.return_value = [npc]

    collision_map = collision_manager.get_collision_map()
    assert (0, 0) in collision_map


def test_get_region_properties(collision_manager, map_manager):
    region = RegionProperties([], [], [], None, "label1")
    map_manager.collision_map = {(0, 0): region}

    props = collision_manager._get_region_properties((0, 0), "label1")
    assert props.key == "label1"
