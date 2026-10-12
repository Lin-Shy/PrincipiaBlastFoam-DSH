from experiments.retrieval_method.removal_intent import requested_removals
from test_model_edit_draft import fixture
from experiments.retrieval_method.model_edit_draft import draft_model_edits

def resolve(text):
 return requested_removals(text,'gas/transport',['mu','Pr'],{'mu':['固定黏度']})

def test_explicit_keys_alias_negation_and_other_phase_preservation():
 assert resolve('删除该气体原有固定黏度和Pr参数，另一种气体的物性不变')['keys']==['Pr','mu']
 assert resolve('remove mu, Pr; preserve air phase Pr')['keys']==['Pr','mu']
 assert resolve('delete gas/transport/mu; keep Pr')['keys']==['mu']
 assert resolve('删除gas/transport/mu和gas/transport/Pr')['keys']==['Pr','mu']
 assert resolve('不要删除mu；保留Pr')['keys']==[]
 assert resolve('change transport to sutherland')['keys']==[]

def test_conflicting_unknown_and_other_targets_do_not_generate_deletions():
 for text in ['删除mu；保留mu','删除mu但保留Pr','删除另一相的mu','delete air/transport/mu','删除air的Pr','删除未知参数',
              'remove mu and unknownKey','删除mu和gas/transport/unknownKey']:
  result=resolve(text);assert result['status']!='resolved' and result['keys']==[]

def test_removals_need_existing_bound_fields_and_cannot_conflict_with_new_inputs():
 search,packet=fixture();search.nodes['c']['entries']=[{'entry':'solid/settings/old','value':'3'},{'entry':'solid/settings/A','value':'0'}]
 result=draft_model_edits(search,packet,{'A':'2','B':'4'},['old'])
 assert result['edits'][-1]=={'path':'constant/coefficients','entry':'solid/settings/old','value':None}
 assert draft_model_edits(search,packet,{'A':'2','B':'4'},['absent'])['status']=='unbound_removal'
 assert draft_model_edits(search,packet,{'A':'2','B':'4'},['A'])['status']=='conflicting_model_edits'

def test_set_values_before_removal_are_not_removal_objects():
 assert requested_removals('Hf=0，并移除旧Cv项。','gas/thermodynamics',['Hf','Cv'])['keys']==['Cv']
 assert requested_removals('Cp设置为1005、Hf设置为0，不再保留air的旧Cv项。','air/thermodynamics',['Cv','Hf'])['keys']==['Cv']
