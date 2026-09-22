"""统一原文证据单元与补充性检索质量指标。

本模块只处理已经返回的权威原文范围，不调用模型、不读取留出集，也不把
Graphify 节点、图节点或文本 chunk 直接当作可横向比较的相关项。适配器必须先
把原生结果映射为 ``canonical-evidence-v1`` 的原始路径和精确行段。
"""
from __future__ import annotations

from collections import defaultdict
import math
import statistics


SCHEMA = "canonical-evidence-v1"
DEFAULT_K = (1, 3, 5, 10)
DEFAULT_BUDGETS = (6000, 12000, 24000)


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"invalid {name}")
    return value


def validate_gold(evidence):
    """Validate frozen required-evidence atoms without changing their granularity."""
    seen = set()
    result = []
    for atom in evidence:
        path = atom.get("path")
        start = _integer(atom.get("start"), "gold start", 1)
        end = _integer(atom.get("end"), "gold end", 1)
        if not isinstance(path, str) or not path or start > end:
            raise ValueError("invalid gold evidence atom")
        identity = (path, start, end)
        if identity in seen:
            raise ValueError("duplicate gold evidence atom")
        seen.add(identity)
        result.append({
            "id": atom.get("id") or f"{path}:{start}-{end}",
            "path": path,
            "start": start,
            "end": end,
            "sha256": atom.get("sha256"),
            "source_kind": atom.get("source_kind"),
        })
    if not result:
        raise ValueError("at least one gold evidence atom is required")
    return result


def canonical_unit(*, path, start, end, source_sha256, source_kind,
                   native_unit, native_rank, query_step,
                   source_characters, cumulative_returned_characters,
                   cumulative_query_seconds, case_id=None, scope_id=None):
    """Build one validated canonical unit while retaining native provenance."""
    start = _integer(start, "start", 1)
    end = _integer(end, "end", 1)
    if not isinstance(path, str) or not path or start > end:
        raise ValueError("invalid canonical evidence range")
    if not isinstance(source_sha256, str) or len(source_sha256) != 64:
        raise ValueError("invalid source sha256")
    _integer(native_rank, "native rank", 1)
    _integer(query_step, "query step", 0)
    _integer(source_characters, "source characters", 0)
    _integer(cumulative_returned_characters, "cumulative returned characters", 0)
    if not isinstance(cumulative_query_seconds, (int, float)) or cumulative_query_seconds < 0:
        raise ValueError("invalid cumulative query seconds")
    return {
        "schema": SCHEMA,
        "path": path,
        "source_sha256": source_sha256,
        "start": start,
        "end": end,
        "source_kind": source_kind,
        "case_id": case_id,
        "file_id": path,
        "scope_id": scope_id,
        "native_unit": native_unit,
        "native_rank": native_rank,
        "query_step": query_step,
        "source_characters": source_characters,
        "cumulative_returned_characters": cumulative_returned_characters,
        "cumulative_query_seconds": float(cumulative_query_seconds),
    }


def deduplicate(units):
    """Keep the first occurrence of an identical authoritative source range."""
    seen = set()
    result = []
    for unit in units:
        if unit.get("schema") != SCHEMA:
            raise ValueError("unrecognized evidence schema")
        identity = (unit["source_sha256"], unit["path"], unit["start"], unit["end"])
        if identity in seen:
            continue
        seen.add(identity)
        result.append({**unit, "first_rank": len(result) + 1})
    return result


def _same_source(unit, atom):
    return (unit["path"] == atom["path"]
            and (not atom.get("sha256")
                 or unit["source_sha256"] == atom["sha256"]))


def _overlap(unit, atom):
    return (_same_source(unit, atom)
            and unit["start"] <= atom["end"]
            and atom["start"] <= unit["end"])


def _contains(unit, atom):
    return (_same_source(unit, atom)
            and unit["start"] <= atom["start"]
            and atom["end"] <= unit["end"])


def _covered(atom, units):
    intervals = sorted(
        (max(atom["start"], unit["start"]), min(atom["end"], unit["end"]))
        for unit in units if _overlap(unit, atom)
    )
    cursor = atom["start"]
    for start, end in intervals:
        if start > cursor:
            return False
        cursor = max(cursor, end + 1)
        if cursor > atom["end"]:
            return True
    return False


def _rank_metrics(gold, selected, k):
    relevant = [any(_overlap(unit, atom) for atom in gold) for unit in selected]
    grades = [
        2 if any(_contains(unit, atom) for atom in gold)
        else 1 if relevant[index] else 0
        for index, unit in enumerate(selected)
    ]
    covered = [atom["id"] for atom in gold if _covered(atom, selected)]
    dcg = sum((2 ** grade - 1) / math.log2(rank + 1)
              for rank, grade in enumerate(grades, 1))
    ideal_grades = [2] * min(len(gold), k)
    idcg = sum((2 ** grade - 1) / math.log2(rank + 1)
               for rank, grade in enumerate(ideal_grades, 1))
    return {
        "retrieved": len(selected),
        "relevant_retrieved": sum(relevant),
        "recall": len(covered) / len(gold),
        "hit_rate": int(any(relevant)),
        "precision": sum(relevant) / k,
        "ndcg": dcg / idcg if idcg else 0.0,
        "complete_evidence_set_success": int(len(covered) == len(gold)),
        "covered_gold_ids": covered,
    }


def score(gold_evidence, units, *, ks=DEFAULT_K, budgets=DEFAULT_BUDGETS):
    """Score one query after canonical mapping and first-occurrence de-duplication.

    Precision and nDCG use the frozen *required* evidence set as relevance labels.
    Because that set is not an exhaustive pool of every useful passage, precision is
    explicitly a required-gold precision lower bound rather than corpus-wide precision.
    """
    gold = validate_gold(gold_evidence)
    ranked = deduplicate(units)
    ks = tuple(sorted(set(_integer(k, "k", 1) for k in ks)))
    budgets = tuple(sorted(set(_integer(b, "budget", 1) for b in budgets)))
    first = next((index for index, unit in enumerate(ranked, 1)
                  if any(_overlap(unit, atom) for atom in gold)), None)
    top_k = {str(k): _rank_metrics(gold, ranked[:k], k) for k in ks}
    by_budget = {}
    for budget in budgets:
        selected = [unit for unit in ranked
                    if unit["cumulative_returned_characters"] <= budget]
        metrics = _rank_metrics(gold, selected, max(1, len(selected)))
        by_budget[str(budget)] = {
            "retrieved": len(selected),
            "recall": metrics["recall"],
            "hit_rate": metrics["hit_rate"],
            "complete_evidence_set_success": metrics["complete_evidence_set_success"],
            "covered_gold_ids": metrics["covered_gold_ids"],
        }
    return {
        "schema": "canonical-evidence-retrieval-metrics-v1",
        "gold_evidence_count": len(gold),
        "deduplicated_result_count": len(ranked),
        "mrr": 1 / first if first else 0.0,
        "first_relevant_rank": first,
        "top_k": top_k,
        "by_returned_character_budget": by_budget,
        "returned_characters": max(
            (unit["cumulative_returned_characters"] for unit in ranked), default=0),
        "query_seconds": max(
            (unit["cumulative_query_seconds"] for unit in ranked), default=0.0),
        "precision_scope": "required-gold-only-lower-bound; gold is not an exhaustive relevance pool",
    }


def score_identifier_layer(gold_ids, ranked_ids, *, ks=DEFAULT_K):
    """Score a canonical case/file/scope identifier ranking.

    Native units must be mapped to one comparable identifier layer before this
    function is called.  Duplicate identifiers retain only their first rank.
    """
    gold = []
    for value in gold_ids:
        if not isinstance(value, str) or not value:
            raise ValueError("invalid gold identifier")
        if value not in gold:
            gold.append(value)
    if not gold:
        raise ValueError("at least one gold identifier is required")
    ranked = []
    for value in ranked_ids:
        if not isinstance(value, str) or not value:
            continue
        if value not in ranked:
            ranked.append(value)
    relevant = set(gold)
    first = next((index for index, value in enumerate(ranked, 1)
                  if value in relevant), None)
    top_k = {}
    for k in sorted(set(_integer(value, "k", 1) for value in ks)):
        selected = ranked[:k]
        hits = [value for value in selected if value in relevant]
        covered = [value for value in gold if value in selected]
        dcg = sum(1 / math.log2(rank + 1)
                  for rank, value in enumerate(selected, 1) if value in relevant)
        idcg = sum(1 / math.log2(rank + 1)
                   for rank in range(1, min(len(gold), k) + 1))
        top_k[str(k)] = {
            "retrieved": len(selected),
            "relevant_retrieved": len(hits),
            "recall": len(covered) / len(gold),
            "hit_rate": int(bool(hits)),
            "precision": len(hits) / k,
            "ndcg": dcg / idcg if idcg else 0.0,
            "complete_set_success": int(len(covered) == len(gold)),
            "covered_gold_ids": covered,
        }
    return {
        "gold_count": len(gold),
        "deduplicated_result_count": len(ranked),
        "ranked_ids": ranked,
        "mrr": 1 / first if first else 0.0,
        "first_relevant_rank": first,
        "top_k": top_k,
        "precision_scope": "required-gold-only-lower-bound; gold is not an exhaustive relevance pool",
    }


def aggregate(rows, *, ks=DEFAULT_K, budgets=DEFAULT_BUDGETS):
    """Return question means and fact-family macro means for one method arm."""
    if not rows:
        raise ValueError("cannot aggregate an empty retrieval grid")

    def mean(values):
        return statistics.mean(values)

    def summary(selected):
        result = {
            "questions": len(selected),
            "mrr": mean([row["metrics"]["mrr"] for row in selected]),
            "returned_characters": mean([
                row["metrics"]["returned_characters"] for row in selected]),
            "query_seconds": mean([row["metrics"]["query_seconds"] for row in selected]),
            "top_k": {},
            "by_returned_character_budget": {},
        }
        for k in ks:
            key = str(k)
            result["top_k"][key] = {
                metric: mean([row["metrics"]["top_k"][key][metric]
                              for row in selected])
                for metric in ("recall", "hit_rate", "precision", "ndcg",
                               "complete_evidence_set_success")
            }
        for budget in budgets:
            key = str(budget)
            result["by_returned_character_budget"][key] = {
                metric: mean([
                    row["metrics"]["by_returned_character_budget"][key][metric]
                    for row in selected])
                for metric in ("recall", "hit_rate", "complete_evidence_set_success")
            }
        return result

    question = summary(rows)
    families = defaultdict(list)
    for row in rows:
        families[row["family"]].append(row)
    family_summaries = [summary(group) for group in families.values()]

    def family_mean(path):
        values = []
        for item in family_summaries:
            value = item
            for key in path:
                value = value[key]
            values.append(value)
        return mean(values)

    family_macro = {
        "families": len(families),
        "mrr": family_mean(("mrr",)),
        "returned_characters": family_mean(("returned_characters",)),
        "query_seconds": family_mean(("query_seconds",)),
        "top_k": {},
        "by_returned_character_budget": {},
    }
    for k in ks:
        key = str(k)
        family_macro["top_k"][key] = {
            metric: family_mean(("top_k", key, metric))
            for metric in ("recall", "hit_rate", "precision", "ndcg",
                           "complete_evidence_set_success")
        }
    for budget in budgets:
        key = str(budget)
        family_macro["by_returned_character_budget"][key] = {
            metric: family_mean(("by_returned_character_budget", key, metric))
            for metric in ("recall", "hit_rate", "complete_evidence_set_success")
        }
    return {"question_mean": question, "family_macro": family_macro}
