"""按原生首次出现顺序映射权威行段，独立应用实际送达字符预算。"""
from collections import defaultdict
import hashlib

from canonical_evidence_v1 import canonical_unit


def canonicalize(packet, query_seconds):
    seen, units = defaultdict(set), []
    for item in packet["items"]:
        if item.get("mapping_status") == "unmappable":
            # 此项是排名占位，不是可引用的原文行段；不能删除后重排。
            units.append({"schema": "canonical-evidence-v1", "mapping_status": "unmappable",
                          "path": "unmappable-native:"+str(item["native_unit"]), "original_path": item.get("path"),
                          "source_sha256": item.get("source_sha256") or hashlib.sha256(str(item["native_unit"]).encode()).hexdigest(),
                          "source_kind": "unmappable", "start": None, "end": None, "lines": [],
                          "native_unit": item["native_unit"], "native_rank": item["native_rank"],
                          "first_rank": len(units)+1, "source_characters": 0, "cumulative_returned_characters": 0,
                          "cumulative_query_seconds": query_seconds, "query_step": 0, "reason": item.get("reason")})
            continue
        for span in item["ranges"]:
            if len(span["lines"]) != span["end"]-span["start"]+1:
                raise ValueError("source range/line count mismatch")
            run = []
            def emit():
                if not run:
                    return
                start, end = run[0][0], run[-1][0]
                source_text = "\n".join(text for _, text in run)
                unit = canonical_unit(path=item["path"], start=start, end=end,
                    source_sha256=item["source_sha256"], source_kind=item["source_kind"],
                    native_unit=item["native_unit"], native_rank=item["native_rank"], query_step=0,
                    source_characters=len(source_text), cumulative_returned_characters=0,
                    cumulative_query_seconds=query_seconds,
                    case_id=item.get("scope", {}).get("case_directory"),
                    scope_id=str(item.get("scope", {}).get("dictionary") or item.get("dictionary") or f"{item['path']}:{span['start']}-{span['end']}"))
                units.append({**unit, "first_rank": len(units)+1, "lines": [text for _, text in run],
                              "route": item.get("route", []), "owner_range": [span["start"], span["end"]]})
                run.clear()
            for number, text in enumerate(span["lines"], span["start"]):
                key = (item["path"], item["source_sha256"])
                if number in seen[key]:
                    emit()
                else:
                    seen[key].add(number)
                    run.append((number, text))
            emit()
    return units


def render(units, budget=None):
    """只送达排名前缀；不跳过过长单元。行未送达完整不计作证据。"""
    if budget is not None and (type(budget) is not int or budget < 1):
        raise ValueError("positive character budget required")
    blocks, delivered = [], []
    size, stopped = 0, False
    for unit in units:
        if unit.get("mapping_status") == "unmappable":
            block = f"\n[UNMAPPED rank={unit['first_rank']}] {unit.get('original_path') or '(unknown path)'}: no authoritative text; not citable.\n"
            if budget is not None and size+len(block)>budget:
                stopped=True
                break
            size += len(block)
            blocks.append(block)
            delivered.append({**unit, "cumulative_returned_characters": size})
            continue
        header = (f"\n[S{unit['first_rank']}] {unit['path']} sha256={unit['source_sha256']} "
                  f"requested_lines={unit['start']}-{unit['end']}\n")
        if budget is not None and size+len(header) > budget:
            stopped = True
            break
        block = header
        full_lines = []
        for number, line in enumerate(unit["lines"], unit["start"]):
            text = f"{number}: {line}\n"
            if budget is not None and size+len(block)+len(text) > budget:
                stopped = True
                break
            block += text
            full_lines.append(line)
        if not full_lines:
            # 没有完整原文行时不发送孤立头部；保留预算停止事件。
            stopped = True
            break
        size += len(block)
        blocks.append(block)
        delivered.append({**unit, "end": unit["start"]+len(full_lines)-1, "lines": full_lines,
                          "source_characters": len("\n".join(full_lines)),
                          "cumulative_returned_characters": size,
                          "truncated": len(full_lines) != len(unit["lines"]),
                          "citation_id": f"S{unit['first_rank']}"})
        if stopped:
            break
    text = "".join(blocks)
    if len(text) != size or budget is not None and size > budget:
        raise AssertionError("actual delivery character accounting")
    return {"schema": "canonical-evidence-v1-actual-delivery", "text": text, "units": delivered,
            "returned_characters": size, "budget": budget, "stopped_at_budget": stopped,
            "policy": "native-first-occurrence; overlap lines removed; whole-line prefix; metadata included in characters"}
