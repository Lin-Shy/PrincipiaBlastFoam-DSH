from experiments.retrieval_method.native_natural_server import hints


def test_concept_hints_do_not_choose_model_or_values():
    assert hints('空气黏度随温度变化')==['air','viscosity','temperature']
    assert hints('水的粘度')==['viscosity']
    assert hints('As=1e-6 Ts=110')==[]
    assert hints('不要改变空气黏度')==['air','viscosity']  # Retrieval only; no edit intent assertion.


def test_missing_input_packet_never_proposes_edits(monkeypatch):
    from types import SimpleNamespace
    from experiments.retrieval_method import native_draft_server as api
    packet={'status':'ok','case':'demo','locations':[]}
    search=SimpleNamespace(search=object(),locate=lambda *a,**k:packet)
    monkeypatch.setattr(api.knowledge_navigation,'navigator',lambda:search)
    monkeypatch.setattr(api,'explicit_inputs',lambda *a:{})
    monkeypatch.setattr(api,'draft_model_edits',lambda *a:{'status':'missing_inputs','missing_inputs':['A'],'edits':[]})
    result=api.locate_drafts('model','demo')
    assert result['status']=='located_missing_inputs'
    assert result['input_request']['keys']==['A']
    assert 'model_draft' not in result
