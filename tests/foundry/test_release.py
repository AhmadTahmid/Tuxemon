from __future__ import annotations

import json
import zipfile
from pathlib import Path

from foundry.release import (
    _canonical_fingerprint,
    _sha256,
    _write_deterministic_zip,
)


def test_certificate_fingerprint_is_content_addressed() -> None:
    certificate = {
        "schema": "test/v1",
        "proofs": [{"id": "reachable", "passed": True}],
    }
    certificate["fingerprint"] = _canonical_fingerprint(certificate)
    serialized = json.loads(json.dumps(certificate))

    assert _canonical_fingerprint(serialized) == certificate["fingerprint"]
    serialized["proofs"][0]["passed"] = False
    assert _canonical_fingerprint(serialized) != certificate["fingerprint"]


def test_release_archive_is_byte_deterministic(tmp_path: Path) -> None:
    build = tmp_path / "build"
    (build / "lib").mkdir(parents=True)
    (build / "UnmappedProvince.exe").write_bytes(b"frozen-game")
    (build / "lib" / "world.dat").write_bytes(b"semantic-world")
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"

    _write_deterministic_zip(build, first)
    _write_deterministic_zip(build, second)

    assert _sha256(first) == _sha256(second)
    with zipfile.ZipFile(first) as archive:
        assert archive.testzip() is None
        assert {entry.date_time for entry in archive.infolist()} == {
            (1980, 1, 1, 0, 0, 0)
        }
