from __future__ import annotations

import json
from pathlib import Path

import foundry.branching as branching


def test_branch_aggregation_reads_the_persisted_certificate(
    tmp_path: Path, monkeypatch
) -> None:
    certificate = {
        "schema": "test/v1",
        "survey_policy": "silence",
        "proofs": [{"id": "executed", "passed": True}],
    }
    output = tmp_path / "playthrough.silence.generated.json"
    output.write_text(json.dumps(certificate), encoding="utf-8")

    def fake_playthrough(root: Path, policy: str):
        return {"output": output.as_posix(), **certificate}

    monkeypatch.setattr(branching, "run_playthrough", fake_playthrough)
    loaded, loaded_path = branching._run_and_load(tmp_path, "silence")

    assert loaded_path == output
    assert loaded == certificate
    assert "output" not in loaded
