from pathlib import Path
import subprocess
import sys

def test_guard_rejects_score_authoring_split_and_other_dataset_inputs(tmp_path):
    modules=Path(__file__).resolve().parents[1]/'experiments/retrieval_method'
    paths=[tmp_path/'scoring/annotations.json',tmp_path/'authoring/catalog.json',tmp_path/'split.json',
       tmp_path/'graduation-datasets/qa/model/other.json']
    allowed=tmp_path/'graduation-datasets/qa/model/questions.json'
    for path in paths+[allowed]:path.parent.mkdir(parents=True,exist_ok=True);path.write_text('[]')
    program=f'''import sys
from pathlib import Path
sys.path.insert(0,{str(modules)!r})
from chapter2_knowledge_input_guard import install
install({str(allowed)!r})
assert Path({str(allowed)!r}).read_text()=='[]'
for name in {[str(p) for p in paths]!r}:
 try:Path(name).read_text()
 except PermissionError:pass
 else:raise AssertionError('forbidden input was read')
print('guard passed')
'''
    result=subprocess.run([sys.executable,'-c',program],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
