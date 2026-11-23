"""Check the actual candidate on the operator side before reserving a PIPE-01 job."""
import hashlib
import json
from pathlib import Path
import time


def candidate(raw,validate,check_direction):
    if len(raw)>65536:
        raise ValueError("case exceeds 65536 bytes")
    case = json.loads(raw)
    validate(case)
    check_direction(case["rows"],driving_sign=1)
    return case


def await_input(root,validate,check_direction,write):
    exchange = root/"workspace/pipe_exchange"
    evidence = root/"admission"
    evidence.mkdir(exist_ok=True)
    request = exchange/"request.json"
    while not (root/"sealed.json").exists():
        if not request.is_file():
            time.sleep(1)
            continue
        with request.open("rb") as stream:
            raw = stream.read(65537)
        key = hashlib.sha256(raw).hexdigest()
        try:
            case = candidate(raw,validate,check_direction)
        except (ValueError,TypeError,OverflowError) as exc:
            refusal = dict(status="rejected_before_submission",candidate_sha256=key,
                reason=str(exc),job_id=None,remaining_jobs=1,
                guidance="For negative dp/dz and a positive diagonal for minus diffusion, "
                         "use the forcing corresponding to -dp/dz. Revise the source and register a new matrix.")
            record = evidence/(key+".rejected.json")
            if not record.exists():
                write(record,refusal)
            # Keep the rejection bound to the actual bytes, even for a custom producer.
            result = exchange/(key+".rejected.json")
            if not result.exists():
                write(result,refusal)
            time.sleep(1)
            continue
        write(evidence/"accepted.json",dict(candidate_sha256=key,policy="known positive driving; monotone diffusion rows"))
        return case
    return None
