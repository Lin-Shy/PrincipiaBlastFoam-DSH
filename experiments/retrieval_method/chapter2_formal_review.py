"""隔离正式盲评分与一次必要裁决；不导入或调用检索器。"""
import argparse
import fcntl
import json
from pathlib import Path
import random
import time

from chapter2_formal_runtime import sha, load, save, verify, jobs, ANSWER_ARMS, transport
from chapter2_pointwise_review import validate


def prepare(root, protocol, protocol_sha):
    for arm in ANSWER_ARMS:
        if not (root / "completion" / ("answer--" + arm + ".json")).exists():
            raise ValueError("complete all six frozen answer grids before blind scoring")
    annotation_file = Path(protocol["private_scoring_input"]["path"])
    if sha(annotation_file) != protocol["private_scoring_input"]["sha256"]:
        raise ValueError("frozen scoring annotation drift")
    annotations = {a["id"]: a for a in load(annotation_file)}
    entries = []
    for key, repeat, question in jobs(protocol):
        for arm in ANSWER_ARMS:
            answer_file = root / "answers" / arm / key / "compiled.json"
            answer = load(answer_file)
            native_file = root / "native" / arm / (key + ".json")
            if answer["protocol_sha256"] != protocol_sha or answer["native_response_sha256"] != sha(native_file):
                raise ValueError("frozen answer input drift")
            native = load(native_file)
            sources = {u["citation_id"]: u for u in native["answer_delivery"]["units"] if u.get("mapping_status") != "unmappable"}
            references = []
            if answer["status"] == "complete_structure":
                for claim in answer["answer"]["claims"]:
                    for cite in claim["citations"]:
                        unit = sources[cite["source"]]
                        a, b = cite["start"], cite["end"]
                        references.append({"index": len(references), "claim": claim["text"], "path": unit["path"],
                            "start": a, "end": b, "source_sha256": unit["source_sha256"],
                            "quote": "\n".join(unit["lines"][a-unit["start"]:b-unit["start"]+1])})
                actual = answer["answer_text"]
            else:
                final = load(answer_file.parent / "final.json")
                actual = final.get("raw_response", {}).get("choices", [{}])[0].get("message", {}).get("content", "")
            annotation = annotations[question["family_id"]]
            entries.append({"identity": {"key": key, "question_id": question["id"], "family_id": question["family_id"],
                "repeat": repeat, "category": annotation["category"], "arm": arm, "answer_structure": answer["status"],
                "answer_sha256": sha(answer_file)},
                "packet": {"question": question["question"], "answer_text": actual, "references": references,
                    "gold_evidence": annotation["evidence"], "allowed": annotation["allowed"],
                    "forbidden": annotation["forbidden"], "ambiguity": annotation["ambiguity"],
                    "gold_points": [{"index": i, "requirement": text} for i, text in enumerate(annotation["gold"])]}})
    random.Random(protocol["seed"]).shuffle(entries)
    identity, review_jobs = {}, {}
    for index, entry in enumerate(entries, 1):
        blind = f"B{index:04d}"
        identity[blind] = entry["identity"]
        packet = entry["packet"]
        save(root / "evaluation_only" / "blind_packets" / (blind + ".json"), packet)
        base = {k: packet[k] for k in ("question", "answer_text", "references")}
        for point in packet["gold_points"]:
            job = blind + "--p" + str(point["index"])
            file = root / "evaluation_only" / "review_packets" / (job + ".json")
            save(file, {**base, "requirement": point["requirement"]})
            review_jobs[job] = {"kind": "point", "blind_id": blind, "point_index": point["index"], "packet_sha256": sha(file)}
        job = blind + "--citations"
        file = root / "evaluation_only" / "review_packets" / (job + ".json")
        save(file, base)
        review_jobs[job] = {"kind": "citations", "blind_id": blind, "packet_sha256": sha(file)}
    save(root / "evaluation_only" / "identity.json", identity)
    save(root / "evaluation_only" / "review_jobs.json", {"protocol_sha256": protocol_sha, "jobs": review_jobs,
        "identity_sha256": sha(root / "evaluation_only" / "identity.json")})
    # 预冻结种子按族分层选择，整组六臂同题同重复，不按得分筛选。
    strata = {}
    for family, annotation in sorted(annotations.items()):
        strata.setdefault(annotation["category"], []).append(family)
    rng = random.Random(protocol["seed"])
    selected = []
    for category, count in protocol["human_review"]["families_by_category"].items():
        families = strata[category][:]
        rng.shuffle(families)
        for family in families[:count]:
            selected.append((family, rng.randint(1, 3), rng.randint(1, 3)))
    sample = []
    for family, variant, repeat in selected:
        for blind, item in identity.items():
            if item["family_id"] == family and item["question_id"].endswith("-n" + str(variant)) and item["repeat"] == repeat:
                packet = load(root / "evaluation_only" / "blind_packets" / (blind + ".json"))
                sample.append({"blind_id": blind, **packet, "human_verdict": None, "human_notes": ""})
    rng.shuffle(sample)
    if len(sample) != protocol["human_review"]["sessions"]:
        raise ValueError("pre-registered human sample count mismatch")
    save(root / "human_review" / "blind_sample.json", {"protocol_sha256": protocol_sha, "instructions": protocol["human_review"], "cases": sample})
    save(root / "completion" / "review_prepare.json", {"status": "complete", "sessions": len(identity),
        "jobs": len(review_jobs), "protocol_sha256": protocol_sha,
        "review_jobs_sha256": sha(root / "evaluation_only" / "review_jobs.json"),
        "human_sample_sha256": sha(root / "human_review" / "blind_sample.json")})


def run(root, protocol, protocol_sha, settings, adjudicate=False, shard=0):
    qa, net = transport(settings)
    manifest = load(root / "evaluation_only" / "review_jobs.json")
    prepared = load(root / "completion" / "review_prepare.json")
    if prepared["review_jobs_sha256"] != sha(root / "evaluation_only" / "review_jobs.json"):
        raise ValueError("prepared scoring manifest drift")
    if manifest["identity_sha256"] != sha(root / "evaluation_only" / "identity.json"):
        raise ValueError("prepared blind identity drift")
    if manifest["protocol_sha256"] != protocol_sha:
        raise ValueError("blind review manifest drift")
    for index, (key, job) in enumerate(manifest["jobs"].items()):
        if index % protocol["scoring_shards"] != shard:
            continue
        file = root / "evaluation_only" / "review_packets" / (key + ".json")
        if sha(file) != job["packet_sha256"]:
            raise ValueError("blind scoring packet drift")
        packet = load(file)
        if adjudicate:
            first = load(root / "evaluation_only" / "reviews" / key / "compiled.json")
            if first["status"] == "valid_structure" and not (job["kind"] == "citations" and first["review"]["state"] == "uncertain"):
                continue
            folder = root / "evaluation_only" / "adjudications" / key
        else:
            folder = root / "evaluation_only" / "reviews" / key
        output = folder / "compiled.json"
        if output.exists():
            old = load(output)
            if old["protocol_sha256"] != protocol_sha or old["packet_sha256"] != job["packet_sha256"] or old["response_sha256"] != sha(folder / "review.json"):
                raise ValueError("existing score drift")
            continue
        prompt = protocol["prompts"]["point" if job["kind"] == "point" else "citations"]
        if adjudicate:
            # 首次语义标签不发给裁决，防止方法信息及默认标签锚定。
            prompt += "\n这是预注册的一次必要裁决。此前输出结构无效或支持性无法确定；请独立核验原材料并严格遵守字段与枚举。不改变实际回答，不补写事实，材料仍不足时保留不确定。"
        response = net.fetch(folder, "review", qa.request([{"role": "system", "content": prompt},
            {"role": "user", "content": qa.wire(packet)}], final=False), net.SECRET)
        try:
            choice = qa.choice(response)
            if choice["finish_reason"] != "stop":
                raise ValueError("review response truncated")
            value = validate(qa.decode_json_prefix(choice["message"]["content"]), packet, job["kind"])
            compiled = {"status": "valid_structure", "review": value}
        except (ValueError, KeyError, TypeError) as error:
            compiled = {"status": "invalid_structure", "review": None, "error": str(error)}
        save(output, {**compiled, "packet_sha256": job["packet_sha256"], "response_sha256": sha(folder / "review.json"),
            "protocol_sha256": protocol_sha, "adjudication": adjudicate})
        print("DONE", "adjudication" if adjudicate else "review", key, compiled["status"], flush=True)
    output = root / "completion" / (("adjudication" if adjudicate else "review") + "--" + str(shard) + ".json")
    if not output.exists():
        save(output, {"status": "complete", "protocol_sha256": protocol_sha})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage", choices=("prepare", "run", "adjudicate"))
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--settings-file", type=Path)
    p.add_argument("--shard", type=int, choices=(0, 1, 2), default=0)
    args = p.parse_args()
    protocol, protocol_sha = verify(args.root)
    lockpath = args.root / "locks" / ("review--" + args.stage + "--" + str(args.shard) + ".lock")
    lockpath.parent.mkdir(parents=True, exist_ok=True)
    with lockpath.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.stage == "prepare":
            prepare(args.root, protocol, protocol_sha)
        else:
            run(args.root, protocol, protocol_sha, args.settings_file, args.stage == "adjudicate", args.shard)


if __name__ == "__main__":
    main()
