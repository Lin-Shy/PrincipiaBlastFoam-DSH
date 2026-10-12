import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from candidate_graph import include_target,scoped_roles_match,Paths


def test_same_name_does_not_establish_role_alignment():
    instance={'key':'thermodynamics','components':['mixture','thermodynamics']}
    assert not scoped_roles_match(instance,{'selector_keys':['equationOfState'],'parent_keys':[]})
    assert scoped_roles_match(instance,{'selector_keys':['thermodynamics'],'parent_keys':['mixture']})
    assert not scoped_roles_match(instance,{'selector_keys':[],'parent_keys':[]})


def test_includes_are_confined_literal_and_not_environment_expanded():
    assert include_target('case/system/controlDict','"shared"',{'case/system/shared':b'x'})==('case/system/shared',None)
    assert include_target('case/controlDict','"../../secret"',{})[1]=='outside_corpus_include'
    assert include_target('case/controlDict','"$FOAM_ETC/a"',{})[1]=='dynamic_or_non_literal_include'


def test_path_search_cannot_cross_case_or_reverse_requirement():
    nodes={x:{'scope':{'case_directory':scope}} for x,scope in [('a','case-a'),('b','case-b'),('m',None),('r',None)]}
    def edge(a,b,kind,i,**extra):return dict(source=a,target=b,relation=kind,id=i,**extra)
    graph={'nodes':nodes,'edges':[edge('a','b','HAS_BLOCK','ab'),
       edge('a','m','DOCUMENTED_BY','am',instance_evidence=[1],definition_evidence=[2]),edge('m','r','REQUIRES_WHEN','mr')]}
    paths=Paths(graph)
    found,_=paths.search([('a',1)],case_scopes=['case-a'])
    assert 'b' not in {p['node'] for p in found}
    assert 'r' in {p['node'] for p in found}
    without,_=paths.search([('a',1)],case_scopes=['case-a'],with_cross=False)
    assert 'm' not in {p['node'] for p in without}
    backwards,_=paths.search([('r',1)])
    assert {p['node'] for p in backwards}=={'r'}


def test_unknown_conditions_are_declarations_not_satisfied_requirements():
    graph={'nodes':{'a':{'scope':{}},'b':{'scope':{}}},'edges':[
        {'id':'ab','source':'a','target':'b','relation':'REQUIRES_WHEN',
         'conditions':['only when enabled'],'condition_satisfied':None}]}
    paths=Paths(graph)
    declared,_=paths.search([('a',1)])
    satisfied,_=paths.search([('a',1)],condition_mode='satisfied_only')
    assert {p['node'] for p in declared}=={'a','b'}
    assert {p['node'] for p in satisfied}=={'a'}


def test_explicit_assertion_role_cannot_fall_back_to_same_name():
    from candidate_graph import assertion_owners
    definitions=[{'name':'eTabulated','role':'enthalpy_input'}]
    assert not assertion_owners({'subject':'eTabulated','subject_role':'internal_energy_input'},definitions)
    assert assertion_owners({'subject':'eTabulated','subject_role':'enthalpy_input'},definitions)==definitions
