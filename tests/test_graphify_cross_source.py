from copy import deepcopy
from pathlib import Path

import pytest

from experiments.retrieval_method import graphify_cross_source as cross
from experiments.retrieval_method import graphify_structure as structure


MANUAL = """# 15 Function objects

These function objects use a controlDict entry.
```cpp
functions { impulse { type impulse; } }
```

## 15.1 alphaMeter (alternateMeter)

Only scalar fields are supported; the field must already exist.

| Entry | Description |
|---|---|
| fields | Fields to inspect |
| reference | Reference value (default 7) |

## 15.2 betaMeter

A different role-specific function object.

| Entry | Description |
|---|---|
| fields | Fields to write |
"""


def example(config=None):
    content = config or """FoamFile { class dictionary; }
functions
{
 a { type alphaMeter; fields (p); reference 12; }
 b { type betaMeter; fields (rho); }
}
"""
    raw = {cross.MANUAL: MANUAL.encode(),
        "tutorials/solverA/shared/system/controlDict": content.encode(),
        "tutorials/solverB/shared/system/controlDict": content.encode()}
    support, _ = structure.load_support(Path(__file__).resolve().parents[1] / ".dsh/skills/blastfoam-knowledge/scripts")
    _, graph, index, _, _ = structure.construct(raw, "synthetic", {"nodes": [], "links": []}, support)
    return raw, graph, index


def test_two_sided_role_path_conditions_and_instances_are_preserved():
    raw, graph, _ = example()
    layer = cross.derive(graph, raw, "fixture-structure")
    assert len(layer["relations"]) == 10
    assert len({r["id"] for r in layer["relations"]}) == 10
    assert len({r["scope"]["case_directory"] for r in layer["relations"]}) == 2
    for r in layer["relations"]:
        assert r["manual_evidence"] and r["tutorial_evidence"]
        assert r["runtime_activation"] == r["manual_preconditions_satisfied"] == "not_evaluated"
        assert not r["instance_value_is_default"] and not r["cooccurrence_is_dependency"]
    param = next(r for r in layer["relations"] if r["parameter"] == "reference")
    d = layer["definitions"][param["target"]]
    assert d["parameters"]["reference"]["normalized_default_or_obligation"] is None
    assert "default 7" in d["parameters"]["reference"]["description_verbatim"]
    assert cross.validate(layer, graph, raw, "fixture-structure")["status"] == "PASS"


def test_repeated_derivation_is_byte_identical_and_parent_graph_is_unchanged():
    raw, graph, _ = example()
    original = deepcopy(graph)
    a, b = cross.derive(graph, raw, "id"), cross.derive(graph, raw, "id")
    assert cross.encoded(a) == cross.encoded(b) and original == graph


@pytest.mark.parametrize("config,reason", [
    ("FoamFile {} functions { a { type alternateMeter; } }", "no_exact_primary_manual_definition"),
    ("FoamFile {} functions { a { type alphaMeter; type betaMeter; } }", "unresolved_selector_or_ancestor"),
    ('FoamFile {}\n#include "unresolved"\nfunctions { a { type alphaMeter; } }', "ancestor_scope_contains_unevaluated_directive_or_statement"),
    ('FoamFile {} functions { a {\n#if $x\ntype alphaMeter;\n#endif\n} }', "unresolved_selector_or_ancestor"),
])
def test_aliases_duplicates_and_unevaluated_scopes_are_not_verified(config, reason):
    raw, graph, _ = example(config)
    layer = cross.derive(graph, raw, "id")
    assert not layer["relations"]
    assert reason in {c["reason"] for c in layer["candidates"]}


def test_nested_same_named_parameters_are_not_crossed_and_disabled_is_explicit():
    raw, graph, _ = example("FoamFile {} functions { a { type alphaMeter; enabled false; nested { reference 8; } } }")
    layer = cross.derive(graph, raw, "id")
    assert len(layer["relations"]) == 2
    assert all(r["relation"] == "SELECTOR_DOCUMENTED_BY" for r in layer["relations"])
    assert all(r["enabled_observations"][0]["literal"] == "false" for r in layer["relations"])
    assert all(r["runtime_activation"] == "not_evaluated" for r in layer["relations"])


@pytest.mark.parametrize("change", ["one_side", "quote", "scope", "endpoint", "condition", "dropped"])
def test_validation_rejects_tampered_evidence_conditions_and_missing_edges(change):
    raw, graph, _ = example()
    layer = cross.derive(graph, raw, "id")
    r = layer["relations"][0]
    if change == "one_side":
        r["manual_evidence"] = []
    elif change == "quote":
        r["tutorial_evidence"][0]["quote_sha256"] = "changed"
    elif change == "scope":
        r["scope"]["case_directory"] = "invented"
        graph = deepcopy(example()[1])
    elif change == "endpoint":
        r["target"] = "missing-definition"
    elif change == "condition":
        r["conditions"]["exact_primary_model_name"] = "wrong"
    else:
        layer["relations"].pop()
    with pytest.raises(ValueError):
        cross.validate(layer, graph, raw, "id")
