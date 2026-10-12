from copy import deepcopy
from pathlib import Path

import pytest

from experiments.retrieval_method import graphify_structure as g


SUPPORT = Path(__file__).resolve().parents[1] / ".dsh/skills/blastfoam-knowledge/scripts"


@pytest.fixture
def source():
    return {p: s.encode() for p, s in {
        "manual/markdown/01_models.md": "Preamble.\n\n# Models\n\n## Choice\n\nThe field must exist; the tool is only recommended.\n\n| Key | Meaning |\n|---|---|\n| coeff | 7 by default if active |\n",
        "tutorials/solverA/shared/Allrun": "#!/bin/sh\nrunApplication initializer\n",
        "tutorials/solverA/shared/system/controlDict": "FoamFile { class dictionary; }\napplication solverA;\n",
        "tutorials/solverA/shared/constant/state": "FoamFile { class dictionary; }\nleft\n{\n selector choice;\n coefficients { coeff 12; }\n}\nright { coefficients { coeff 19; } }\n#include \"fragment\"\n#include \"absent\"\n",
        "tutorials/solverA/shared/constant/fragment": "speciesX { transport { coeff 26; } }\n",
        "tutorials/solverB/shared/system/controlDict": "FoamFile { class dictionary; }\napplication solverB;\n",
        "tutorials/solverB/shared/0/p": "FoamFile { class volScalarField; }\nboundaryField { wall { type fixedValue; value uniform 3; } }\n",
        "tutorials/solverB/shared/helper.py": "header = 'FoamFile { class dictionary; }'\nprint(header)\n",
        "tutorials/solverB/shared/empty": "",
    }.items()} | {"manual/markdown/figures/test.png": b"\x89PNG\x00\x00"}


@pytest.fixture
def parent():
    return {"directed": False, "multigraph": False, "graph": {"original": "unchanged"},
        "nodes": [{"id": "original-a", "label": "original interpretation", "source_file": "manual/markdown/01_models.md", "source_location": ""},
                  {"id": "original-b", "label": "original code", "source_file": "tutorials/solverA/shared/Allrun", "source_location": "L1"}],
        "links": [{"source": "original-a", "target": "original-b", "relation": "inferred_relation", "confidence": "INFERRED", "weight": .4}],
        "hyperedges": [{"original": "hyperedge retained"}], "built_at_commit": "inherited-not-construction-id"}


def build(source, parent):
    support, _ = g.load_support(SUPPORT)
    return g.construct(source, "fixture-corpus", parent, support)


def test_same_nodes_plus_edges_and_original_graph_bytes_are_preserved(source, parent):
    original = deepcopy(parent)
    gn, gh, index, issues, stats = build(source, parent)
    assert parent == original
    assert gn["nodes"] == gh["nodes"]
    assert gn["links"] == original["links"]
    assert gh["links"][:1] == original["links"]
    assert gh["hyperedges"] == parent["hyperedges"]
    assert stats["added_edges_GH"] > 0
    assert g.validate(parent, gn, gh, index, source)["status"] == "PASS"
    assert any(i.get("reason") == "literal_include_target_unavailable" for i in issues)
    assert not any(e["relation"] in {"PARAMETER_INSTANCE", "REQUIRES", "DEFAULT_FOR", "INCLUDES"} for e in gh["links"])


def test_cold_repeated_construction_is_identical(source, parent):
    first = build(source, parent)
    second = build(source, parent)
    assert [g.encoded(x) for x in first] == [g.encoded(x) for x in second]


def test_same_named_cases_and_phases_are_not_merged(source, parent):
    gn, gh, index, _, _ = build(source, parent)
    configs = [n for n in gn["nodes"] if n.get("structure_kind") == "configuration"]
    bypath = {(n["source_file"], n["metadata"]["dictionary_path"]): n for n in configs}
    left = bypath["tutorials/solverA/shared/constant/state", "left/coefficients/coeff"]
    right = bypath["tutorials/solverA/shared/constant/state", "right/coefficients/coeff"]
    assert left["id"] != right["id"]
    assert left["metadata"]["value_text"] == "12" and right["metadata"]["value_text"] == "19"
    assert left["scope"]["case_directory"] == "tutorials/solverA/shared"
    wall = bypath["tutorials/solverB/shared/0/p", "boundaryField/wall/type"]
    assert wall["scope"]["case_directory"] == "tutorials/solverB/shared"
    assert wall["scope"]["field_file_hint"] == "p"
    assert not any(e["source"] == left["id"] and e["target"] == right["id"] for e in gh["links"])
    assert all(n["is_general_default"] is False for n in configs)


def test_fragment_keeps_physical_scope_and_python_header_is_not_a_dictionary(source, parent):
    gn, _, _, _, stats = build(source, parent)
    fragment = next(n for n in gn["nodes"] if n.get("structure_kind") == "configuration" and n["metadata"]["dictionary_path"] == "speciesX/transport/coeff")
    assert fragment["source_file"].endswith("/constant/fragment")
    assert fragment["metadata"]["include_reached_from"]
    assert fragment["metadata"]["effective_value_or_override_resolution"] is False
    assert not any(n.get("structure_kind") == "configuration" and n["source_file"].endswith("helper.py") for n in gn["nodes"])
    assert stats["extraction_work"]["literal_include_target_files"] == 1


def test_manual_conditions_remain_verbatim_and_assets_are_not_understood(source, parent):
    gn, gh, index, _, _ = build(source, parent)
    units = [n for n in gn["nodes"] if n.get("structure_kind") == "document_unit"]
    assert any("7 by default if active" in n["rationale"] for n in units)
    assert all(n["metadata"]["meaning_defaults_and_conditions_not_automatically_interpreted"] for n in units)
    image = next(n for n in gn["nodes"] if n.get("structure_kind") == "file" and n["source_file"].endswith("test.png"))
    assert image["evidence_status"] == "not-parsed" and image["source_location"] == ""
    assert image["metadata"]["image_pixels_understood"] is False
    empty = next(n for n in gn["nodes"] if n.get("structure_kind") == "file" and n["source_file"].endswith("/empty"))
    assert empty["source_location"] == ""
    assert g.validate(parent, gn, gh, index, source)["status"] == "PASS"


@pytest.mark.parametrize("tamper", ["location", "rationale", "source", "metadata", "edge"])
def test_validator_rejects_visible_anchor_and_factor_drift(source, parent, tamper):
    gn, gh, index, _, _ = build(source, parent)
    target = next(i for i, n in enumerate(gn["nodes"]) if n.get("structure_kind") == "configuration")
    if tamper in ("location", "rationale", "source"):
        field, value = {"location": ("source_location", "L9999"), "rationale": ("rationale", "injected answer not in any source"),
                        "source": ("source_sha256", "changed")}[tamper]
        gn["nodes"][target][field] = gh["nodes"][target][field] = value
    elif tamper == "metadata":
        gh["graph"]["not_a_pure_edge_factor"] = True
    else:
        edge = next(e for e in gh["links"] if e["relation"] == "HAS_ENTRY")
        edge["relation"] = "REQUIRES"
    with pytest.raises(ValueError):
        g.validate(parent, gn, gh, index, source)


def test_uncertain_syntax_is_visible_without_modifying_query_renderer(source, parent):
    source["tutorials/solverA/shared/system/fvSchemes"] = b"FoamFile { class dictionary; }\nschemes {\n a first\n b second;\n}\n"
    gn, _, _, _, _ = build(source, parent)
    combined = next(n for n in gn["nodes"] if n.get("structure_kind") == "configuration" and n["metadata"]["dictionary_path"] == "schemes/a")
    assert combined["label"].endswith("[unresolved]")
    assert "multiline_plain_value_needs_syntax_check" in combined["metadata"]["flags"]


def test_illegal_source_location_is_not_allowed(source, parent):
    source["manual/markdown/../../private"] = b"not an allowed source"
    with pytest.raises(ValueError):
        build(source, parent)


def test_malformed_markdown_is_fully_retained_as_explicit_raw_fallback(source, parent):
    path = "tutorials/solverA/shared/README.md"
    source[path] = b"# Original heading\n\n```sh\nnot closed\n"
    gn, gh, index, issues, stats = build(source, parent)
    assert index["coverage"][path]["mode"] == "markdown_raw_fallback"
    units = [n for n in gn["nodes"] if n.get("structure_kind") == "source_span" and n["source_file"] == path]
    assert "".join(n["rationale"] for n in sorted(units, key=lambda n: n["metadata"].get("start_offset", 0))) == source[path].decode()
    assert all(n["evidence_status"] == "unparsed-format" for n in units)
    assert any(i.get("reason") == "markdown_format_unparsed" and i["path"] == path for i in issues)
    assert stats["file_coverage_modes"]["markdown_raw_fallback"] == 1
    assert set(index["coverage"]) == set(source)
    assert g.validate(parent, gn, gh, index, source)["status"] == "PASS"


def test_observations_have_versioned_identity_and_physical_scope(source, parent):
    gn, _, _, _, _ = build(source, parent)
    support, _ = g.load_support(SUPPORT)
    changed, _, _, _, _ = g.construct(source, "next-corpus", parent, support)
    a = next(n for n in gn["nodes"] if n.get("structure_kind") == "configuration")
    b = next(n for n in changed["nodes"] if n["id"] == a["id"])
    assert a["observation_id"] != b["observation_id"]
    assert a["scope"]["physical_dictionary_components"] == a["metadata"]["physical_components"]
    assert a["scope"]["source_version"] == a["source_sha256"]


def test_inventory_witness_does_not_make_ancestor_directory_part_of_a_case(source, parent):
    gn, gh, index, _, _ = build(source, parent)
    directories = {n["metadata"]["directory"]: n for n in gn["nodes"] if n.get("metadata", {}).get("directory")}
    assert directories["tutorials"]["scope"]["case_directory"] is None
    assert directories["tutorials/solverA"]["scope"]["case_directory"] is None
    assert directories["tutorials/solverA/shared"]["scope"]["case_directory"] == "tutorials/solverA/shared"
    assert g.validate(parent, gn, gh, index, source)["status"] == "PASS"
