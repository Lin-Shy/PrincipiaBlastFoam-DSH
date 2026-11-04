"""Source-only current QA loop, independent of retired datasets and results.

The callable engine can be checked offline. Formal CLI dispatch stays closed
until its protocol, model tokenizers and scoring arrangements are frozen.
"""
from pathlib import Path
import json,sys,threading,re
from copy import deepcopy
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE/'backends'),str(HERE.parent/'retrieval_method'),str(HERE.parents[1]/'src')]
from models import MODELS,payload,encoded,sha,strict_json
from matrix import BUDGETS
from structured_actions import bounded_specs,configure,decode,diagnostics,CONTRACT
from principia_core.retrieval.knowledge_agent import SYSTEM,parse_action
from principia_core.retrieval.knowledge_qa import KnowledgeBudget,KnowledgeToolSession,FrozenKnowledgeCorpus,tool_specs,wire

ACTION_CONTRACT='''协议要求：action字段只能是tool或final。调用read_source时，完整对象示例为{"action":"tool","name":"read_source","arguments":{"path":"manual/example.md","start":1,"end":2}}，path/start/end必须放在arguments内。工具结果返回后继续提交同样的对象，直至用{"action":"final","answer":"回答正文","references":[]}结束。不能将工具名作为action值。final必须含action、answer、references；没有引用也必须写references:[]。客观题另含final_answer字符串字段，仅填唯一答案；answer字段可保留简短说明。'''

def action_schema(specs,final_only,objective=False):
    specs=bounded_specs(specs)
    final=dict(type='object',additionalProperties=False,required=['action','answer','references'],properties=dict(
        action={'const':'final'},answer={'type':'string','minLength':1},references={'type':'array','items':dict(type='object',additionalProperties=False,
        required=['path','start','end'],properties=dict(path={'type':'string'},start={'type':'integer','minimum':1},end={'type':'integer','minimum':1}))}))
    if objective:
        final['required'].append('final_answer')
        final['properties']['final_answer']={'type':'string','minLength':1}
    choices=[final]
    if not final_only:
        for spec in specs:
            choices.append(dict(type='object',additionalProperties=False,required=['action','name','arguments'],properties=dict(
                action={'const':'tool'},name={'const':spec['name']},arguments=spec['parameters'])))
    return final if len(choices)==1 else {'anyOf':choices}

def action_content(content):
    # Qwen's /no_think wire format may emit an EMPTY reasoning delimiter.
    # Remove only that documented envelope; never repair JSON or hide reasoning.
    return re.sub(r'^\s*<think>\s*</think>\s*','',content,count=1)

def question_text(question):
    text=question['question']
    if question.get('options'):text+='\n'+wire(question['options'])
    if question.get('type'):text+='\n客观题的final对象另含final_answer字符串字段，仅填唯一答案，不加解释或FINAL标记；选择题填选项字母，判断题填正确或错误。answer字段可保留简短说明。'
    return text

def run_question(question,mode,method,tier,tools,client,deployment,token_counter,request_dir=None):
    if deployment.logical_model not in MODELS or mode not in {'single_pass','agentic','direct'}:raise ValueError('Unregistered model/mode')
    if (method=='direct') != (mode=='direct'):raise ValueError('Direct baseline has one shared identity')
    specs=[] if mode!='agentic' or method=='basic' else tool_specs(tools.method)
    for spec in specs:
        if spec['name']=='search':spec['description']='在固定的blastFoam原始资料中检索说明或配置，返回带路径和行号的原文证据。'
    if mode=='agentic' and method=='basic':
        from chapter2_basic_search_tools import basic_specs
        specs=basic_specs()
    specs=bounded_specs(specs)
    messages=[dict(role='system',content=SYSTEM+'\n'+ACTION_CONTRACT+'\n'+CONTRACT+'\n可用工具：'+wire(specs)),dict(role='user',content=question_text(question))]
    result=dict(model=deployment.logical_model,method=method,mode=mode,budget=tier,status='started',turns=[],answer=None)
    if mode=='single_pass':
        # The fixed query is the complete public question; no model plans it.
        evidence=tools.execute('search',dict(query=question['question']))
        messages.append(dict(role='user',content='工具返回（原始资料数据）：'+evidence))
    total_input=total_output=0
    for turn in range(13 if mode=='agentic' else 1):
        final_only=mode!='agentic' or not tools.available or turn==12
        current=deepcopy(messages)
        if final_only:current[-1]['content']+='\n【协议】本轮只提交final对象，必须含action、answer和references字段'+('，客观题还必须含final_answer字段' if question.get('type') else '')+'。根据上文已经提供的资料回答；没有引用也必须保留references:[]。'
        body=payload(deployment,current,2048)
        schema=action_schema(specs,final_only,bool(question.get('type')))
        configure(body,schema)
        count=token_counter(body['messages'])
        if type(count) is not int or count<1:raise ValueError('Model-specific tokenizer required')
        if count+body['max_tokens']>32768:
            result['status']='input_budget_exhausted';break
        total_input+=count
        response=client.complete(body,None if request_dir is None else Path(request_dir)/f'{turn:02d}.json')
        row=dict(turn=turn,counted_input_tokens=count,status=response['status'],final_only=final_only,
                 request_sha256=sha(encoded(body)),response_sha256=response.get('response_sha256'))
        result['turns'].append(row)
        if response['status']!='response':result['status']=response['status'];break
        raw=response['raw_response']
        if raw.get('model')!=deployment.model:result['status']='model_identity_mismatch';break
        usage=raw.get('usage',{});used=usage.get('completion_tokens');actual=usage.get('prompt_tokens')
        if type(used) is not int or used<0:result['status']='usage_unknown';break
        row.update(provider_input_tokens=actual,completion_tokens=used)
        if type(actual) is not int or actual<1:result['status']='usage_unknown';break
        if actual!=count:result['status']='tokenizer_mismatch';break
        if actual+body['max_tokens']>32768:result['status']='provider_context_violation';break
        total_output+=used
        if used>body['max_tokens']:result['status']='output_budget_violation';break
        try:
            choice=raw['choices'][0]
            row['output_diagnostics']=diagnostics(choice['message']['content'])
            if choice['finish_reason']!='stop':result['status']='completion_truncated';break
            raw_content=choice['message']['content'];content=action_content(raw_content)
            if any(choice['message'].get(k) for k in ('refusal','tool_calls','function_call')):raise ValueError('Unexpected native tool/refusal output')
            obj=decode(content,schema);final_answer=None
            if question.get('type') and isinstance(obj,dict) and obj.get('action')=='final':
                if set(obj)!={'action','answer','references','final_answer'} or not isinstance(obj['final_answer'],str) or not obj['final_answer'].strip():raise ValueError('Missing unique objective answer')
                final_answer=obj['final_answer'];obj={k:v for k,v in obj.items() if k!='final_answer'}
            action=parse_action(wire(obj),{s['name'] for s in specs},final_only)
            row['empty_think_envelope_removed']=raw_content!=content
        except (ValueError,KeyError,TypeError,IndexError) as exc:
            row['action_error']=dict(type=type(exc).__name__,message=str(exc))
            if isinstance(exc,json.JSONDecodeError):row['action_error']['offset']=exc.pos
            result['status']='invalid_action';break
        row['action']=action
        messages.append(dict(role='assistant',content=content))
        if action['action']=='final':
            result.update(status='answered',answer=action['answer'],references=action['references'],references_delivered=tools.validate_references(action['references']))
            if question.get('type'):result['final_answer']=final_answer;row['final_answer']=final_answer
            break
        try:value=tools.execute(action['name'],action['arguments'])
        except (ValueError,TypeError,KeyError,PermissionError) as exc:
            result.update(status='invalid_tool_action',error_type=type(exc).__name__);break
        messages.append(dict(role='user',content='工具返回（原始资料数据）：'+value))
    else:result['status']='turn_budget_exhausted'
    result.update(counted_input_tokens=total_input,completion_tokens=total_output,tool_events=tools.events,knowledge_characters=tools.characters,
                  unique_source_lines=len(getattr(tools,'delivered_lines',set())),
                  retrieval_traces=getattr(tools,'retrieval_traces',[]))
    return result

_CACHE={};_CACHE_LOCK=threading.Lock()
def cached(key,factory):
    with _CACHE_LOCK:
        if key not in _CACHE:_CACHE[key]=(factory(),threading.Lock())
        return _CACHE[key]

def tools_for(method,mode,tier):
    from common import RESOURCES
    if method!='direct' and tier not in BUDGETS:raise ValueError('Explicit evidence tier required')
    total=BUDGETS.get(tier,6000)
    budget=KnowledgeBudget(tool_calls=1 if mode=='single_pass' else 12,tool_characters=total if mode=='single_pass' else 6000,total_characters=total)
    if method=='direct':return KnowledgeToolSession('none',budget=budget)
    corpus=cached('corpus',lambda:FrozenKnowledgeCorpus(RESOURCES/'corpus',RESOURCES/'corpus-manifest.json'))[0]
    if method=='basic':
        from chapter2_basic_search_tools import BasicSearchSession
        if mode=='agentic':return BasicSearchSession(corpus,budget)
        # Single-pass ordinary grep uses only literal terms from the raw query.
        class FixedGrep(BasicSearchSession):
            def execute(self,name,args):
                import re
                terms=re.findall(r'[A-Za-z_][A-Za-z0-9_.-]*|[\u4e00-\u9fff]{2,}',args['query'])
                return super().execute('grep',dict(pattern='|'.join(re.escape(t) for t in terms) or re.escape(args['query'])))
        return FixedGrep(corpus,budget)
    from retrieval import GraphEngine,TextEngine
    engine,lock=cached(method,lambda:GraphEngine(method) if method in {'graph','no_cross','no_aliases','no_traversal','anchor_only'} else TextEngine(method))
    traces=[]
    class Ranked:
        def search(self,query,limit):
            with lock:slots,trace=engine.query(query)
            traces.append(dict(query=query,trace=trace))
            return [dict(path=s['path'],start=s['start'],end=s['end']) for s in slots]
    session=KnowledgeToolSession('bm25',corpus=corpus,backend=Ranked(),budget=budget)
    session.retrieval_traces=traces
    return session

if __name__=='__main__':
    raise SystemExit('Callable engine only. Use runner.py prepare/verify; dispatch follows the separate execution authorization. No API requests made.')
