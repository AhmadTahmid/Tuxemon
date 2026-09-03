from __future__ import annotations

from pathlib import Path

from foundry.ingest import build_ontology

ROOT = Path(__file__).parents[2]


def test_upstream_ontology_is_deterministic() -> None:
    first = build_ontology(ROOT)
    second = build_ontology(ROOT)
    assert first["fingerprint"] == second["fingerprint"]


def test_upstream_ontology_contains_runtime_scale_content() -> None:
    graph = build_ontology(ROOT)
    assert graph["counts"]["database_records"] > 1_000
    assert graph["counts"]["maps"] > 200
    assert graph["counts"]["events"] > 1_000
    assert graph["counts"]["action_verbs"] > 50
    assert graph["counts"]["condition_verbs"] > 20


def test_every_graph_edge_has_a_node_at_both_ends() -> None:
    graph = build_ontology(ROOT)
    node_ids = {node["id"] for node in graph["nodes"]}
    for edge in graph["edges"]:
        assert edge["source"] in node_ids
        assert edge["target"] in node_ids


def test_proof_results_retain_counterexamples() -> None:
    graph = build_ontology(ROOT)
    for proof in graph["proofs"]:
        if not proof["passed"]:
            assert proof["counterexamples"]
