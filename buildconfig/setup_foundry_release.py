#!/usr/bin/env python
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import os
import sys
from pathlib import Path

from cx_Freeze import Executable, setup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DEFAULT_OUTPUT = ROOT / "build" / "unmapped-province-windows"
OUTPUT = Path(os.environ.get("FOUNDRY_BUILD_DIR", DEFAULT_OUTPUT)).resolve()
ROOT_MOD_FILES = [
    (str(path), f"lib/mods/{path.name}")
    for path in sorted((ROOT / "mods").iterdir())
    if path.is_file()
]


setup(
    name="The Unmapped Province",
    version="0.1.0",
    description="A proof-carrying turn-based RPG compiled by an AI foundry",
    options={
        "build_exe": {
            "build_exe": str(OUTPUT),
            "packages": [
                "natsort",
                "pygame",
                "pygame_menu",
                "pyscroll",
                "pytmx",
                "tuxemon",
                "websockets",
                "yaml",
            ],
            "excludes": ["PySide6", "tkinter"],
            "includes": ["importlib.resources"],
            "include_files": [
                (str(ROOT / "mods" / "tuxemon"), "lib/mods/tuxemon"),
                (
                    str(ROOT / "mods" / "unmapped_province"),
                    "lib/mods/unmapped_province",
                ),
                *ROOT_MOD_FILES,
                (str(ROOT / "LICENSE"), "LICENSE"),
                (str(ROOT / "ATTRIBUTIONS.md"), "ATTRIBUTIONS.md"),
            ],
            "optimize": 1,
        }
    },
    executables=[
        Executable(
            str(ROOT / "foundry" / "launch.py"),
            base="gui",
            target_name="UnmappedProvince.exe",
            icon=str(ROOT / "mods" / "tuxemon" / "gfx" / "icon.ico"),
        )
    ],
)
