import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments/retrieval_method'))
from chapter2_v4_retrieval_probe import retrieval_metrics


def span(path, start, end):return dict(path=path, start=start, end=end, mapping_status='mapped')
def gold(path, start, end):return dict(path=path, line_start=start, line_end=end)
def record(candidates, lines=()):
    return dict(candidates=candidates, deliveries={'6000': dict(original_lines=[dict(path=p, line=n) for p, n in lines])})


def test_joint_line_coverage_and_unmappable_rank_penalty():
    r = record([dict(path='image', start=None, end=None, mapping_status='unmappable'), span('manual/a', 10, 11), span('manual/a', 12, 14)])
    metrics = retrieval_metrics(r, [gold('manual/a', 10, 14)])
    assert metrics['recall@1'] == 0 and metrics['recall@3'] == 1
    assert metrics['mrr'] == 1 / 3
    assert math.isclose(metrics['file_ndcg@10'], 1 / math.log2(3))


def test_duplicate_chunks_do_not_make_file_ndcg_exceed_one():
    r = record([span('manual/a', i, i + 20) for i in range(1, 11)])
    metrics = retrieval_metrics(r, [gold('manual/a', 12, 14)])
    assert metrics['file_ndcg@10'] == 1
    assert metrics['recall@1'] == 1


def test_one_chunk_can_cover_multiple_atoms_without_multiple_file_gains():
    r = record([span('manual/a', 1, 20)])
    metrics = retrieval_metrics(r, [gold('manual/a', 2, 5), gold('manual/a', 10, 14)])
    assert metrics['recall@1'] == metrics['complete@1'] == metrics['file_ndcg@10'] == 1


def test_truncated_delivery_is_scored_on_full_actual_lines_only():
    r = record([span('manual/a', 10, 14)], [('manual/a', n) for n in range(10, 14)])
    metrics = retrieval_metrics(r, [gold('manual/a', 10, 14)])
    assert metrics['recall@1'] == 1
    assert metrics['delivered_recall_6000'] == metrics['delivered_complete_6000'] == 0


def test_empty_retriever_keeps_zero_metrics():
    metrics = retrieval_metrics(record([]), [gold('manual/a', 1, 2)])
    assert all(value == 0 for value in metrics.values())
