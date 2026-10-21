import json
from pathlib import Path
import sys
import copy
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_graph_semantics import validate_extraction,validate_verification,accepted_semantics,curate_extraction

def sample():
    unit={'path':'manual/markdown/model.md','sha256':'fixed','start':10,'end':12,
          'text':'# Model\nCoefficient default is 0 if enabled.\nOutput is pressure.'}
    value={'definitions':[],'facts':[{'id':'F1','subject':'coefficient','subject_role':'Model input',
      'owner_model':'Model','predicate':'DEFAULT','object':'0','body':'Coefficient defaults to zero.',
      'aliases':['系数'],'conditions':['if enabled'],'evidence':[{'start':11,'end':11,'quote':'default is 0 if enabled'}]}],
      'relations':[],'unresolved':[]}
    body={'messages':[{'content':'prompt'},{'content':json.dumps({'source_unit':unit})}]}
    return value,body,unit

def test_fact_and_condition_have_independent_verification():
    value,body,unit=sample();candidate=validate_extraction(value,body)
    vb={'messages':[{'content':'prompt'},{'content':json.dumps({'source_unit':unit,'candidate':candidate})}]}
    verdict={'definitions':[],'facts':[{'id':'F1','supported':True,'condition_separation_supported':True,'reason':'direct source'}],'relations':[]}
    assert len(accepted_semantics(candidate,validate_verification(verdict,vb))['facts'])==1
    verdict['facts'][0]['condition_separation_supported']=False
    rejected=accepted_semantics(candidate,validate_verification(verdict,vb))
    assert rejected['facts']==[] and len(rejected['rejected'])==1

def test_quote_cannot_cross_source_unit_or_be_invented():
    value,body,unit=sample();value['facts'][0]['evidence'][0]['start']=9
    with pytest.raises(ValueError,match='one original'):validate_extraction(value,body)
    value,body,unit=sample();value['facts'][0]['evidence'][0]['quote']='wrong default'
    with pytest.raises(ValueError,match='quote'):validate_extraction(value,body)

def test_verifier_cannot_skip_or_invent_fact_identity():
    value,body,unit=sample();candidate=validate_extraction(value,body)
    vb={'messages':[{'content':'prompt'},{'content':json.dumps({'source_unit':unit,'candidate':candidate})}]}
    with pytest.raises(ValueError,match='incomplete'):validate_verification({'definitions':[],'facts':[],'relations':[]},vb)

def test_rejected_endpoint_cannot_support_an_accepted_relation():
    candidate={'definitions':[],'facts':[{'id':'F1'},{'id':'F2'}],
      'relations':[{'index':0,'source':'F1','target':'F2'}]}
    verdict={'definitions':[],'facts':[{'id':'F1','supported':True,'condition_separation_supported':True,'reason':'yes'},
      {'id':'F2','supported':False,'condition_separation_supported':True,'reason':'not in source'}],
      'relations':[{'index':0,'supported':True,'reason':'candidate relation'}]}
    assert accepted_semantics(candidate,verdict)['relations']==[]

def test_unique_exact_quote_relocation_preserves_text_and_other_valid_facts():
    value,body,unit=sample();value['facts'][0]['evidence'][0].update(start=10,end=10)
    bad=copy.deepcopy(value['facts'][0]);bad.update(id='F2');bad['evidence'][0]['quote']='default is 100 if enabled'
    value['facts'].append(bad)
    candidate=curate_extraction(value,body)
    assert len(candidate['facts'])==1 and candidate['facts'][0]['evidence'][0]['end']==11
    assert candidate['facts'][0]['evidence'][0]['quote']=='default is 0 if enabled'
    assert candidate['curation']['repairs'] and len(candidate['curation']['rejected'])==1
    assert not candidate['curation']['text_or_facts_rewritten']
