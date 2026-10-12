from copy import deepcopy

import pytest

from experiments.retrieval_method import graphify_cross_source as cross
from experiments.retrieval_method import graphify_evidence_search as search
from tests.test_graphify_cross_source import example


@pytest.fixture
def engine():
    raw, graph, index = example()
    layer = cross.derive(graph, raw, "synthetic-structure")
    return search.Engine(graph, index, raw, layer, "synthetic-snapshot")


def assert_group_anchors(payload, engine):
    for e in payload["evidence"].values():
        path = payload["sources"][e["source"]]
        expected = "".join(f"{i}: {line}" for i, line in enumerate(engine.lines[path][e["start"] - 1:e["end"]], e["start"]))
        assert e["text"] == expected
    for group in payload["groups"]:
        if group["kind"] == "cross_source":
            categories = {cross.structure.source_category(payload["sources"][payload["evidence"][eid]["source"]]) for eid in group["evidence"]}
            assert categories == {"manual", "tutorial"}
            original = "".join(payload["evidence"][eid]["text"] for eid in group["evidence"])
            assert "type " + group["model"] in original
            if group["model"] == "alphaMeter":
                assert "Only scalar fields" in original and "field must already exist" in original


def test_explicit_case_returns_both_sides_with_unclipped_conditions(engine):
    result, audit = engine.query("alphaMeter reference", case="tutorials/solverA/shared", cap=6000)
    assert any(g["kind"] == "cross_source" and g["model"] == "alphaMeter" for g in result["groups"])
    assert all(not g["case"] or g["case"] == "tutorials/solverA/shared" for g in result["groups"])
    assert audit["returned_characters"] == len(search.compact(result)) <= 6000
    assert_group_anchors(result, engine)


def test_same_named_cases_remain_ambiguous_and_explicit_path_is_respected(engine):
    result, _ = engine.query("shared alphaMeter", cap=15000)
    assert result["scope"]["mode"] == "ambiguous_basename"
    assert set(result["scope"]["cases"]) == set(engine.cases)
    assert {g["case"] for g in result["groups"] if g["kind"] == "cross_source"} == set(engine.cases)
    result, _ = engine.query("solverB/shared alphaMeter")
    assert result["scope"] == {"mode": "literal_path_in_query", "cases": ["tutorials/solverB/shared"]}
    assert all(not g["case"] or g["case"] == "tutorials/solverB/shared" for g in result["groups"])


@pytest.mark.parametrize("source", ["manual", "tutorial"])
def test_source_constraints_do_not_smuggle_in_other_corpus(engine, source):
    result, _ = engine.query("alphaMeter reference", source=source)
    assert result["groups"]
    assert all(g["kind"] == "structure" for g in result["groups"])
    assert all(cross.structure.source_category(path) == source for path in result["sources"].values())


def test_budget_never_publishes_half_a_cross_source_group(engine):
    for cap in (1000, 1400, 2000, 3000, 6000):
        result, audit = engine.query("alphaMeter reference fields", cap=cap)
        assert len(search.compact(result)) <= cap
        assert audit["work"]["groups_materialized_before_budget"] >= len(result["groups"])
        assert_group_anchors(result, engine)


def test_seen_groups_are_not_repeated_and_search_is_deterministic(engine):
    first, audit = engine.query("alphaMeter reference")
    second, audit2 = engine.query("alphaMeter reference")
    assert search.compact(first) == search.compact(second)
    assert audit["candidate_group_ids"] == audit2["candidate_group_ids"]
    more, _ = engine.query("alphaMeter reference", seen_groups=audit["returned_group_ids"])
    assert not set(audit["returned_group_ids"]) & {g["id"] for g in more["groups"]}


def test_edge_factor_does_not_mutate_graph_or_invent_unknown_alignment(engine):
    original = deepcopy(engine.layer)
    result, audit = engine.query("alphaMeter", with_relations=False)
    assert all(g["kind"] == "structure" for g in result["groups"])
    assert not any(audit["returned_canonical_relations"].values())
    assert engine.layer == original
    missing, _ = engine.query("entirelyUnknownName")
    assert missing["groups"] == []
    with pytest.raises(ValueError):
        engine.query("alphaMeter", case="shared")
    with pytest.raises(ValueError):
        engine.query("alphaMeter", file="outside-corpus")


def test_dictionary_scope_only_expands_relations_of_the_requested_instance(engine):
    result, _ = engine.query("fields reference", case="tutorials/solverA/shared", dictionary="functions/a/reference")
    assert any(g["kind"] == "cross_source" for g in result["groups"])
    assert all(g["model"] == "alphaMeter" for g in result["groups"] if g["kind"] == "cross_source")
