"""Read-only verification of current inputs. Never opens inference services."""
from pathlib import Path
import hashlib,json,subprocess,sys
sys.dont_write_bytecode=True
WORK=Path(__file__).resolve().parents[3]
ROOT=WORK/'graduation-experiment-results/chapter2_retrieval'

def main():
    manifest=json.loads((ROOT/'release/manifests/current.json').read_text(encoding='utf-8'))
    assert manifest['status']=='current_inputs_not_frozen_experiment'
    for rel,expected in manifest['files'].items():
        assert hashlib.sha256((WORK/rel).read_bytes()).hexdigest()==expected,rel
    resources=ROOT/'data/resources'
    entries=json.loads((resources/'manifest.json').read_text(encoding='utf-8'))['files']
    for rel,expected in entries.items():
        assert hashlib.sha256((resources/rel).read_bytes()).hexdigest()==expected,rel
    subprocess.run([sys.executable,str(WORK/'graduation-datasets/chapter02_knowledge_qa/tools/rebuild.py')],check=True)
    matrix=json.loads((ROOT/'release/planning/matrix.json').read_text(encoding='utf-8'))
    assert matrix['tasks']==51300 and matrix['configurations']==171 and matrix['formal_generation_started'] is False
    from runner import verify_protocol,PROTOCOL,AUTHORIZATION
    from human_review import verify_plan,ROOT as REVIEW
    verify_protocol();verify_plan()
    prep=json.loads((ROOT/'release/validation/preparation.json').read_text('utf-8'))
    assert prep['passed'] and prep['protocol_sha256']==hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()
    assert prep['input_manifest_sha256']==hashlib.sha256((ROOT/'release/manifests/current.json').read_bytes()).hexdigest()
    for rel,h in prep['check_receipts'].items():assert hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()==h,rel
    assert json.loads(AUTHORIZATION.read_text('utf-8'))['formal_generation_authorized'] is False
    for phase in ('calibration','acceptance'):
        packets=json.loads((REVIEW/phase/'packets.json').read_text('utf-8'))
        assert all(p['answer'] is None and p['binding_status']=='awaiting_generation' for p in packets['samples'])
    assert not (ROOT/'runs').exists()
    print(json.dumps(dict(passed=True,current_input_files=len(manifest['files']),resource_files=len(entries),model_requests=0,formal_generation_started=False,human_labels=0)))

if __name__=='__main__':main()
