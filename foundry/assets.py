# SPDX-License-Identifier: GPL-3.0-or-later
"""Certify semantic asset projections without making aesthetic claims."""
from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from PIL import Image

from foundry.town import compile_world


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(root: Path) -> dict[str, Any]:
    root = root.resolve()
    build = compile_world(root)
    admission = json.loads(
        Path(build["certificate"]).read_text(encoding="utf-8")
    )
    mod = Path(build["mod"])
    observations: dict[str, dict[str, Any]] = {}
    references_resolve = True
    dimensions_match = True
    atlases_well_formed = True

    for slug, region in admission["regions"].items():
        atlas_path = mod / "gfx" / "tilesets" / f"{slug}.png"
        tsx_path = mod / "gfx" / "tilesets" / f"{slug}.tsx"
        tmx_path = mod / "maps" / f"{slug}.tmx"
        preview_path = Path(build["previews"][slug])
        atlas = Image.open(atlas_path).convert("RGBA")
        preview = Image.open(preview_path).convert("RGBA")
        tsx = ET.parse(tsx_path).getroot()
        tmx = ET.parse(tmx_path).getroot()
        tsx_image = tsx.find("image")
        tmx_tileset = tmx.find("tileset")
        expected_preview = tuple(value * 32 for value in region["dimensions"])
        reference_ok = (
            tsx_image is not None
            and tsx_image.attrib.get("source") == f"{slug}.png"
            and tmx_tileset is not None
            and tmx_tileset.attrib.get("source")
            == f"../gfx/tilesets/{slug}.tsx"
        )
        references_resolve &= reference_ok
        dimensions_match &= preview.size == expected_preview
        atlas_ok = (
            atlas.size == (128, 64)
            and tsx.attrib.get("tilecount") == "32"
            and tsx.attrib.get("columns") == "8"
            and len(atlas.getcolors(maxcolors=128 * 64)) >= 12
        )
        atlases_well_formed &= atlas_ok
        observations[slug] = {
            "atlas_sha256": _sha256(atlas_path),
            "atlas_dimensions": list(atlas.size),
            "atlas_colors": len(atlas.getcolors(maxcolors=128 * 64)),
            "preview_sha256": _sha256(preview_path),
            "preview_dimensions": list(preview.size),
            "references_resolve": reference_ok,
        }

    atlas_hashes = {
        observation["atlas_sha256"] for observation in observations.values()
    }
    proofs = [
        {
            "id": "semantic-projections-have-declared-shape",
            "passed": atlases_well_formed and dimensions_match,
            "detail": observations,
        },
        {
            "id": "compiled-asset-references-resolve",
            "passed": references_resolve,
            "detail": {
                slug: value["references_resolve"]
                for slug, value in observations.items()
            },
        },
        {
            "id": "regional-style-projections-are-distinct",
            "passed": len(atlas_hashes) == len(observations),
            "detail": sorted(atlas_hashes),
        },
        {
            "id": "every-region-has-a-rendered-preview",
            "passed": len(observations) == admission["counts"]["regions"]
            and all(item["preview_sha256"] for item in observations.values()),
            "detail": list(observations),
        },
    ]
    body = {
        "schema": "ai-native-semantic-asset-identity/v1",
        "world_fingerprint": build["fingerprint"],
        "observations": observations,
        "proofs": proofs,
        "non_claims": [
            "This certificate proves identity, integrity, and distinction; not beauty or player preference."
        ],
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    body["fingerprint"] = hashlib.sha256(canonical.encode()).hexdigest()
    output = root / "foundry" / "artifacts" / "assets.generated.json"
    output.write_text(
        json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if not all(proof["passed"] for proof in proofs):
        raise RuntimeError(f"Asset admission failed; inspect {output}")
    return {"output": output.as_posix(), **body}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Certify semantic visual projections for every region."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(json.dumps(run(args.root), indent=2))


if __name__ == "__main__":
    main()
