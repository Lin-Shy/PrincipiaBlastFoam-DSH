"""Check sealed readout pairs against the archived grading tables."""
import json
import zipfile

from local_sealed_tables import match, table
from readout_pair_retest import ARMS, OUT, TASKS, batch, read, sha


def compare(task):
    source = next(row for row in read(batch/"tasks.json") if row["id"] == task)
    grading = batch/source["grading_zip"]
    if sha(grading) != source["grading_sha256"]:
        raise ValueError("grading ZIP changed")
    pair = OUT/task
    receipts = {arm:read(pair/arm/"sealed.json") for arm in ARMS}
    with zipfile.ZipFile(grading) as archive:
        reference = {n:table(archive.read(n)) for n in ("baseline.csv","expected_changed.csv")}
    scores = {}
    for arm, receipt in receipts.items():
        submission = pair/arm/"submission.zip"
        if sha(submission) != receipt["archive_sha256"]:
            raise ValueError("submission ZIP changed")
        with zipfile.ZipFile(submission) as archive:
            matches = {n:[] for n in reference}
            for name in archive.namelist():
                if not name.lower().endswith(".csv"):
                    continue
                try:
                    candidate = table(archive.read(name))
                except (UnicodeError,ValueError,StopIteration):
                    continue
                for ref, data in reference.items():
                    mapping = match(data,candidate)
                    if mapping:
                        matches[ref].append(dict(file=name,columns=mapping))
            scores[arm] = dict(archive_sha256=receipt["archive_sha256"],tables=matches,
                               requests=receipt["requests"],reported_tokens=receipt["known_tokens"],
                               files=archive.namelist())
    return scores


if __name__ == "__main__":
    for short in TASKS:
        task = "CH3-DEV-"+short
        if all((OUT/task/arm/"sealed.json").exists() for arm in ARMS):
            print(json.dumps({task:compare(task)},ensure_ascii=True))
