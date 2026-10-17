from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from test_knowledge_agent import make_tools
from chapter2_full_generation import execute, ANSWER_CHECKLIST
from chapter2_v2_retrieval_probe import save, read, sha
from chapter2_full_protocol import verify_result
from principia_core.retrieval.knowledge_agent import ModelBudget, SYSTEM


def test_full_generation_actual_agent_delivery_binding_and_resume_without_paid_replay(tmp_path,monkeypatch):
    import chapter2_autonomous_qa as qa
    import chapter2_qwen_routing as routing
    import chapter2_knowledge_input_guard as guard
    tools=make_tools(tmp_path)
    questions=tmp_path/'questions.json';save(questions,[dict(id='Q',question='pressure condition?')])
    source_map=tmp_path/'source-map.json';save(source_map,dict(files=tools.corpus.hashes))
    dummy=tmp_path/'metadata.json';save(dummy,{})
    resources=dict(questions=str(questions),corpus=str(tmp_path),corpus_manifest=str(tools.corpus.manifest_path),source_map=str(source_map))
    for name in ('e5_manifest','graph_full','graph_no_cross','graph_no_conditions','graph_no_extension'):resources[name]=str(dummy)
    for model in ('qwen3-8b','qwen3-14b'):
        folder=tmp_path/model;save(folder/'artifact-binding.json',{})
        resources['tokenizer_'+model]=str(folder)
    resource_file=tmp_path/'resources.json';save(resource_file,resources)
    cells=[dict(id=f'main/{m}_{method}/r01',kind='main',model=m,method=method,graph_ablation='full' if method=='graph' else None,
        repeat=1,question_ids=['Q'],tool_calls=8,knowledge_characters=24000) for m in ('qwen3-8b','qwen3-14b') for method in ('graph','none')]
    plan=dict(cells=cells,test_ids=['Q'],model_budget=asdict(ModelBudget(output_tokens_per_request=4096,final_output_reserve=4096,output_tokens_total=32768)),
        artifacts_sha256={k:sha(Path(v)/'artifact-binding.json') if k.startswith('tokenizer_') else sha(Path(v)) for k,v in resources.items() if k!='corpus'},
        runtime_source_sha256={},common_answer_checklist=ANSWER_CHECKLIST,system_prompt_sha256=hashlib.sha256(SYSTEM.encode()).hexdigest(),knowledge_per_result_characters=6000)
    plan_path=tmp_path/'plan.json';save(plan_path,plan)
    monkeypatch.setattr(guard,'install',lambda path:dict(test_guard=True))
    monkeypatch.setattr(qa,'load_tokenizer',lambda folder,model:(lambda messages:100,dict(model=model)))
    calls=[]
    def client(model,folder,**kwargs):
        class Client:
            deployment=SimpleNamespace(model=model)
            def __call__(self,body,turn):
                calls.append((str(folder),turn))
                retrieve='graph' in str(folder) and turn==0
                action=dict(action='tool',name='search',arguments=dict(query='pressure')) if retrieve else dict(action='final',answer='pressure threshold; condition applies',references=[])
                return dict(status='response',raw_response=dict(model=model,usage=dict(completion_tokens=10),choices=[dict(finish_reason='stop',message=dict(content=json.dumps(action)))]))
        return Client()
    monkeypatch.setattr(routing,'routed_client',client)
    class Server:
        receipt=dict(graph_process=True,baseline_dependencies_loaded=[])
        def search(self,query,limit):
            return dict(rows=[dict(path='manual/rule.md',start=1,end=2)],event=dict(query=query,native_packet=dict(items=[]),stats={}))
    args=SimpleNamespace(plan=plan_path,resources=resource_file,output=tmp_path/'results',receipt=tmp_path/'attempt1',
        diagnostic=False,prepare_only=False,continue_unattempted=False,proxy_settings=tmp_path/'unused.env',timeout=10)
    execute(args,plan,resources,{'graph':Server()})
    assert len(calls)==6
    for cell in cells:
        result=verify_result(args.output/cell['id']/'sessions/Q/result.json',dict(id='Q',question='pressure condition?'),cell['id'],sha(args.output/'protocol.json'))
        assert result['status']=='answered'
        assert len(result['tool_events'])==(1 if cell['method']=='graph' else 0)
        assert len(result['native_ranking_events'])==(1 if cell['method']=='graph' else 0)
    args.receipt=tmp_path/'attempt2';args.continue_unattempted=True
    execute(args,plan,resources,{'graph':Server()})
    assert len(calls)==6 and read(args.receipt/'completion.json')['completed']==4
