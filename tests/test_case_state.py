import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'.dsh/skills/blastfoam-knowledge/scripts'))
from case_state import viscosity_state
import pytest


def write_case(tmp_path,text):
    folder=tmp_path/'constant';folder.mkdir(exist_ok=True)
    (folder/'phaseProperties').write_text(text)
    return tmp_path


def test_reloads_actual_case_and_includes_both_detonating_components(tmp_path):
    part='thermoType { transport const; } transport { mu 0; }'
    text='phases (charge air); charge { type detonating; reactants {'+part+'} products {'+part+'}} air {type basic;'+part+'}'
    root=write_case(tmp_path,text)
    before=viscosity_state(root)
    assert before['state']=='all_const_zero' and len(before['observations'])==3
    write_case(tmp_path,text.replace('mu 0','mu 1.8e-5',1))
    after=viscosity_state(root)
    assert after['state']=='positive_const_input' and after['sha256']!=before['sha256']
    assert after['runtime_branch']=='not_evaluated'


@pytest.mark.parametrize('body',[
    'type basic; thermoType {transport sutherland;} transport {mu 0;}',
    'type basic; thermoType {transport const;} transport {mu $reference;}',
    'type basic; thermoType {transport const;} transport {mu 0; mu 1;}',
    'type basic; thermoType {transport const;} transport {mu nan;}',
    'type unknown; thermoType {transport const;} transport {mu 0;}',
    'type detonating; reactants {thermoType {transport const;} transport {mu 0;}}',
    'type basic; thermoType {transport const;} #include "other"\n transport {mu 0;}',
])
def test_incomplete_or_dynamic_state_cannot_be_declared_zero(tmp_path,body):
    state=viscosity_state(write_case(tmp_path,'phases (air); air {'+body+'}'))
    assert state['state']=='unknown' and state['reasons']


def test_proposal_is_separate_from_source_and_recomputes_relevant_inputs(tmp_path):
    root=write_case(tmp_path,'phases (air); air {type basic; thermoType {transport const;} transport {mu 0;} }')
    source=(root/'constant/phaseProperties').read_bytes()
    thermo=[{'path':'constant/phaseProperties','entry':'air/thermoType/thermo','value':'hConst'}]
    assert viscosity_state(root,thermo)['state']=='all_const_zero'
    changed=thermo+[{'path':'constant/phaseProperties','entry':'air/transport/mu','value':'1e-5'}]
    state=viscosity_state(root,changed)
    assert state['state']=='positive_const_input' and 'hypothetical' in state['state_scope']
    changed.append({'path':'constant/phaseProperties','entry':'air/thermoType/transport','value':'sutherland'})
    assert viscosity_state(root,changed)['state']=='unknown'
    assert (root/'constant/phaseProperties').read_bytes()==source
    assert viscosity_state(root)['state']=='all_const_zero'
