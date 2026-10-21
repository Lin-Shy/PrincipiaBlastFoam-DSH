import json
from pathlib import Path
import subprocess
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_complete_material_qa import run_diagnostic,validate_pack,sha
from principia_core.retrieval.knowledge_agent import ModelBudget
from test_knowledge_qa_tools import corpus

def test_complete_originals_are_not_truncated_and_only_actual_lines_citable(tmp_path):
    c,_,_=corpus(tmp_path,'x'*12000+'\nsecond line\n');m=c.read('manual/markdown/topic.md',1,2)
    q={'id':'Q1','question':'Explain source','original_material':[m]};seen=[]
    def client(body,turn):
        seen.append(body)
        return {'status':'response','response':{'model':'qwen3-14b','usage':{'completion_tokens':30},
          'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'action':'final','answer':'Explanation',
            'references':[{'path':m['path'],'start':1,'end':3}]})}}]}}
    r=run_diagnostic(q,'qwen3-14b',client,lambda _:100)
    assert r['status']=='answered' and r['privileged_input'] and not r['references_delivered']
    assert 'x'*12000 in seen[0]['messages'][1]['content'] and r['tool_calls']==0
    assert r['counted_input_tokens']==100 and 'required_points' not in str(seen)

def test_no_request_when_input_budget_exhausted_and_no_retry_on_bad_action(tmp_path):
    c,_,_=corpus(tmp_path);q={'id':'Q1','question':'Q','original_material':[c.read('manual/markdown/topic.md',1,1)]}
    def forbidden(*args):raise AssertionError('must not submit')
    assert run_diagnostic(q,'qwen3-8b',forbidden,lambda _:32769)['status']=='input_budget_exhausted'
    calls=[]
    def bad(body,turn):
        calls.append(body);return {'status':'response','response':{'model':'qwen3-8b','usage':{'completion_tokens':8},
         'choices':[{'finish_reason':'stop','message':{'content':'{"action":"tool","name":"search","arguments":{}}'}}]}}
    assert run_diagnostic(q,'qwen3-8b',bad,lambda _:20)['status']=='invalid_action' and len(calls)==1

def test_receipt_cannot_authorize_extra_fields_or_changed_originals(tmp_path):
    c,_,_=corpus(tmp_path);m=c.read('manual/markdown/topic.md',1,2)
    material=tmp_path/'materials.json';receipt=tmp_path/'receipt.json';q={'id':'Q1','question':'Q','original_material':[m]}
    material.write_text(json.dumps([q]),encoding='utf-8')
    confirmation={'status':'confirmed_for_separate_diagnostic','user_authorized_ai_confirmation':True,
      'normal_production_use_prohibited':True,'formal_result':False,'material_sha256':sha(material),
      'corpus_manifest_sha256':c.manifest_sha256,'checks':[{'id':'Q1','verdict':'sufficient_with_documented_scope',
        'change_required':False,'original_material':[{k:m[k] for k in ('path','sha256','start','end')}]}]}
    receipt.write_text(json.dumps(confirmation),encoding='utf-8')
    assert len(validate_pack(material,receipt,[{'id':'Q1','question':'Q'}],c)[0])==1
    q['answer_points']=['SECRET'];material.write_text(json.dumps([q]),encoding='utf-8')
    confirmation['material_sha256']=sha(material);receipt.write_text(json.dumps(confirmation),encoding='utf-8')
    with pytest.raises(ValueError,match='strict natural'):validate_pack(material,receipt,[{'id':'Q1','question':'Q'}],c)

def test_diagnostic_guard_allows_exact_pack_but_blocks_notes_and_gold(tmp_path):
    modules=Path(__file__).resolve().parents[1]/'experiments/retrieval_method'
    allowed=[tmp_path/'evaluation_only/materials.json',tmp_path/'evaluation_only/receipt.json',tmp_path/'graduation-datasets/model/questions.json']
    blocked=[tmp_path/'evaluation_only/REVIEW.md',tmp_path/'scoring/annotations.json',tmp_path/'evaluation_only/other.json']
    for p in allowed+blocked:p.parent.mkdir(parents=True,exist_ok=True);p.write_text('[]')
    program=f'''import sys
from pathlib import Path
sys.path.insert(0,{str(modules)!r})
from chapter2_complete_material_qa import install_diagnostic_guard
install_diagnostic_guard(*{[str(p) for p in allowed]!r})
for p in {[str(p) for p in allowed]!r}:assert Path(p).read_text()=='[]'
for p in {[str(p) for p in blocked]!r}:
 try:Path(p).read_text()
 except PermissionError:pass
 else:raise AssertionError('diagnostic read forbidden notes/gold')
'''
    result=subprocess.run([sys.executable,'-c',program],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
