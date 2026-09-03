from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from foundry.contracts import Edge, Node, Proof

RULE_PARTS = re.compile(r"[\s,]+")
TMX_TARGET = re.compile(r"([^,\s]+\.tmx)", re.IGNORECASE)


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _rule_verb(raw: str, category: str) -> str | None:
    parts = [part for part in RULE_PARTS.split(raw.strip()) if part]
    if not parts:
        return None
    if category == "condition" and parts[0] in {"is", "not"}:
        return parts[1] if len(parts) > 1 else None
    return parts[0]


def _properties(element: ET.Element) -> dict[str, str]:
    values: dict[str, str] = {}
    props = element.find("properties")
    if props is None:
        return values
    for prop in props.findall("property"):
        name = prop.get("name")
        if not name:
            continue
        values[name] = prop.get("value", prop.text or "")
    return values


class OntologyBuilder:
    def __init__(self, root: Path, mod_slug: str) -> None:
        self.root = root.resolve()
        self.mod_slug = mod_slug
        self.mod_root = self.root / "mods" / mod_slug
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self.yaml_failures: list[str] = []
        self.database_shape_failures: list[str] = []
        self.database_key_collisions: list[str] = []
        self.database_declarations = 0
        self.redundant_database_declarations = 0
        self.tmx_failures: list[str] = []
        self.rule_failures: list[str] = []
        self.missing_map_targets: list[str] = []
        self.action_counts: Counter[str] = Counter()
        self.condition_counts: Counter[str] = Counter()
        self.map_ids: dict[str, str] = {}

    def add_node(self, node: Node) -> None:
        existing = self.nodes.get(node.id)
        if existing and existing != node:
            raise ValueError(f"Conflicting node identity: {node.id}")
        self.nodes[node.id] = node

    def add_edge(
        self,
        source: str,
        relation: str,
        target: str,
        evidence: str,
    ) -> None:
        self.edges.append(Edge(source, relation, target, evidence))

    def load_yaml(self, path: Path) -> Any:
        try:
            return yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as error:
            self.yaml_failures.append(f"{_relative(path, self.root)}: {error}")
            return None

    def ingest_database(self) -> None:
        database_root = self.mod_root / "db"
        for table in sorted(
            path for path in database_root.iterdir() if path.is_dir()
        ):
            records: list[tuple[Path, dict[str, Any], str, int]] = []
            for path in sorted(table.glob("*.yaml")):
                document = self.load_yaml(path)
                if isinstance(document, dict):
                    candidates: list[Any] = [document]
                elif isinstance(document, list):
                    candidates = document
                elif document is None:
                    continue
                else:
                    self.database_shape_failures.append(
                        f"{_relative(path, self.root)}: root is neither a record nor list"
                    )
                    continue

                for index, record in enumerate(candidates, 1):
                    if not isinstance(record, dict):
                        self.database_shape_failures.append(
                            f"{_relative(path, self.root)}#{index}: record is not a mapping"
                        )
                        continue
                    fallback = (
                        path.stem
                        if len(candidates) == 1
                        else f"{path.stem}_{index}"
                    )
                    slug = str(record.get("slug", fallback))
                    records.append((path, record, slug, index))

            self.database_declarations += len(records)

            keys: dict[str, list[tuple[Path, dict[str, Any], str, int]]] = {}
            for item in records:
                keys.setdefault(item[2], []).append(item)

            for slug, claims in sorted(keys.items()):
                variants: dict[
                    str, list[tuple[Path, dict[str, Any], str, int]]
                ] = {}
                for claim in claims:
                    payload = json.dumps(
                        claim[1], sort_keys=True, separators=(",", ":")
                    )
                    variants.setdefault(payload, []).append(claim)
                self.redundant_database_declarations += len(claims) - len(
                    variants
                )

                conflict_id: str | None = None
                if len(variants) > 1:
                    conflict_id = (
                        f"counterexample:duplicate-db-key:{table.name}:{slug}"
                    )
                    sources = [
                        f"{_relative(path, self.root)}#{index}"
                        for path, _, _, index in claims
                    ]
                    detail = f"db/{table.name}/{slug} claimed by {', '.join(sources)}"
                    self.database_key_collisions.append(detail)
                    self.add_node(
                        Node(
                            id=conflict_id,
                            kind="counterexample.duplicate_database_key",
                            source="conflicting database records",
                            attributes={
                                "table": table.name,
                                "slug": slug,
                                "claims": sources,
                            },
                        )
                    )

                for payload, variant_claims in sorted(variants.items()):
                    path, record, _, index = variant_claims[0]
                    declarations = [
                        f"{_relative(item_path, self.root)}#{item_index}"
                        for item_path, _, _, item_index in variant_claims
                    ]
                    node_id = f"db:{table.name}:{slug}"
                    if conflict_id is not None:
                        digest = hashlib.sha256(payload.encode()).hexdigest()[
                            :12
                        ]
                        node_id = f"{node_id}@variant:{digest}"
                    self.add_node(
                        Node(
                            id=node_id,
                            kind=f"db.{table.name}",
                            source=_relative(path, self.root),
                            attributes={
                                "slug": slug,
                                "document_index": index,
                                "declarations": declarations,
                                "fields": sorted(record),
                            },
                        )
                    )
                    if conflict_id is not None:
                        self.add_edge(
                            node_id,
                            "collides_on_key",
                            conflict_id,
                            f"duplicate slug {slug}",
                        )

    def ingest_maps(self) -> None:
        maps_root = self.mod_root / "maps"
        tmx_paths = sorted(maps_root.glob("*.tmx"))
        # Build identity before reading any event. A transition is allowed to point
        # forward in filename order; resolving it while streaming the directory
        # would turn those valid edges into false counterexamples.
        for path in tmx_paths:
            self.map_ids[path.name.casefold()] = f"map:{path.stem}"

        for path in tmx_paths:
            map_id = f"map:{path.stem}"
            try:
                root = ET.parse(path).getroot()
            except (OSError, ET.ParseError) as error:
                self.tmx_failures.append(
                    f"{_relative(path, self.root)}: {error}"
                )
                continue
            collision_count = sum(
                1
                for obj in root.findall(".//object")
                if obj.get("type") in {"collision", "collision-line"}
            )
            self.add_node(
                Node(
                    id=map_id,
                    kind="map.tmx",
                    source=_relative(path, self.root),
                    attributes={
                        "width": int(root.get("width", "0")),
                        "height": int(root.get("height", "0")),
                        "tile_width": int(root.get("tilewidth", "0")),
                        "tile_height": int(root.get("tileheight", "0")),
                        "tile_layers": len(root.findall("layer")),
                        "tilesets": len(root.findall("tileset")),
                        "collisions": collision_count,
                    },
                )
            )
            event_index = 0
            for obj in root.findall(".//object"):
                props = _properties(obj)
                if not any(
                    name.startswith(("act", "cond", "behav")) for name in props
                ):
                    continue
                event_index += 1
                event_id = f"event:{path.stem}:tmx:{event_index}"
                self.add_node(
                    Node(
                        id=event_id,
                        kind=f"event.{obj.get('type', 'event')}",
                        source=_relative(path, self.root),
                        attributes={
                            "name": obj.get("name", ""),
                            "x": float(obj.get("x", "0")),
                            "y": float(obj.get("y", "0")),
                        },
                    )
                )
                self.add_edge(map_id, "contains", event_id, "TMX event object")
                for name, raw in sorted(props.items()):
                    if name.startswith("act"):
                        self.ingest_rule(event_id, "action", raw)
                    elif name.startswith("cond"):
                        self.ingest_rule(event_id, "condition", raw)

        for path in sorted(maps_root.glob("*.yaml")):
            document = self.load_yaml(path)
            if not isinstance(document, dict):
                continue
            events = document.get("events", {})
            if not isinstance(events, dict):
                self.rule_failures.append(
                    f"{_relative(path, self.root)}: events is not a mapping"
                )
                continue
            map_id = self.map_ids.get(path.with_suffix(".tmx").name.casefold())
            if map_id is None:
                map_id = f"script:{path.stem}"
                self.add_node(
                    Node(
                        id=map_id,
                        kind="map.script",
                        source=_relative(path, self.root),
                        attributes={},
                    )
                )
            for index, (name, spec) in enumerate(sorted(events.items()), 1):
                if not isinstance(spec, dict):
                    self.rule_failures.append(
                        f"{_relative(path, self.root)}:{name}: invalid event"
                    )
                    continue
                event_id = f"event:{path.stem}:yaml:{index}"
                self.add_node(
                    Node(
                        id=event_id,
                        kind=f"event.{spec.get('type', 'event')}",
                        source=_relative(path, self.root),
                        attributes={"name": str(name)},
                    )
                )
                self.add_edge(map_id, "contains", event_id, "YAML event")
                for raw in spec.get("actions", []):
                    self.ingest_rule(event_id, "action", str(raw))
                for raw in spec.get("conditions", []):
                    self.ingest_rule(event_id, "condition", str(raw))

    def ingest_rule(self, event_id: str, category: str, raw: str) -> None:
        verb = _rule_verb(raw, category)
        if verb is None:
            self.rule_failures.append(
                f"{event_id}: malformed {category}: {raw!r}"
            )
            return
        counts = (
            self.action_counts
            if category == "action"
            else self.condition_counts
        )
        counts[verb] += 1
        target_id = f"rule:{category}:{verb}"
        self.add_edge(event_id, f"uses_{category}", target_id, raw)
        if category != "action":
            return
        for target in TMX_TARGET.findall(raw):
            target_name = PurePosixPath(
                target.replace("\\", "/")
            ).name.casefold()
            target_map_id = self.map_ids.get(
                target_name, f"missing-map:{target_name}"
            )
            self.add_edge(event_id, "transitions_to", target_map_id, raw)
            if target_map_id.startswith("missing-map:"):
                self.missing_map_targets.append(f"{event_id} -> {target_name}")

    def add_rule_nodes(self) -> None:
        for category, counts in (
            ("action", self.action_counts),
            ("condition", self.condition_counts),
        ):
            for verb, occurrences in sorted(counts.items()):
                self.add_node(
                    Node(
                        id=f"rule:{category}:{verb}",
                        kind=f"rule.{category}",
                        source="observed event vocabulary",
                        attributes={"occurrences": occurrences},
                    )
                )
        for target in sorted(set(self.missing_map_targets)):
            name = target.rsplit(" -> ", 1)[1]
            self.add_node(
                Node(
                    id=f"missing-map:{name}",
                    kind="counterexample.missing_map",
                    source="unresolved transition",
                    attributes={"filename": name},
                )
            )

    def proofs(self) -> list[Proof]:
        return [
            Proof(
                "yaml-decodes",
                not self.yaml_failures,
                f"Decoded YAML corpus with {len(self.yaml_failures)} failures.",
                tuple(self.yaml_failures[:20]),
            ),
            Proof(
                "database-record-shapes",
                not self.database_shape_failures,
                (
                    "Observed "
                    f"{len(self.database_shape_failures)} malformed database records."
                ),
                tuple(self.database_shape_failures[:20]),
            ),
            Proof(
                "tmx-decodes",
                not self.tmx_failures,
                f"Decoded TMX corpus with {len(self.tmx_failures)} failures.",
                tuple(self.tmx_failures[:20]),
            ),
            Proof(
                "database-keys-unambiguous",
                not self.database_key_collisions,
                (
                    "Observed "
                    f"{len(self.database_key_collisions)} database keys with "
                    "conflicting payloads."
                ),
                tuple(self.database_key_collisions[:20]),
            ),
            Proof(
                "event-rules-parse",
                not self.rule_failures,
                f"Parsed event rules with {len(self.rule_failures)} failures.",
                tuple(self.rule_failures[:20]),
            ),
            Proof(
                "map-targets-resolve",
                not self.missing_map_targets,
                f"Observed {len(self.missing_map_targets)} unresolved transitions.",
                tuple(sorted(set(self.missing_map_targets))[:20]),
            ),
        ]

    def build(self) -> dict[str, Any]:
        self.ingest_database()
        self.ingest_maps()
        self.add_rule_nodes()
        nodes = [
            self.nodes[node_id].serializable()
            for node_id in sorted(self.nodes)
        ]
        edges = [
            edge.serializable()
            for edge in sorted(
                self.edges,
                key=lambda item: (
                    item.source,
                    item.relation,
                    item.target,
                    item.evidence,
                ),
            )
        ]
        proofs = [proof.serializable() for proof in self.proofs()]
        body = {
            "schema": "ai-native-tuxemon-ontology/v1",
            "upstream": {
                "mod": self.mod_slug,
                "source_root": "mods/tuxemon",
            },
            "counts": {
                "nodes": len(nodes),
                "edges": len(edges),
                "database_records": sum(
                    1 for node in nodes if node["kind"].startswith("db.")
                ),
                "database_declarations": self.database_declarations,
                "redundant_database_declarations": (
                    self.redundant_database_declarations
                ),
                "maps": sum(1 for node in nodes if node["kind"] == "map.tmx"),
                "script_maps": sum(
                    1 for node in nodes if node["kind"] == "map.script"
                ),
                "events": sum(
                    1 for node in nodes if node["kind"].startswith("event.")
                ),
                "action_verbs": len(self.action_counts),
                "condition_verbs": len(self.condition_counts),
                "transitions": sum(
                    1 for edge in edges if edge["relation"] == "transitions_to"
                ),
            },
            "proofs": proofs,
            "nodes": nodes,
            "edges": edges,
        }
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
        body["fingerprint"] = hashlib.sha256(canonical.encode()).hexdigest()
        return body


def build_ontology(root: Path, mod_slug: str = "tuxemon") -> dict[str, Any]:
    return OntologyBuilder(root, mod_slug).build()
