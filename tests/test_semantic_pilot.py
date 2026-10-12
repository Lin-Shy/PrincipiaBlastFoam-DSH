import copy
import importlib.util
import json
from pathlib import Path

import pytest

SKILL=Path(__file__).resolve().parents[1]/'.dsh/skills/blastfoam-knowledge'
if not (SKILL/'scripts/validate_semantic.py').exists():
    pytest.skip('用户已移除旧分页语义试验；新章节图由 test_manual_graph.py 验证', allow_module_level=True)
spec=importlib.util.spec_from_file_location('semantic_validator',SKILL/'scripts/validate_semantic.py')
v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)


@pytest.fixture
def data():
    corpus=SKILL/'corpus'
    return (json.loads((SKILL/'semantic/format.json').read_text()),corpus,
            {p['pdf_page']:p for p in map(json.loads,(corpus/'manual/pages.jsonl').read_text().splitlines())},
            v.sha(corpus/'manual/source.pdf'),
            [json.loads(x) for x in (SKILL/'semantic/pilot/facts.jsonl').read_text().splitlines()])


def test_pilot_sources_and_quarantine():
    result=v.validate(SKILL)
    assert result['facts']==19 and result['deferred_items']==2


@pytest.mark.parametrize('mutation', ['wrong_units','wrong_page_region','wrong_anchor','unconditional_default','publish','false_review'])
def test_rejects_unreliable_fact_metadata(data,mutation):
    contract,corpus,pages,pdf_hash,facts=data
    selected=next(f for f in facts if f['kind']=='documented_default') if mutation=='unconditional_default' else facts[0]
    fact=copy.deepcopy(selected)
    if mutation=='wrong_units':
        fact['object']['dimensions']=[0]*7
    elif mutation=='wrong_page_region':
        fact['evidence'][0]['region_id']='p056-r001'
    elif mutation=='wrong_anchor':
        fact['evidence'][0]['anchor']='invented supporting sentence'
    elif mutation=='unconditional_default':
        fact['conditions']={'op':'always'}
    elif mutation=='publish':
        fact['publication']='published';fact['executable']=True
    else:
        fact['review']['independent_review']=True
    with pytest.raises(ValueError):
        v.check_fact(fact,contract,corpus,pages,pdf_hash)


def test_unknown_conditions_and_boolean_combinations():
    eq=lambda field,value:{'op':'eq','field':field,'value':value}
    both={'op':'all','args':[eq('model','chosen'),eq('mesh_changed',True)]}
    either={'op':'any','args':[eq('pressure',True),eq('impulse',True)]}
    assert v.evaluate_condition(both,{'model':'chosen'}) is None
    assert v.evaluate_condition(both,{'model':'different'}) is False
    assert v.evaluate_condition(both,{'model':'chosen','mesh_changed':True}) is True
    assert v.evaluate_condition(either,{'pressure':True}) is True
    assert v.evaluate_condition(either,{'pressure':False}) is None
    assert v.evaluate_condition(either,{'pressure':False,'impulse':False}) is False
    assert v.evaluate_condition(eq('mesh_changed',False),{'mesh_changed':0}) is None


def test_required_resource_is_distinct_from_recommended_method(data):
    facts={f['id']:f for f in data[-1]}
    required=facts['manual6:impulse-field-required']
    recommended=facts['manual6:impulse-function-recommended']
    assert required['modality']=='required'
    assert recommended['modality']=='recommended' and recommended['object']['alternatives_allowed']
    bad=copy.deepcopy(recommended);bad['modality']='required'
    with pytest.raises(ValueError):
        v.check_fact(bad,*data[:4])
