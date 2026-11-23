"""Export a traceable S10 time-series delivery from a native scalar probe file."""
import argparse
import csv
import hashlib
import json
import re
import shutil
from decimal import Decimal
from pathlib import Path


def export(raw, task, receipt, output):
    evidence = raw.read_bytes()
    digest = hashlib.sha256(evidence).hexdigest()
    run = json.loads(receipt.read_bytes())
    if digest != run["native_probe_sha256"]:
        raise ValueError("native probe hash differs from run receipt")
    conditions = json.loads(task.read_bytes(), parse_float=Decimal)
    locations = [tuple(point) for point in conditions["probe_locations_m"]]
    ambient = Decimal(conditions["ambient"]["pressure_absolute_Pa"])
    headers, rows = {}, []
    for line in evidence.decode().splitlines():
        match = re.fullmatch(r"#\s*Probe\s+(\d+)\s+\(([^)]+)\)\s*", line.strip())
        if match:
            index = int(match[1])
            if index in headers:
                raise ValueError("duplicate probe index")
            headers[index] = tuple(map(Decimal, match[2].split()))
        elif line.strip() and not line.lstrip().startswith("#"):
            values = tuple(map(Decimal, line.split()))
            if len(values) != len(locations)+1 or not all(v.is_finite() for v in values):
                raise ValueError("malformed pressure row")
            if rows and values[0] <= rows[-1][0]:
                raise ValueError("non-increasing native time")
            rows.append(values)
    if (not rows or set(headers) != set(range(len(locations))) or
            len(set(headers.values())) != len(locations) or set(headers.values()) != set(locations)):
        raise ValueError("missing or ambiguous native probe identity/data")
    columns = [next(i for i, point in headers.items() if point == required) for required in locations]
    output.mkdir(parents=True, exist_ok=False)
    (output/"raw").mkdir()
    (output/"raw/p").write_bytes(evidence)
    for source, name in [(task,"conditions.json"), (receipt,"run.json")]:
        shutil.copyfile(source, output/name)
    with (output/"pressure.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["time_s", *(name for i in range(1,len(columns)+1)
                         for name in (f"P{i}_absolute_pa", f"P{i}_overpressure_pa"))])
        for row in rows:
            writer.writerow([row[0], *(value for c in columns for value in (row[c+1],row[c+1]-ambient))])
    manifest = {"source_sha256":digest,"source_job_id":run["allocation"]["job_id"],
                "ambient_pa":str(ambient),"samples":len(rows),"native_time_s":[str(rows[0][0]),str(rows[-1][0])],
                "records":[{"sensor_id":f"P{i}","raw_file":"raw/p","column":c,
                            "position_m":list(map(str,headers[c]))} for i,c in enumerate(columns,1)],
                "pressure_csv_sha256":hashlib.sha256((output/"pressure.csv").read_bytes()).hexdigest()}
    (output/"observations.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ["raw","task","receipt","output"]:
        parser.add_argument(arg,type=Path)
    export(**vars(parser.parse_args()))
