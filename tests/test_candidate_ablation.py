import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from candidate_ablation import transform_graph, verify_transform, options_for


def fixture():
    a=lambda n:[{'path':'p','start':n,'end':n}]
    return {'nodes':{
        'config':{'id':'config','kind':'configuration','path':'p','label':'model A','key':'type','value':'A',
                  'role':'selector','scope':{'case_directory':'case'},'components':['block','type'],
                  'parent':'dictionary','evidence':a(1)},
        'dictionary':{'id':'dictionary','kind':'dictionary','path':'p','label':'block','scope':{},'evidence':a(1)},
        'definition':{'id':'definition','kind':'domain_definition','path':'m','label':'A / transport',
                      'name':'A','role':'transport','selector_keys':['type'],'parent_keys':['block'],'scope':{},'evidence':a(2)},
        'assertion':{'id':'assertion','kind':'conditional_assertion','path':'m','label':'A REQUIRES_WHEN x',
                     'subject':'A','predicate':'REQUIRES_WHEN','object':'x','subject_role':'transport','scope':{},'evidence':a(3)},
    },'edges':[
        {'id':'parent','source':'dictionary','target':'config','relation':'HAS_ENTRY','status':'physical_structure','conditions':[],'evidence':a(1)},
        {'id':'pair','source':'config','target':'definition','relation':'DOCUMENTED_BY','role':'transport','scope':{},
         'status':'literal_role_matched_alignment_not_runtime_activation','conditions':[],
         'instance_evidence':a(1),'definition_evidence':a(2),'evidence':a(1)+a(2)},
        {'id':'owner','source':'definition','target':'assertion','relation':'REQUIRES_WHEN','status':'source_supported_declaration',
         'conditions':[],'evidence':a(3)},
    ],'candidates':[],'issues':[]}


def test_role_scope_ablation_replaces_role_alignment_with_bare_name_and_erases_metadata():
    graph=transform_graph(fixture(),['role_scope']);verify_transform(graph,['role_scope'])
    pair=next(e for e in graph['edges'] if e['relation']=='DOCUMENTED_BY')
    assert pair['status']=='ablation_bare_name_alignment'
    assert graph['nodes']['definition']['label']=='A'
    assert 'scope' not in graph['nodes']['config'] and 'components' not in graph['nodes']['config']


def test_bilateral_paths_and_group_ablation_physically_remove_information():
    for factors in [['conditional_bilateral'],['paths'],['evidence_groups'],['paths','evidence_groups']]:
        graph=transform_graph(fixture(),factors);verify_transform(graph,factors)
    assert not transform_graph(fixture(),['paths'])['edges']
    group=transform_graph(fixture(),['evidence_groups'])
    pair=next(e for e in group['edges'] if e['relation']=='DOCUMENTED_BY')
    assert pair['evidence']==[] and 'instance_evidence' not in pair and 'definition_evidence' not in pair


def test_each_registered_option_only_turns_off_its_factor():
    assert options_for(['semantic_recall'])['semantic'] is False
    assert options_for(['semantic_recall'])['with_paths'] is True
    assert options_for(['claim_verification'])['with_claim_verification'] is False
