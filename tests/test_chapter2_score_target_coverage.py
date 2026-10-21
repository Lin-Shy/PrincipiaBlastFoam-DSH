import importlib.util
import json
from pathlib import Path
import sys
import pytest

MODULES=Path(__file__).resolve().parents[1]/'experiments/retrieval_method'
sys.path.insert(0,str(MODULES))
spec=importlib.util.spec_from_file_location('target_coverage',MODULES/'chapter2_score_target_coverage.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)

def fixture():
    body={'messages':[{'content':'prompt'},{'content':json.dumps({'rows':[{'id':'q','required_points':[{'id':'q.K1'}]}],
      'sources':{'s':{'excerpt':'exact source quote'}}})}]}
    value={'reviews':[{'id':'q','targets':[{'target':'default behavior','covered_by_points':[],
      'source_sufficient_for_target':True,'missing_required_point':True,'reason':'point only lists the name'}],
      'proposed_additions':[{'claim':'default behavior','evidence_ids':['s'],'quotes':{'s':'source quote'}}],
      'action_required':True}]}
    return value,body

def test_missing_target_is_distinct_from_supported_existing_point():
    value,body=fixture();assert audit.parse(value,body)['reviews'][0]['action_required']

def test_false_action_flag_cannot_hide_target_coverage_gap():
    value,body=fixture();value['reviews'][0]['action_required']=False
    with pytest.raises(AssertionError):audit.parse(value,body)

def test_proposed_gold_cannot_invent_source_quotes_or_point_ids():
    value,body=fixture();value['reviews'][0]['proposed_additions'][0]['quotes']['s']='invented text'
    with pytest.raises(AssertionError,match='quote'):audit.parse(value,body)
    value,body=fixture();value['reviews'][0]['targets'][0]['covered_by_points']=['q.K99']
    with pytest.raises(AssertionError):audit.parse(value,body)
