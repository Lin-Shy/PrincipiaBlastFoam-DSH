from copy import deepcopy

import pytest

from experiments.retrieval_method import graphify_cross_source as cross
from experiments.retrieval_method import graphify_evidence_search as search
from experiments.retrieval_method import graphify_navigation_audit as audit
from tests.test_graphify_cross_source import example


def response():
    raw, graph, index = example()
    layer = cross.derive(graph, raw, "id")
    engine = search.Engine(graph, index, raw, layer, "identity")
    r = next(r for r in layer["relations"] if r["parameter"] == "reference")
    q = {"query": "alphaMeter reference", "case": r["scope"]["case_directory"], "id": r["id"]}
    payload, trace = engine.query(q["query"], case=q["case"])
    return payload, trace, engine, q


def test_source_driven_contract_checker_checks_both_endpoints():
    payload, trace, engine, q = response()
    assert audit.checks(payload, trace, engine, q, True) == []


@pytest.mark.parametrize("tamper,error", [
    ("budget", "budget"), ("raw", "verbatim_line_mismatch"),
    ("scope", "case_scope"), ("anchor", "incomplete_required_anchor"),
    ("edge", "requested_literal_relation_not_returned"),
])
def test_contract_checker_rejects_tampered_search_result(tamper, error):
    payload, trace, engine, q = response()
    if tamper == "budget":
        trace["cap"] = 1
    elif tamper == "raw":
        next(iter(payload["evidence"].values()))["text"] = "made up"
    elif tamper == "scope":
        payload["groups"][0]["case"] = "other-case"
    elif tamper == "anchor":
        g = next(g for g in payload["groups"] if g["kind"] == "cross_source")
        g["evidence"] = []
    else:
        trace["returned_canonical_relations"] = {}
        payload["groups"] = []
    assert error in audit.checks(payload, trace, engine, q, True)
