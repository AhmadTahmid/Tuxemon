from __future__ import annotations

import argparse
import json
from pathlib import Path

from foundry.ingest import build_ontology


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Atomize a Tuxemon mod into a typed evidence graph."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--mod", default="tuxemon")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("foundry/artifacts/upstream-ontology.generated.json"),
    )
    args = parser.parse_args()
    certificate = build_ontology(args.root, args.mod)
    output = args.root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(certificate, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    summary = {
        "output": output.as_posix(),
        "fingerprint": certificate["fingerprint"],
        "counts": certificate["counts"],
        "proofs": certificate["proofs"],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
