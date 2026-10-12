from types import SimpleNamespace
from experiments.retrieval_method.native_draft_server import explicit_inputs
from experiments.retrieval_method.native_draft_server import projected_requirement_sources


def test_explicit_scalar_assignments_allow_adjacent_chinese_but_not_conflicts():
    search=SimpleNamespace(search=SimpleNamespace(nodes={'i':{'kind':'input_schema','entries':[{'entry':'transport/As'},{'entry':'transport/Ts'}]}}))
    packet={'locations':[{'id':'i'}]}
    assert explicit_inputs(search,packet,'使用As=1.458e-6、Ts=110.4的关系')=={'As':'1.458e-6','Ts':'110.4'}
    assert explicit_inputs(search,packet,'As=1e-6 As=0.000001 Ts=1 Ts=2')=={'As':'1e-6'}
    assert explicit_inputs(search,packet,'otherAs=1 As=1eBAD Ts=NaN')=={}
    assert explicit_inputs(search,packet,'As设置为1.2e-6，Ts设为120；保留其他对象As=2和Ts=3')=={'As':'1.2e-6','Ts':'120'}
    assert explicit_inputs(search,packet,'As为1.2e-6，Ts to 120')=={'As':'1.2e-6','Ts':'120'}


def test_exclusive_solver_replacement_sources_omitted_only_when_preserved():
    c={'requirements':[{'target':'schemes','support':['S1']},{'target':'solution','support':['S1','S2']},
                       {'target':'heat','support':['S3']}], 'code_sources':[{'id':x} for x in ['S1','S2','S3']]}
    d={'edits':[{'path':'schemes'}],'target_states':[{'path':'solution','state':'present_preserved'}]}
    assert [x['id'] for x in projected_requirement_sources(c,d)]==['S1','S3']
    d['target_states'][0]['state']='unresolved'
    assert projected_requirement_sources(c,d)==c['code_sources']
    d['target_states'][0]['state']='present_preserved';d['edits'].append({'path':'solution'})
    assert projected_requirement_sources(c,d)==c['code_sources']
