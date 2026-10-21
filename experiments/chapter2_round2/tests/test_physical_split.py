from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
from common import *
from materialize_split import DATA_DIRS
from split_existing200 import SPLIT,OUT
from unify_current import SOURCES

@pytest.mark.parametrize('part,n',[('development',160),('test',40)])
def test_physical_questions_and_annotations_are_exact_original_objects(part,n):
    target=DATA_DIRS[part];ids=set(read(SPLIT)[part]['ids']);oldq={q['id']:q for q in public_questions()};olda={a['id']:a for a in read(DATASET/'scoring/annotations.json')};olde=read(DATASET/'scoring/evidence.json')
    qs=read(target/'model/questions.json');a=read(target/'scoring/annotations.json');ev=read(target/'scoring/evidence.json')
    assert len(qs)==len(a)==n and {q['id']for q in qs}==ids
    assert all(set(q)=={'id','question'}and q==oldq[q['id']]for q in qs)
    assert all(r==olda[r['id']]for r in a)
    assert set(ev)=={e for r in a for e in r['required_evidence_ids']}and all(v==olde[k]for k,v in ev.items())

@pytest.mark.parametrize('model',['8b','14b','round2_14b'])
@pytest.mark.parametrize('part,n',[('development',160),('test',40)])
def test_raw_records_are_physically_separate_and_hash_identical(model,part,n):
    original=OUT/model/part;manifest=read(original/'physical-records.json');ids=set(read(SPLIT)[part]['ids'])
    actual_model,run=SOURCES[model];root=CURRENT/actual_model/part
    current=read(CURRENT/'physical-records.json')
    files={k:v for k,v in current['files'].items()if v['model']==actual_model and v['run']==run and v['role']==part}
    arms=list(read(original/'summary.json')['by_arm'])
    assert manifest['questions']==n and manifest['sessions']==n*len(arms)
    assert len(files)==manifest['copied_files']
    for kind in ['generation','scoring']:
        for arm in arms:
            assert {p.name for p in (root/kind/arm/run).iterdir()if p.is_dir()}==ids
    for relative,entry in files.items():
        local=CURRENT/relative;source=WORKSPACE/entry['source']
        assert local.is_relative_to(root)and local.is_file()and not local.is_symlink()
        assert sha(local)==entry['sha256']==sha(source)
        assert not(WORKSPACE/entry['previous_copy']).exists()

def test_actual_guard_reads_only_selected_public_file_in_physical_layout():
    import subprocess
    code="""import sys
sys.path.insert(0,'PrincipiaBlastFoam-DSH/experiments/chapter2_round2')
from common import read
from materialize_split import DATA_DIRS
from chapter2_knowledge_input_guard import install
install(DATA_DIRS['test']/'model/questions.json')
assert len(read(DATA_DIRS['test']/'model/questions.json'))==40
for p in [DATA_DIRS['test']/'scoring/annotations.json',DATA_DIRS['development']/'model/questions.json']:
 try:read(p)
 except PermissionError:pass
 else:raise AssertionError('physical split input isolation failed')
"""
    result=subprocess.run([sys.executable,'-X','utf8','-c',code],cwd=WORKSPACE,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
