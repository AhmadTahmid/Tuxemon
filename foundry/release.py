# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUILD = ROOT / "build" / "unmapped-province-windows"
DEFAULT_DIST = ROOT / "dist"
RELEASE_NAME = "The-Unmapped-Province-0.7.0-windows-x86_64"
SOURCE_CERTIFICATES = {
    "world-admission": (
        ROOT
        / "foundry"
        / "artifacts"
        / "unmapped_province.admission.generated.json"
    ),
    "ecology-selection": (
        ROOT / "foundry" / "worlds" / "echo_wilds.ecology.lock.json"
    ),
    "campaign-selection": (
        ROOT / "foundry" / "worlds" / "campaign.lock.json"
    ),
    "asset-identity": (
        ROOT / "foundry" / "artifacts" / "assets.generated.json"
    ),
    "runtime-probe": (
        ROOT
        / "foundry"
        / "artifacts"
        / "unmapped_province.runtime.generated.json"
    ),
    "combat-self-play": (
        ROOT / "foundry" / "artifacts" / "combat-selfplay.generated.json"
    ),
    "campaign-playthrough": (
        ROOT / "foundry" / "artifacts" / "playthrough.generated.json"
    ),
    "counterfactual-branches": (
        ROOT / "foundry" / "artifacts" / "branching.generated.json"
    ),
    "persistence-replay": (
        ROOT / "foundry" / "artifacts" / "persistence.generated.json"
    ),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_fingerprint(document: dict[str, Any]) -> str:
    body = dict(document)
    body.pop("fingerprint", None)
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _relative_label(path: Path, build_dir: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return f"build/{path.relative_to(build_dir).as_posix()}"


def _read_certificate(
    stage: str, path: Path, build_dir: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not path.is_file():
        raise RuntimeError(f"Missing {stage} certificate: {path}")
    document = json.loads(path.read_text(encoding="utf-8"))
    expected = document.get("fingerprint")
    observed = _canonical_fingerprint(document)
    if expected != observed:
        raise RuntimeError(
            f"{stage} certificate fingerprint mismatch: {expected} != {observed}"
        )
    proofs = document.get("proofs", [])
    failed = [proof["id"] for proof in proofs if not proof.get("passed")]
    if not proofs or failed:
        raise RuntimeError(f"{stage} has failed or missing proofs: {failed}")
    bundled_path = build_dir / "proofs" / path.name
    if bundled_path.is_file() and _sha256(bundled_path) == _sha256(path):
        certificate_label = _relative_label(bundled_path, build_dir)
    else:
        certificate_label = _relative_label(path, build_dir)
    summary = {
        "stage": stage,
        "certificate": certificate_label,
        "certificate_sha256": _sha256(path),
        "fingerprint": expected,
        "proofs": [proof["id"] for proof in proofs],
    }
    return document, summary


def _release_files(build_dir: Path) -> list[dict[str, Any]]:
    excluded = {"release-manifest.json"}
    files = [
        path
        for path in build_dir.rglob("*")
        if path.is_file() and path.name not in excluded
    ]
    return [
        {
            "path": path.relative_to(build_dir).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(files, key=lambda item: item.as_posix().casefold())
    ]


def build_manifest(build_dir: Path) -> dict[str, Any]:
    executable = build_dir / "UnmappedProvince.exe"
    if not executable.is_file():
        raise RuntimeError(f"Frozen executable does not exist: {executable}")

    certificate_paths = dict(SOURCE_CERTIFICATES)
    certificate_paths["frozen-runtime"] = (
        build_dir / "release-smoke.generated.json"
    )
    documents: dict[str, dict[str, Any]] = {}
    proof_chain: list[dict[str, Any]] = []
    for stage, path in certificate_paths.items():
        documents[stage], summary = _read_certificate(stage, path, build_dir)
        proof_chain.append(summary)

    world_fingerprint = documents["world-admission"]["fingerprint"]
    mismatched = {
        stage: document.get("world_fingerprint")
        for stage, document in documents.items()
        if stage != "world-admission"
        and "world_fingerprint" in document
        and document.get("world_fingerprint") != world_fingerprint
    }
    if mismatched:
        raise RuntimeError(
            "Proof chain refers to different compiled worlds: "
            f"expected {world_fingerprint}, got {mismatched}"
        )

    files = _release_files(build_dir)
    body: dict[str, Any] = {
        "schema": "ai-native-proof-carrying-release/v1",
        "release": {
            "name": "The Unmapped Province",
            "version": "0.7.0",
            "platform": "windows-x86_64",
            "entrypoint": "UnmappedProvince.exe",
        },
        "world_fingerprint": world_fingerprint,
        "proof_chain": proof_chain,
        "payload": {
            "file_count": len(files),
            "bytes": sum(file["bytes"] for file in files),
            "files": files,
        },
    }
    body["fingerprint"] = _canonical_fingerprint(body)
    manifest = build_dir / "release-manifest.json"
    manifest.write_text(
        json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return body


def _write_deterministic_zip(build_dir: Path, archive: Path) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    root_name = RELEASE_NAME
    paths = sorted(
        (path for path in build_dir.rglob("*") if path.is_file()),
        key=lambda item: item.as_posix().casefold(),
    )
    with zipfile.ZipFile(
        archive,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as bundle:
        for path in paths:
            relative = path.relative_to(build_dir).as_posix()
            info = zipfile.ZipInfo(
                f"{root_name}/{relative}", date_time=(1980, 1, 1, 0, 0, 0)
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            with path.open("rb") as source, bundle.open(info, "w") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)


def promote(build_dir: Path, dist_dir: Path, run_smoke: bool) -> dict[str, Any]:
    build_dir = build_dir.resolve()
    if run_smoke:
        subprocess.run(
            [str(build_dir / "UnmappedProvince.exe"), "--smoke-test"],
            cwd=build_dir,
            check=True,
            timeout=60,
        )
    manifest = build_manifest(build_dir)
    archive = dist_dir.resolve() / f"{RELEASE_NAME}.zip"
    _write_deterministic_zip(build_dir, archive)
    receipt: dict[str, Any] = {
        "schema": "ai-native-release-receipt/v1",
        "archive": archive.name,
        "bytes": archive.stat().st_size,
        "sha256": _sha256(archive),
        "manifest_fingerprint": manifest["fingerprint"],
        "world_fingerprint": manifest["world_fingerprint"],
    }
    receipt_path = archive.with_suffix(".release.json")
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Promote a frozen build only when every proof agrees."
    )
    parser.add_argument("--build-dir", type=Path, default=DEFAULT_BUILD)
    parser.add_argument("--dist-dir", type=Path, default=DEFAULT_DIST)
    parser.add_argument(
        "--skip-smoke",
        action="store_true",
        help="Use an existing frozen smoke certificate instead of rerunning it.",
    )
    args = parser.parse_args()
    receipt = promote(args.build_dir, args.dist_dir, not args.skip_smoke)
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
