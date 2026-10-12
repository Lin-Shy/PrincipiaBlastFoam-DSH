"""冻结 20/80 协议的评分规则，不覆写父版本。"""
import argparse
from pathlib import Path
import shutil
import time

from build_natural_navigation_v2 import sha, write
from build_natural_navigation_v6 import read


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--parent", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError("output exists")
    shutil.copytree(a.parent, a.output)
    (a.output / "manifest.json").unlink()
    rules = read(a.output / "scoring-rules.json")
    rules.update({"schema": "natural-navigation-scoring-v7-20-80",
                  "independent_unit": "family_id; six variants and three final repeats are clustered",
                  "statistics": "paired family bootstrap, 10000 resamples, seed 20260928; report planned and completed denominators",
                  "selection": "development 10 families only; implementation freezes before a single final holdout workflow",
                  "acceptance": None,
                  "legacy_threshold_status": "v5 five-round 8 percentage-point gate failed; the v7 holdout proceeds regardless and does not retune"})
    write(a.output / "scoring-rules.json", rules)
    manifest = read(a.parent / "manifest.json")
    manifest.update({"schema": "natural-navigation-qa-v7r1-20-80", "created_unix_ns": time.time_ns(),
                     "parent_v7_manifest_sha256": sha((a.parent / "manifest.json").read_bytes()),
                     "artifacts": {p.relative_to(a.output).as_posix(): sha(p.read_bytes())
                                   for p in sorted(a.output.rglob("*")) if p.is_file() and p.name != "manifest.json"}})
    write(a.output / "manifest.json", manifest)
    print(manifest["schema"])


if __name__ == "__main__":
    main()
