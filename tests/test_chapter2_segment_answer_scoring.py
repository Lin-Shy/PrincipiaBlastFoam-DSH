import copy
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_segment_answer_scoring import segments,segment_payload,parse_segment_judgment
from chapter2_answer_scoring import JUDGE_MODEL

def sample():
    payload={'question':'Compare','answer':'fieldValue 高。delta 为零。','rubric':{'condition_discrimination':True,
      'required_points':[{'id':'Q.K1','weight':1},{'id':'Q.K2','weight':1}],'critical_errors':[{'id':'C1'}]},'original_material':{'source':{}}}
    value={'points':[{'id':'K1','verdict':'satisfied','support_segment_ids':['A1'],'evidence_ids':['source'],'reason':'amplitude'},
      {'id':'K2','verdict':'satisfied','support_segment_ids':['A2'],'evidence_ids':['source'],'reason':'equal neighbors'}],
      'critical_errors':[],'additional_claims':[],'factuality':{'verdict':'pass','reason':'source matches'},
      'applicability':{'verdict':'pass','reason':'given condition'}}
    def response(v):return {'status':'response','response':{'model':JUDGE_MODEL,'usage':{'completion_tokens':200},
      'choices':[{'finish_reason':'stop','message':{'content':json.dumps(v)}}]}}
    return payload,value,response

def test_segment_ids_restore_actual_answer_not_reference_paraphrases():
    p,v,r=sample();score=parse_segment_judgment(r(v),p)
    assert score['status']=='judged' and score['metrics']['complete_valid_answer']==1
    assert score['judgment']['points'][0]['id']=='Q.K1'
    assert score['judgment']['points'][0]['answer_quote']=='fieldValue 高。'
    assert score['actual_answer_support_segments']['Q.K2'][0]['text']=='delta 为零。'
    assert list(segment_payload(p)[0])[-1]=='candidate_answer'

def test_invented_or_missing_candidate_segments_cannot_support_a_point():
    p,v,r=sample();v['points'][1]['support_segment_ids']=['A99']
    assert parse_segment_judgment(r(v),p)['status']=='judge_unknown'
    v['points'][1]['support_segment_ids']=[]
    assert parse_segment_judgment(r(v),p)['status']=='judge_unknown'

def test_offsets_preserve_formulae_spaces_and_linebreaks_verbatim():
    answer='  e = C_v(T - T_ref)。\n\n仅当 enabled 才适用！'
    rows=segments(answer)
    assert all(answer[r['start']:r['end']]==r['text'] for r in rows)
    assert rows[0]['text']=='  e = C_v(T - T_ref)。'
