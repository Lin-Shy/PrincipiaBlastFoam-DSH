"""核心测试可用 unittest 运行；真实 Graphify 用冻结隔离解释器验证。"""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

try:
    import networkx as nx
except ModuleNotFoundError:
    nx = None

from experiments.retrieval_method import graphify_query_variants as variant
from experiments.retrieval_method import graphify_query_backend as reference


class FilterTests(unittest.TestCase):
    def test_only_unsupported_automatic_filters_removed(self):
        graph = SimpleNamespace(edges=lambda **kw: [
            ("a", "b", {"context": "call"}), ("b", "c", {"relation": "uses"})])
        serve = SimpleNamespace(_resolve_context_filters=lambda q, e: (["field", "call"], "heuristic"))
        used, origin, audit = variant.resolve_filters(serve, graph, "question", True)
        self.assertEqual(used, ["call"])
        self.assertEqual(audit["dropped"], ["field"])
        self.assertEqual(origin, "heuristic")
        self.assertEqual(variant.resolve_filters(serve, graph, "question", False)[0], ["field", "call"])

    def test_no_supported_context_falls_back_to_unfiltered_graph(self):
        graph = SimpleNamespace(edges=lambda **kw: [("a", "b", {"relation": "documents"})])
        serve = SimpleNamespace(_resolve_context_filters=lambda q, e: (["parameter_type"], "heuristic"))
        self.assertEqual(variant.resolve_filters(serve, graph, "question", True)[0], [])


@unittest.skipUnless(nx is not None and importlib.util.find_spec("graphify"),
                     "Use pinned Graphify runtime for integration tests")
class RealGraphifyTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.graph = nx.DiGraph()
        for i in range(16):
            self.graph.add_node(f"n{i}", label=f"alpha model {i}",
                source_file=f"tutorials/case{i}/settings.txt", source_location=f"L{i+1}",
                community="test community")
        for i in range(1, 16):
            self.graph.add_edge(f"n{i}", "n0", relation="documents", confidence="EXTRACTED",
                source_file=f"tutorials/case{i}/settings.txt", source_location=f"L{i+1}")
        self.path = self.root / "graph.json"
        self.path.write_text(json.dumps(nx.node_link_data(self.graph, edges="links")))
        self.backend = variant.Backend(self.path)
        self.inverse = {f"tutorials/case{i}/settings.txt": f"tutorials/case{i}/settings" for i in range(16)}

    def query(self, mode, text="alpha", budget=400, cap=2000):
        return self.backend.payload(text, budget, cap, self.inverse, mode)

    def test_original_coordinator_matches_upstream(self):
        raw, _ = reference.Backend(self.path).query("alpha", 400)
        expected = reference.bounded_payload(reference.original_paths(raw, self.inverse), 2000, variant.wire)
        actual, _ = self.query("original")
        self.assertEqual(actual, expected)

    def test_atomic_keeps_same_candidates_and_whole_edges(self):
        original, before = self.query("original")
        actual, after = self.query("atomic")
        for key in ["seeds", "visited_nodes", "candidate_edges"]:
            self.assertEqual(before[key], after[key])
        self.assertLessEqual(len(variant.wire(actual)), 2000)
        packing = after["packing"]
        self.assertTrue(packing["shown_edges"])
        self.assertLessEqual(packing["body_characters"] + packing["reserved_notice_characters"], 1200)
        for edge in packing["shown_edges"]:
            self.assertIn(edge["line"], actual["graph_navigation"].splitlines())
            for node in edge["endpoints"]:
                self.assertIn(packing["endpoint_records"][node], actual["graph_navigation"].splitlines())
        self.assertNotIn("items", actual)
        self.assertEqual(actual["evidence"], "derived_navigation_only_read_original_sources")

    def test_filter_change_does_not_change_seeds(self):
        _, original = self.query("original", "alpha fields")
        _, fixed = self.query("compatible", "alpha fields")
        self.assertEqual(original["seeds"], fixed["seeds"])
        self.assertEqual(original["candidate_edges"], [])
        self.assertTrue(fixed["candidate_edges"])
        self.assertEqual(fixed["filters"]["dropped"], ["field"])

    def test_combined_changes_only_packing_relative_to_compatible(self):
        _, compatible = self.query("compatible", "alpha fields")
        _, combined = self.query("combined", "alpha fields")
        for key in ["seeds", "visited_nodes", "candidate_edges", "filters"]:
            self.assertEqual(compatible[key], combined[key])

    def test_preserves_direction_and_source_mapping(self):
        payload, audit = self.query("atomic")
        self.assertTrue(audit["packing"]["shown_edges"])
        for edge in audit["packing"]["shown_edges"]:
            line = edge["line"]
            self.assertIn("--> alpha model 0", line)
            self.assertIn("at=tutorials/", line)
            self.assertNotIn(".txt:L", line)
        self.assertNotIn(".txt loc=", payload["graph_navigation"])

    def test_repeated_payloads_identical_graph_file_untouched(self):
        before = self.path.read_bytes()
        first = self.query("combined", "alpha fields")[0]
        second = self.query("combined", "alpha fields")[0]
        self.assertEqual(first, second)
        self.assertEqual(before, self.path.read_bytes())

    def test_tiny_budget_never_splits_a_relation(self):
        payload, audit = self.query("atomic", budget=100, cap=1000)
        self.assertLessEqual(len(variant.wire(payload)), 1000)
        self.assertTrue(payload["truncated"])
        for edge in audit["packing"]["shown_edges"]:
            self.assertTrue(set(edge["endpoints"]) <= set(audit["packing"]["shown_nodes"]))

    def test_no_match_no_fabricated_source(self):
        payload, audit = self.query("combined", text="zzzznonexistenttoken")
        self.assertEqual(payload["status"], "no_match")
        self.assertEqual(audit["visited_nodes"], [])

    def test_graph_labels_are_sanitized_by_original_renderer(self):
        self.backend.graph.nodes["n1"]["label"] = "alpha\x1b[31m hostile"
        payload, _ = self.query("atomic")
        self.assertNotIn("\x1b", payload["graph_navigation"])

    def test_invalid_modes_and_budgets_are_rejected(self):
        for args in [("alpha", 100, 999, {}, "atomic"),
                     ("alpha", 100, 1000, {}, "invented"),
                     ("", 100, 1000, {}, "atomic")]:
            with self.assertRaises(ValueError):
                self.backend.payload(*args)


if __name__ == "__main__":
    unittest.main()
