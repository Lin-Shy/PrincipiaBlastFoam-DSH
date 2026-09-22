import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/retrieval_method"))
import canonical_evidence_v1 as metrics


SHA = "a" * 64
GOLD = [
    {"id": "g1", "path": "manual/a.md", "start": 10, "end": 12,
     "sha256": SHA, "source_kind": "manual"},
    {"id": "g2", "path": "tutorials/case/0/U", "start": 20, "end": 21,
     "sha256": SHA, "source_kind": "tutorial"},
]


def unit(path, start, end, rank, chars=None, cumulative=None):
    return metrics.canonical_unit(
        path=path, start=start, end=end, source_sha256=SHA,
        source_kind="manual" if path.startswith("manual/") else "tutorial",
        native_unit={"id": rank}, native_rank=rank, query_step=0,
        source_characters=chars if chars is not None else end - start + 1,
        cumulative_returned_characters=cumulative if cumulative is not None else rank * 100,
        cumulative_query_seconds=rank / 10,
    )


def test_chunk_can_cover_multiple_gold_atoms_and_complete_set():
    gold = [
        {"id": "g1", "path": "manual/a.md", "start": 10, "end": 12},
        {"id": "g2", "path": "manual/a.md", "start": 15, "end": 16},
    ]
    scored = metrics.score(gold, [unit("manual/a.md", 8, 20, 1)])
    assert scored["top_k"]["1"]["recall"] == 1
    assert scored["top_k"]["1"]["complete_evidence_set_success"] == 1


def test_multiple_units_can_jointly_complete_one_gold_atom():
    scored = metrics.score([GOLD[0]], [
        unit("manual/a.md", 10, 10, 1),
        unit("manual/a.md", 11, 12, 2),
    ])
    assert scored["top_k"]["1"]["recall"] == 0
    assert scored["top_k"]["3"]["recall"] == 1


def test_duplicate_exact_evidence_keeps_first_rank_only():
    first = unit("manual/a.md", 10, 12, 1, cumulative=100)
    duplicate = unit("manual/a.md", 10, 12, 2, cumulative=200)
    result = metrics.deduplicate([first, duplicate])
    assert len(result) == 1
    assert result[0]["first_rank"] == 1
    assert result[0]["cumulative_returned_characters"] == 100


def test_budget_truncation_uses_actual_cumulative_returned_characters():
    scored = metrics.score(GOLD, [
        unit("manual/a.md", 10, 12, 1, cumulative=6000),
        unit("tutorials/case/0/U", 20, 21, 2, cumulative=12001),
    ])
    assert scored["by_returned_character_budget"]["6000"]["recall"] == .5
    assert scored["by_returned_character_budget"]["12000"]["recall"] == .5
    assert scored["by_returned_character_budget"]["24000"]["recall"] == 1


def test_multi_source_complete_requires_both_sources():
    scored = metrics.score(GOLD, [unit("manual/a.md", 9, 13, 1)])
    assert scored["top_k"]["10"]["hit_rate"] == 1
    assert scored["top_k"]["10"]["recall"] == .5
    assert scored["top_k"]["10"]["complete_evidence_set_success"] == 0


def test_same_path_from_different_corpus_hash_does_not_match():
    wrong = unit("manual/a.md", 10, 12, 1)
    scored = metrics.score([{**GOLD[0], "sha256": "b" * 64}], [wrong])
    assert scored["top_k"]["1"]["recall"] == 0
    assert scored["top_k"]["1"]["hit_rate"] == 0


def test_precision_uses_k_denominator_and_mrr_uses_first_overlap():
    scored = metrics.score([GOLD[0]], [
        unit("manual/other.md", 1, 3, 1),
        unit("manual/a.md", 11, 11, 2),
    ])
    assert scored["mrr"] == .5
    assert scored["top_k"]["3"]["precision"] == pytest.approx(1 / 3)
    assert scored["top_k"]["3"]["recall"] == 0


def test_aggregate_keeps_fact_family_as_declared_unit():
    rows = []
    for question, family, hit in (("q1", "f1", True), ("q2", "f1", False), ("q3", "f2", True)):
        units = [unit("manual/a.md", 10, 12, 1)] if hit else []
        rows.append({"question_id": question, "family": family,
                     "metrics": metrics.score([GOLD[0]], units)})
    summary = metrics.aggregate(rows)
    assert summary["question_mean"]["top_k"]["1"]["recall"] == pytest.approx(2 / 3)
    assert summary["family_macro"]["top_k"]["1"]["recall"] == pytest.approx(.75)


def test_identifier_layer_deduplicates_and_scores_required_files():
    scored = metrics.score_identifier_layer(
        ["manual/a.md", "tutorials/c/0/U"],
        ["other", "manual/a.md", "manual/a.md", "tutorials/c/0/U"],
    )
    assert scored["ranked_ids"] == ["other", "manual/a.md", "tutorials/c/0/U"]
    assert scored["mrr"] == .5
    assert scored["top_k"]["1"]["recall"] == 0
    assert scored["top_k"]["3"]["recall"] == 1
    assert scored["top_k"]["3"]["complete_set_success"] == 1
