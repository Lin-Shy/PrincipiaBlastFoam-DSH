import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from experiments.retrieval_method.native_combination_server import proposed_components,attach


@pytest.fixture
def case(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'.dsh/skills/blastfoam-knowledge/scripts'))
    relative='tutorials/demo/constant/phaseProperties';file=tmp_path/'corpus'/relative
    file.parent.mkdir(parents=True);file.write_text('phases (fuel ambient); fuel { type basic; thermoType { transport const; thermo eConst; equationOfState idealGas; } thermodynamics { type eConst; Cv 718; Hf 0; } } ambient { type basic; }')
    engine=SimpleNamespace(skill=tmp_path,graph={'inventory':{relative:hashlib.sha256(file.read_bytes()).hexdigest()}})
    packet={'case':'tutorials/demo','case_identity':{'phases':['fuel','ambient'],'factory_route':'factory_route/guide'},
            'model_draft':{'edits':[{'path':'constant/phaseProperties','entry':'fuel/thermoType/thermo','value':'hConst'},
                                    {'path':'constant/phaseProperties','entry':'fuel/thermodynamics/Cv','value':None}]}}
    return engine,packet,file


def test_specific_tuple_uses_proposal_and_actual_selector_not_redundant_type(case):
    engine,packet,file=case;saved=file.read_bytes()
    result=proposed_components(engine,packet)
    assert result['phase']=='fuel'
    assert result['components']=={'base':'phaseFluid','type':'basic','specie':'specie','transport':'const','thermo':'hConst','equationOfState':'idealGas'}
    assert file.read_bytes()==saved


def test_ambiguous_selector_missing_route_and_changed_state_do_not_bind(case):
    engine,packet,file=case
    multiple=copy.deepcopy(packet);multiple['model_draft']['edits'].append({'path':'constant/phaseProperties','entry':'ambient/thermoType/thermo','value':'hConst'})
    assert proposed_components(engine,multiple) is None
    no_route=copy.deepcopy(packet);no_route['case_identity'].pop('factory_route')
    assert proposed_components(engine,no_route) is None
    file.write_text(file.read_text().replace('idealGas','stiffenedGas'))
    with pytest.raises(ValueError,match='changed'):proposed_components(engine,packet)


def test_budget_keeps_operations_and_condition_state_as_one_bundle(case):
    _,packet,_=case
    packet.update(locations=[{'text':'source'*300,'complete':True}],conditional_drafts=[{'id':'dependency','condition_evaluation':'unknown','preparation_edits':[]}])
    graph=SimpleNamespace(summary=lambda _: {'registration':'source_declaration_verified','scope':'source only'})
    binding={'components':{'thermo':'hConst'}}
    result=attach(packet,binding,graph,1000)
    assert result['model_draft']==packet['model_draft']
    assert result['conditional_drafts']==packet['conditional_drafts']
    assert result['case_identity']==packet['case_identity']
    assert result['model_combination']['components']==binding['components']
    assert not result['locations'][0]['complete']
    assert len(json.dumps(result,ensure_ascii=False,separators=(',',':')))<=1000
