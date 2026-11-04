"""Complete only unsubmitted cases of one unchanged synthetic suite.

Keep the original segment immutable and do not resubmit failed or partial cases.
Known literal-copy failures remain failures; unknown transport still halts.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse,json,re,sys,threading
from models import EXPERIMENT,MODELS,encoded,sha,now
from interface_repair_checks import run_model

class CompletionStop:
    def __init__(self):self.event=threading.Event()
    def is_set(self):return self.event.is_set()
    def set(self):
        error=sys.exc_info()[1]
        if isinstance(error,ValueError) and str(error) in {
            'Literal string roundtrip mismatch','Unique objective answer mismatch',
            'Wrong tool','Source args changed','Empty catalog not retained','Unexpected synthetic reference'}:
            return
        self.event.set()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-id',required=True);a=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',a.run_id):raise ValueError('Simple run ID required')
    source=EXPERIMENT/'technical/compact_actions_multiline_20261104';summary=json.loads((source/'summary.json').read_text('utf-8'))
    for name,h in summary['files'].items():
        if sha((source/name).read_bytes())!=h:raise ValueError('Source segment drift')
    code=Path(__file__).resolve().parent
    for name,h in summary['implementation'].items():
        if sha((code/name).read_bytes())!=h:raise ValueError('Suite implementation changed')
    fixture=json.loads((source/'fixtures.json').read_text('utf-8'));cases=fixture['cases'];missing={}
    for model in MODELS:
        missing[model]=[]
        for case in cases:
            folder=source/model/case['name'];requests=list((folder/'requests').glob('*.json'))
            if not requests:missing[model].append(case);continue
            if len(requests)!=len(case['turns']) or not (folder/'result.json').exists():raise ValueError('Partial or unknown case; do not automatically resubmit')
    expected=sum(len(c['turns']) for rows in missing.values() for c in rows)
    if expected!=22 or summary['model_requests']!=20:raise ValueError('This completion is restricted to the 22 unsubmitted calls')
    root=EXPERIMENT/'technical'/a.run_id;root.mkdir(parents=True,exist_ok=False)
    (root/'fixtures.json').write_bytes((source/'fixtures.json').read_bytes())
    (root/'completion_plan.json').write_bytes(encoded(dict(source_run=source.name,source_summary_sha256=sha((source/'summary.json').read_bytes()),
        unchanged_fixture_sha256=sha((source/'fixtures.json').read_bytes()),expected_requests=expected,
        requested_cases={m:[c['name'] for c in rows] for m,rows in missing.items()},
        repeated_requests=0,known_content_failures='retain_failed_and_continue_unsubmitted_cases_only',unknown_transport='halt',
        user_scope='Complete all three-model synthetic checks; no calibration60, acceptance or full experiment.')))
    bindings={**summary['implementation'],Path(__file__).name:sha(Path(__file__).read_bytes())}
    snapshots=root/'implementation';snapshots.mkdir()
    for name,h in bindings.items():
        raw=(code/name).read_bytes()
        if sha(raw)!=h:raise ValueError('Code drift')
        (snapshots/name).write_bytes(raw)
    stop=CompletionStop()
    with ThreadPoolExecutor(max_workers=3) as pool:reports=list(pool.map(lambda m:run_model(m,root,missing[m],stop),MODELS))
    requests=list(root.glob('*/*/requests/*.json'))
    report=dict(schema='synthetic_suite_completion_segment_v1',created_utc=now(),source_run=source.name,
        synthetic_only=True,formal_questions_used=0,gold_used=False,model_requests=len(requests),expected_model_requests=expected,
        passed_requested_cases=all(all(c['passed'] for c in r['cases']) and len(r['cases'])==len(missing[r['deployment']['logical_model']]) for r in reports),
        complete=len(requests)==expected,query_limit=512,output_tokens=2048,automatic_retries=0,
        formal_generation_started=False,acceptance_started=False,ai_judge_calls=0,implementation=bindings,
        files={p.relative_to(root).as_posix():sha(p.read_bytes()) for p in root.rglob('*') if p.is_file()})
    (root/'summary.json').write_bytes(encoded(report));print(json.dumps({k:v for k,v in report.items() if k not in {'files','implementation'}}),flush=True)

if __name__=='__main__':main()
