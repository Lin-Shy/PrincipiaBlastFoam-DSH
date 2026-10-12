"""GOAL要求的统一映射、预算和读取结构确定性核验；不访问题库。"""
import argparse
import hashlib
import json
from pathlib import Path

from chapter2_canonical_delivery import canonicalize, render
from canonical_evidence_v1 import score
from chapter2_graph_retriever import GraphRetriever
from chapter2_production_guard import install


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError("new verification artifact required")
    source_sha = "a"*64
    def item(rank, path, start, end):
        return {"native_rank": rank, "native_unit": f"native-{rank}", "path": path,
                "source_sha256": source_sha, "source_kind": "manual" if path.startswith("manual/") else "tutorial",
                "ranges": [{"start": start, "end": end, "lines": [f"raw-{i}" for i in range(start,end+1)]}]}
    native = {"items": [item(1,"tutorials/example",1,6), item(2,"tutorials/example",1,6),
                        item(3,"tutorials/example",4,8), item(4,"manual/example",1,3)]}
    units = canonicalize(native, 0.1)
    checks = {}
    checks["duplicate_retains_first_native_rank"] = len(units)==3 and [u["native_rank"] for u in units]==[1,3,4]
    checks["overlap_keeps_only_new_lines"] = (units[1]["start"], units[1]["end"])==(7,8)
    gold = [{"id":"first", "path":"tutorials/example","start":2,"end":3,"sha256":source_sha},
            {"id":"second", "path":"tutorials/example","start":5,"end":6,"sha256":source_sha},
            {"id":"union", "path":"tutorials/example","start":5,"end":8,"sha256":source_sha},
            {"id":"manual", "path":"manual/example","start":1,"end":3,"sha256":source_sha}]
    full = render(units)
    metrics = score(gold, full["units"])
    checks["one_native_unit_contains_multiple_atoms"] = metrics["top_k"]["1"]["recall"]==0.5
    checks["continuous_union_covers_atom"] = metrics["top_k"]["3"]["recall"]==1
    checks["multiple_sources_complete"] = metrics["top_k"]["3"]["complete_evidence_set_success"]==1
    budget = full["text"].index("2: raw-2")+3
    partial = render(units,budget)
    checks["partial_raw_line_not_counted"] = len(partial["units"])==1 and partial["units"][0]["end"]==1 and partial["units"][0]["truncated"]
    checks["budget_includes_metadata"] = partial["returned_characters"]==len(partial["text"])<=budget
    checks["budget_does_not_promote_later_units"] = len(partial["units"])==1 and partial["units"][0]["native_rank"]==1
    checks["input_units_unchanged"] = units[0]["end"]==6 and units[0]["cumulative_returned_characters"]==0
    checks["config_comments_and_quotes_do_not_open_scopes"] = GraphRetriever.owner_ranges([
        "outer", "{", '// }', 'value "{";', "nested", "{", " x 2;", "}", "}"])==[(5,8,"{"),(1,9,"{")]
    checks["manual_code_fence_headings_ignored"] = GraphRetriever.manual_headings(["# Root", "```", "## code", "```", "## Real"])==[(1,1),(5,2)]
    checks["canonical_scope_always_identified"] = all(unit["scope_id"] for unit in units)
    guard = install(offline=True)
    denied = []
    for path in ("evaluation_only/test.annotations.json", "data_design/drafts.json", "public_test/questions.json", "development/dev.annotations.json"):
        try:
            Path(path).read_bytes()
        except PermissionError:
            denied.append(path)
    checks["production_guard_blocks_gold_design_and_unfrozen_test"] = len(denied)==4
    if not all(checks.values()):
        raise AssertionError(json.dumps(checks))
    out = {"schema":"canonical-delivery-deterministic-verification-v1", "checks":checks,
           "passed":len(checks), "failed":0, "guard":guard, "model_calls":0,
           "implementation_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           "dependency_sha256":{name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest() for name in
                                ("chapter2_graph_retriever.py","chapter2_canonical_delivery.py","canonical_evidence_v1.py","chapter2_production_guard.py","candidate_graph_utils.py","index_free_graph_evidence.py","candidate_paths.py")},
           "limits":"synthetic adapter/owner checks and Python audit hook; not answer quality, OS isolation or graph semantic validation"}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(out,ensure_ascii=False))


if __name__=="__main__":
    main()
