from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Node:
    id: str
    kind: str
    source: str
    attributes: dict[str, Any] = field(default_factory=dict)

    def serializable(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Edge:
    source: str
    relation: str
    target: str
    evidence: str

    def serializable(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Proof:
    id: str
    passed: bool
    detail: str
    counterexamples: tuple[str, ...] = ()

    def serializable(self) -> dict[str, Any]:
        return asdict(self)
