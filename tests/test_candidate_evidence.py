import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from candidate_evidence import Engine,scopes,wire


def test_ambiguous_case_name_keeps_solver_branches():
    cases=['tutorials/blastFoam/building3D','tutorials/blastFSIFoam/building3D']
    assert scopes('building3D',cases)['cases']==cases
    assert scopes('blastFoam building3D',cases)['cases']==cases[:1]


def test_budget_omits_whole_group_instead_of_partial_evidence():
    engine=object.__new__(Engine)
    engine.files={'manual.md':['x'*2000,'short supported line']}
    engine.cases=[];engine.graph=None
    hits=[{'id':'large','path':'manual.md','start':1,'end':1,'text':'x'*2000,'score':1},
          {'id':'short','path':'manual.md','start':2,'end':2,'text':'short supported line','score':.5}]
    engine.retriever=SimpleNamespace(manifest={'corpus_id':'fixture'},query=lambda *a,**kw:(hits,{}))
    result,cost=engine.query('fixture',cap=1000)
    assert len(wire(result))<=1000
    assert [g['id'] for g in result['groups']]==['passage:short']
    assert result['gaps']['deferred_groups']==1
    assert next(iter(result['evidence'].values()))['text']=='2: short supported line'
    assert not cost['graph_loaded']


def test_path_evidence_does_not_mutate_shared_graph_between_questions():
    from candidate_graph import Paths
    from collections import defaultdict
    engine=object.__new__(Engine);engine.files={'manual.md':['model A','condition','model B']};engine.cases=[]
    def anchor(n):return {'path':'manual.md','start':n,'end':n}
    nodes={key:{'id':key,'kind':'domain_definition','path':'manual.md','label':key,'scope':{},'evidence':[anchor(n)]}
           for key,n in [('a',1),('b',3)]}
    edge={'id':'ab','source':'a','target':'b','relation':'REQUIRES_WHEN','status':'source_supported_declaration',
          'evidence':[anchor(2)],'conditions':['when enabled']}
    engine.graph={'nodes':nodes,'edges':[edge]};engine.nodes=nodes;engine.edges={'ab':edge}
    engine.paths=Paths(engine.graph);engine.by_file={'manual.md':['a','b']};engine.adjacency=defaultdict(list,{'a':[edge]})
    hits=[{'id':'a-passage','path':'manual.md','start':1,'end':1,'text':'model A','score':1}]
    engine.retriever=SimpleNamespace(manifest={'corpus_id':'fixture'},query=lambda *a,**kw:(hits,{}))
    before=wire(engine.graph);first,_=engine.query('model A');second,_=engine.query('model A')
    assert wire(engine.graph)==before
    assert first==second
    assert nodes['b']['evidence']==[anchor(3)]


def test_gap_ablation_removes_gap_state_from_tool_result():
    engine=object.__new__(Engine);engine.files={'manual.md':['supported line']};engine.cases=[];engine.graph=None
    hits=[{'id':'p','path':'manual.md','start':1,'end':1,'text':'supported line','score':1}]
    engine.retriever=SimpleNamespace(manifest={'corpus_id':'fixture'},query=lambda *a,**kw:(hits,{}))
    result,audit=engine.query('fixture',with_gap=False,slots=['must not leak'])
    assert 'gaps' not in result
    assert not audit['with_gap']
