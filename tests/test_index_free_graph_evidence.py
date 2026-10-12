import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/retrieval_method"))

from candidate_graph_utils import sha
from candidate_graph_utils import wire
from index_free_graph_evidence import Engine
from index_free_graph_evidence import evidence_coordinates
from index_free_graph_evidence import identifier_occurs
from index_free_graph_evidence import requested_relations
from index_free_graph_evidence import scopes
from index_free_graph_evidence import slot_source_preferences
from index_free_graph_evidence import structured_identifiers
from index_free_graph_evidence import retrieval_terms


def test_evidence_coordinates_merge_overlapping_source_ranges():
    coordinates = evidence_coordinates([
        {"path": "a", "start": 2, "end": 4},
        {"path": "a", "start": 3, "end": 5},
        {"path": "b", "start": 1, "end": 1},
    ])
    assert coordinates == {
        ("a", 2), ("a", 3), ("a", 4), ("a", 5), ("b", 1),
    }


def test_direct_graph_scan_returns_original_evidence_without_external_index(tmp_path):
    corpus = tmp_path / "corpus"
    source = corpus / "tutorials/blastFoam/movingCone/constant/dynamicMeshDict"
    source.parent.mkdir(parents=True)
    source.write_text("dynamicFvMesh dynamicRefineFvMesh;\nmotionSolver displacementLaplacian;\n")
    digest = sha(source.read_bytes())
    node = {
        "id": "configuration:motionSolver", "kind": "configuration",
        "label": "configuration motionSolver displacementLaplacian", "search_text": source.read_text(),
        "path": source.relative_to(corpus).as_posix(), "key": "motionSolver",
        "value": "displacementLaplacian", "dictionary": "dynamicMeshDict", "parent": None,
        "scope": {"case_directory": "tutorials/blastFoam/movingCone"},
        "evidence": [{"path": source.relative_to(corpus).as_posix(), "start": 2, "end": 2,
                      "source_sha256": digest}], "status": "physical_structure",
    }
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps({"corpus_id": "fixture", "nodes": {node["id"]: node}, "edges": []}))
    engine = Engine(corpus, graph)

    result, audit = engine.query("movingCone 的网格运动怎么配置？",
                                 translation="movingCone mesh motion motionSolver", cap=3000)

    assert result["groups"]
    assert "motionSolver displacementLaplacian" in next(iter(result["evidence"].values()))["text"]
    assert audit["external_index_loaded"] is False
    assert audit["recall"]["work"]["ranking"].endswith("no BM25/vector/inverted index")

    navigation, navigation_audit = engine.query(
        "movingCone 的网格运动怎么配置？",
        translation="movingCone mesh motion motionSolver",
        cap=3000,
        response_mode="navigation",
    )
    assert navigation["schema"] == "principia-navigation-v1"
    assert navigation["navigation_only"] is True
    assert navigation["catalogue_policy"] == {
        "budget_basis": "evidence_budget_only",
        "candidate_limit": 6,
        "compact_overflow_limit": 0,
    }
    assert "evidence" not in navigation
    assert "sources" not in navigation
    assert navigation["candidates"][0]["node"]["id"] == node["id"]
    assert navigation["candidates"][0]["node"]["value"] == "displacementLaplacian"
    assert "search_text" not in navigation["candidates"][0]["node"]
    assert navigation["candidates"][0]["sources"] == [{
        "path": node["path"], "start": 2, "end": 2,
    }]
    assert navigation_audit["returned_group_ids"] == audit["returned_group_ids"]


def test_navigation_keeps_evidence_budget_without_returning_hidden_text(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    nodes = {}
    for index in range(8):
        source = corpus / f"source-{index}.txt"
        source.write_text("\n".join(
            f"shared target setting {index} detail {line} " + "x" * 60
            for line in range(24)
        ) + "\n")
        nodes[f"node-{index}"] = {
            "id": f"node-{index}", "kind": "configuration",
            "label": f"shared target setting {index}",
            "search_text": source.read_text(), "path": source.name,
            "key": f"setting{index}", "scope": {},
            "evidence": [{"path": source.name, "start": 1, "end": 24,
                          "source_sha256": sha(source.read_bytes())}],
        }
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps({"corpus_id": "fixture", "nodes": nodes,
                                 "edges": []}))
    engine = Engine(corpus, graph)

    evidence, _ = engine.query("shared target setting", cap=3000)
    navigation, audit = engine.query(
        "shared target setting", cap=3000, response_mode="navigation"
    )

    assert len(navigation["candidates"]) == len(evidence["groups"])
    assert len(navigation["candidates"]) <= 6
    assert len(wire(navigation)) <= 3000
    assert all("text" not in source for candidate in navigation["candidates"]
               for source in candidate["sources"])
    assert audit["returned_group_ids"] == [
        candidate["id"] for candidate in navigation["candidates"]
    ]


def test_engine_rejects_graph_evidence_hash_drift(tmp_path):
    corpus = tmp_path / "corpus"; corpus.mkdir()
    (corpus / "manual.md").write_text("supported\n")
    node = {"id": "n", "kind": "section", "label": "supported", "path": "manual.md",
            "scope": {"case_directory": None}, "evidence": [{"path": "manual.md", "start": 1,
            "end": 1, "source_sha256": "wrong"}]}
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps({"corpus_id": "fixture", "nodes": {"n": node}, "edges": []}))
    try:
        Engine(corpus, graph)
    except ValueError as error:
        assert "source drift" in str(error)
    else:
        raise AssertionError("hash drift must fail")


def test_natural_spaced_case_name_matches_camel_case_scope():
    cases = [
        "tutorials/blastFoam/axisymmetricCharge",
        "tutorials/blastFoam/freeField",
    ]
    selected = scopes("axisymmetric charge pressure probes", cases)
    assert selected == {
        "status": "natural_case_name",
        "cases": ["tutorials/blastFoam/axisymmetricCharge"],
    }


def test_short_region_name_does_not_false_scope_natural_prose():
    cases = [
        "tutorials/preCICE/flap/Fluid",
        "tutorials/solids4Foam/flap",
    ]
    selected = scopes("fluid structure coupling flap settings", cases)
    assert selected == {"status": "unrestricted", "cases": []}


def test_only_structured_literals_receive_exact_identifier_bonus():
    assert structured_identifiers(
        "uses the oxygen transport eTabulated O2 DDT phaseProperties path/to/file"
    ) == {"eTabulated", "O2", "DDT", "phaseProperties", "path/to/file"}
    assert structured_identifiers("manual section 12.1") == {"12.1"}
    assert structured_identifiers("coefficients As and Ts") == {"As", "Ts"}
    assert structured_identifiers("ordinary sentence. migration. limited.") == set()
    assert structured_identifiers("use reconstruct(U) here") == {"reconstruct(U)"}


def test_separator_insensitive_terms_match_formula_identifiers():
    assert "c0" in retrieval_terms("C_0")
    assert "tref" in retrieval_terms("T_ref")
    assert "checkpoint" in retrieval_terms("checkpointing")
    assert "boundary" in retrieval_terms("boundaries")
    assert "modifier" in retrieval_terms("modifiers")
    assert "the" not in retrieval_terms("the model")


def test_decimal_identifier_does_not_match_a_longer_source_value():
    assert identifier_occurs("target 0.6", "0.6")
    assert not identifier_occurs("current 0.62 and -0.64", "0.6")


def test_generic_model_word_does_not_request_selector_relation():
    assert "SELECTS_MODEL" not in requested_relations("固体热力学模型的适用范围")
    assert "SELECTS_MODEL" in requested_relations("模型选择器和实际选择")


def test_defaultfaces_identifier_is_not_a_default_value_request():
    slot = "0/Su中的walls与defaultFaces边界类型"
    assert slot_source_preferences(slot) == {"manual": False, "instance": False}
    assert "DEFAULT_WHEN" not in requested_relations(slot)


def test_explicit_tutorial_condition_slot_prefers_instance_source():
    slot = "教程实例的模型选择配置及启用条件"
    assert slot_source_preferences(slot) == {"manual": False, "instance": True}


def test_unresolved_slots_diversify_direct_scan_seeds(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    nodes = {}
    for index in range(10):
        path = corpus / f"generic-{index}.txt"
        path.write_text("generic pressure\n")
        nodes[f"generic-{index}"] = {
            "id": f"generic-{index}", "kind": "document_unit",
            "label": "generic pressure", "path": path.name, "scope": {},
            "evidence": [{"path": path.name, "start": 1, "end": 1,
                          "source_sha256": sha(path.read_bytes())}],
        }
    path = corpus / "specific.txt"
    path.write_text("oxygen transport As Ts\n")
    nodes["specific"] = {
        "id": "specific", "kind": "configuration",
        "label": "O2 transport As Ts", "path": path.name, "scope": {},
        "evidence": [{"path": path.name, "start": 1, "end": 1,
                      "source_sha256": sha(path.read_bytes())}],
    }
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps({"corpus_id": "fixture", "nodes": nodes, "edges": []}))
    engine = Engine(corpus, graph)

    seeds, audit = engine.graph_hits(
        "generic pressure", limit=4, slots=["oxygen As Ts actual coefficients"])

    assert "specific" in dict(seeds)
    assert audit["slot_queries"] == 1
    assert audit["ranking"].endswith("no BM25/vector/inverted index")


def test_query_local_case_coherence_prefers_case_covering_distributed_slots(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    nodes = {}

    def add(node_id, case, text, aliases):
        path = corpus / f"{node_id}.txt"
        path.write_text(text + "\n")
        nodes[node_id] = {
            "id": node_id,
            "kind": "configuration",
            "label": text,
            "path": path.name,
            "scope": {"case_directory": case},
            "aliases": aliases,
            "evidence": [{
                "path": path.name,
                "start": 1,
                "end": 1,
                "source_sha256": sha(path.read_bytes()),
            }],
        }

    # The distractor has a strong match for one concept.  The intended case is
    # identifiable only by combining three concepts spread over separate nodes.
    add("distractor", "tutorials/blastFoam/shockTube", "oxygen setup", ["oxygen"])
    add("transport", "tutorials/blastFoam/reacting", "transport As Ts", ["Sutherland coefficients"])
    add("species", "tutorials/blastFoam/reacting", "species O2", ["oxygen"])
    add("include", "tutorials/blastFoam/reacting", "include thermo file", ["included dictionary"])
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps({"corpus_id": "fixture", "nodes": nodes, "edges": []}))
    engine = Engine(corpus, graph)

    seeds, audit = engine.graph_hits(
        "how is the gas configured?",
        limit=3,
        slots=["oxygen species", "Sutherland coefficients", "included dictionary"],
    )

    assert audit["case_prior_mode"] == "query_local_full_graph_scan_soft_prior"
    assert audit["case_hypotheses"][0]["case_directory"] == "tutorials/blastFoam/reacting"
    assert audit["case_hypotheses"][0]["covered_slots"] == 3
    assert {"transport", "species", "include"} <= set(dict(seeds))


def test_budgeted_selection_prefers_structured_slot_gain_over_long_generic_text(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    generic = corpus / "generic.md"
    generic.write_text("\n".join(
        "generic protected boundaries balancing settings discussion" for _ in range(80)
    ) + "\n")
    target = corpus / "dynamicMeshDict"
    target.write_text("protectedPatches (flap);\nbalance false;\n")
    nodes = {
        "generic": {
            "id": "generic", "kind": "document_unit",
            "label": "generic protected boundaries balancing settings",
            "search_text": generic.read_text(), "path": generic.name, "scope": {},
            "evidence": [{"path": generic.name, "start": 1, "end": 80,
                          "source_sha256": sha(generic.read_bytes())}],
        },
        "target": {
            "id": "target", "kind": "configuration",
            "label": "protectedPatches flap balance false",
            "search_text": target.read_text(), "path": target.name,
            "key": "protectedPatches", "aliases": ["protected boundaries", "protected patches"],
            "scope": {},
            "evidence": [{"path": target.name, "start": 1, "end": 2,
                          "source_sha256": sha(target.read_bytes())}],
        },
    }
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps({"corpus_id": "fixture", "nodes": nodes, "edges": []}))
    engine = Engine(corpus, graph)

    result, audit = engine.query(
        "check protected boundaries and balancing settings",
        slots=["protected boundaries", "balancing settings"],
        cap=1200,
    )

    assert target.name in result["sources"].values()
    assert generic.name not in result["sources"].values()
    assert audit["selection"]["mode"] == "marginal_slot_gain_per_estimated_evidence_character"


def test_manual_slot_and_exact_model_survive_case_seed_pressure(tmp_path):
    corpus = tmp_path / "corpus"
    manual = corpus / "manual/model.md"
    manual.parent.mkdir(parents=True)
    manual.write_text("ePower C_v(T) = C_0 (T/T_ref)^n_0\n")
    nodes = {
        "manual": {
            "id": "manual", "kind": "document_unit", "label": "ePower heat capacity formula",
            "search_text": manual.read_text(), "path": "manual/model.md", "scope": {},
            "evidence": [{"path": "manual/model.md", "start": 1, "end": 1,
                          "source_sha256": sha(manual.read_bytes())}],
        }
    }
    for index in range(20):
        source = corpus / f"tutorials/case-{index}/field"
        source.parent.mkdir(parents=True)
        source.write_text("C0 n0 Tref default value\n")
        nodes[f"case-{index}"] = {
            "id": f"case-{index}", "kind": "configuration", "label": source.read_text(),
            "path": source.relative_to(corpus).as_posix(),
            "scope": {"case_directory": f"tutorials/case-{index}"},
            "evidence": [{"path": source.relative_to(corpus).as_posix(), "start": 1, "end": 1,
                          "source_sha256": sha(source.read_bytes())}],
        }
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps({"corpus_id": "fixture", "nodes": nodes, "edges": []}))
    engine = Engine(corpus, graph)

    seeds, audit = engine.graph_hits(
        "ePower C0 n0 Tref", limit=4, slots=["ePower 公式原文与单位"]
    )

    assert "manual" in dict(seeds)
    assert audit["exact_identifier_seeds"] >= 1


def test_requested_default_relation_gets_reserved_seed(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    nodes = {}
    for node_id, text in [
        ("generic", "temperature default discussion"),
        ("default", "unmappedT DEFAULT_WHEN 293.15"),
    ]:
        source = corpus / f"{node_id}.md"
        source.write_text(text + "\n")
        nodes[node_id] = {
            "id": node_id, "kind": "conditional_assertion", "label": text,
            "path": source.name, "scope": {},
            "evidence": [{"path": source.name, "start": 1, "end": 1,
                          "source_sha256": sha(source.read_bytes())}],
        }
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps({"corpus_id": "fixture", "nodes": nodes, "edges": []}))
    engine = Engine(corpus, graph)

    seeds, audit = engine.graph_hits(
        "temperature", limit=1, slots=["unmapped temperature 默认值"]
    )

    assert list(dict(seeds)) == ["default"]
    assert audit["ranking"].startswith("query_local_identifier_rarity")


def test_case_alias_does_not_falsely_satisfy_every_instance_slot(tmp_path):
    corpus = tmp_path / "corpus"
    marker = corpus / "tutorials/demo/ddtCase/system/controlDict"
    marker.parent.mkdir(parents=True)
    marker.write_text("application demo;\n")
    useful = corpus / "tutorials/demo/ddtCase/constant/combustionProperties"
    useful.parent.mkdir(parents=True, exist_ok=True)
    useful.write_text("Su Su [0 1 -1 0 0 0 0] 0.434;\n")
    distractor = corpus / "tutorials/demo/ddtCase/system/fvSolution"
    distractor.write_text("solvers {}\n")
    nodes = {}
    for node_id, source, label in [
        ("useful", useful, "Su laminar flame speed given value 0.434"),
        ("distractor", distractor, "solver metadata"),
    ]:
        relative = source.relative_to(corpus).as_posix()
        nodes[node_id] = {
            "id": node_id,
            "kind": "configuration",
            "label": label,
            "aliases": ["DDT"],
            "path": relative,
            "scope": {"case_directory": "tutorials/demo/ddtCase"},
            "evidence": [{
                "path": relative,
                "start": 1,
                "end": 1,
                "source_sha256": sha(source.read_bytes()),
            }],
        }
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps({"corpus_id": "fixture", "nodes": nodes, "edges": []}))
    engine = Engine(corpus, graph)

    _result, audit = engine.query(
        "DDT tutorial case",
        slots=["laminar flame speed given value"],
        cap=5000,
    )
    trace = {row["path"]: row for row in audit["selection"]["trace"]}

    assert trace[useful.relative_to(corpus).as_posix()]["slot_scores"]
    assert trace[distractor.relative_to(corpus).as_posix()]["slot_scores"] == {}


def test_named_manual_section_anchor_beats_short_same_symbol_fragment(tmp_path):
    corpus = tmp_path / "corpus"
    section = corpus / "manual/model.md"
    section.parent.mkdir(parents=True)
    section.write_text(
        "#### ArrheniusRate\nTs switch temperature; Tign minimum reaction temperature; not validated.\n"
    )
    fragment = corpus / "tutorial/transport"
    fragment.parent.mkdir(parents=True)
    fragment.write_text("Ts 139;\n")
    nodes = {
        "section": {
            "id": "section", "kind": "document_unit",
            "label": "5.6.1.5 ArrheniusRate", "path": "manual/model.md", "scope": {},
            "evidence": [{"path": "manual/model.md", "start": 1, "end": 2,
                          "source_sha256": sha(section.read_bytes())}],
        },
        "fragment": {
            "id": "fragment", "kind": "configuration", "key": "Ts",
            "label": "Ts transport value", "path": "tutorial/transport", "scope": {},
            "evidence": [{"path": "tutorial/transport", "start": 1, "end": 1,
                          "source_sha256": sha(fragment.read_bytes())}],
        },
    }
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps({"corpus_id": "fixture", "nodes": nodes, "edges": []}))
    engine = Engine(corpus, graph)

    result, audit = engine.query(
        "ArrheniusRate Ts Tign validation",
        slots=["ArrheniusRate Ts and Tign meanings", "validation status"],
        cap=1200,
    )

    assert "manual/model.md" in result["sources"].values()
    selected = next(
        row for row in audit["selection"]["trace"] if row["path"] == "manual/model.md"
    )
    assert selected["accepted"] is True


def test_manual_document_unit_reservation_survives_generic_case_pressure(tmp_path):
    corpus = tmp_path / "corpus"
    manual = corpus / "manual/region.md"
    manual.parent.mkdir(parents=True)
    manual.write_text(
        "globalTemperatureCoupled uses neighbour temperature and heat transfer.\n"
        "unmappedT defaults to 293.15.\n"
    )
    nodes = {
        "manual": {
            "id": "manual", "kind": "document_unit",
            "label": "document_unit globalTemperatureCoupled table/text",
            "search_text": manual.read_text(), "path": "manual/region.md", "scope": {},
            "evidence": [{"path": "manual/region.md", "start": 1, "end": 2,
                          "source_sha256": sha(manual.read_bytes())}],
        }
    }
    for index in range(20):
        source = corpus / f"tutorials/case-{index}/coupling"
        source.parent.mkdir(parents=True)
        source.write_text("region mapping configuration boundary coupling\n")
        nodes[f"case-{index}"] = {
            "id": f"case-{index}", "kind": "configuration",
            "label": source.read_text(), "path": source.relative_to(corpus).as_posix(),
            "scope": {"case_directory": f"tutorials/case-{index}"},
            "evidence": [{"path": source.relative_to(corpus).as_posix(),
                          "start": 1, "end": 1,
                          "source_sha256": sha(source.read_bytes())}],
        }
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps({"corpus_id": "fixture", "nodes": nodes, "edges": []}))
    engine = Engine(corpus, graph)

    seeds, audit = engine.graph_hits(
        "temperature boundary coupling neighbour heat transfer unmapped default",
        limit=4,
        slots=["neighbour quantities", "unmapped temperature default"],
    )

    assert "manual" in dict(seeds)
    assert audit["manual_unit_candidates"] == 1
