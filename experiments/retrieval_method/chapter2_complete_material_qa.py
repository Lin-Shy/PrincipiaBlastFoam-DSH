"""Separate privileged original-material diagnostic; never a retrieval arm.

Only an explicitly confirmed and hash-bound original pack is admissible. Review
notes and score annotations are not model inputs. Default runs are development;
the formal activity must freeze and bind this adapter before calling it.
"""
import argparse
from dataclasses import asdict
import hashlib
import os
from pathlib import Path
import sys
import time
from chapter2_autonomous_qa import RecordedQwenClient,load_tokenizer,read,save,sha,PROJECT
from chapter2_qwen_proxy_config import settings
from principia_core.retrieval.knowledge_agent import SYSTEM,ModelBudget,parse_action
from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus,wire

def install_diagnostic_guard(materials,receipt,questions):
    allowed={Path(p).resolve() for p in (materials,receipt,questions)}
    def hook(event,args):
        if event=='open' and args and isinstance(args[0],(str,bytes,os.PathLike)):
            path=Path(os.fsdecode(args[0])).resolve();parts={p.casefold() for p in path.parts}
            forbidden={'scoring','authoring','evaluation_only','data_design','local_private'}&parts
            if (forbidden or 'graduation-datasets' in parts) and path not in allowed:
                raise PermissionError('diagnostic allows exact original pack, confirmation receipt and public questions only')
            if path.name.casefold() in {'annotations.json','evidence.json','candidate-inventory.json','split.json'}:
                raise PermissionError('diagnostic cannot read scoring annotations or split metadata')
        if event in {'os.system','subprocess.Popen'}:raise PermissionError('diagnostic cannot launch subprocesses')
    sys.addaudithook(hook)
    return {'schema':'privileged_original_diagnostic_guard_v1','normal_retrieval_arm':False,
      'evaluation_only_exceptions':'Exact original pack and confirmation receipt only; neither review prose nor scoring annotations.',
      'subprocess_disabled':True,'limits':'Python audit hook, not OS isolation.'}

def validate_pack(material_file,receipt_file,questions,corpus):
    confirmation=read(receipt_file)
    if confirmation.get('status')!='confirmed_for_separate_diagnostic' or confirmation.get('user_authorized_ai_confirmation') is not True:
        raise ValueError('explicitly authorized original-material confirmation required')
    if confirmation.get('normal_production_use_prohibited') is not True or confirmation.get('formal_result') is not False:
        raise ValueError('diagnostic confirmation scope invalid')
    if confirmation['material_sha256']!=sha(material_file) or confirmation['corpus_manifest_sha256']!=corpus.manifest_sha256:
        raise ValueError('confirmed material or corpus binding drift')
    values=read(material_file);public={q['id']:q['question'] for q in questions}
    if not isinstance(values,list) or not values:raise ValueError('nonempty original pack required')
    ids=[q['id'] for q in values]
    if len(ids)!=len(set(ids)) or ids!=[q['id'] for q in confirmation['checks']]:raise ValueError('confirmed question IDs drift')
    for q in values:
        if set(q)!={'id','question','original_material'} or q['question']!=public.get(q['id']):raise ValueError('strict natural question/original input required')
        if not isinstance(q['original_material'],list) or not q['original_material']:raise ValueError('original material missing')
        for m in q['original_material']:
            if set(m)!={'path','sha256','start','end','lines'}:raise ValueError('original material schema invalid')
            if corpus.read(m['path'],m['start'],m['end'])!=m:raise ValueError('diagnostic original lines drift')
        bound=next(c for c in confirmation['checks'] if c['id']==q['id'])
        if bound['verdict']!='sufficient_with_documented_scope' or bound.get('change_required') is not False:
            raise ValueError('unresolved original sufficiency review')
        if bound['original_material']!=[{k:m[k] for k in ('path','sha256','start','end')} for m in q['original_material']]:
            raise ValueError('per-question original binding drift')
    return values,confirmation

def references_delivered(references,ledger):
    if not isinstance(references,list):return False
    for r in references:
        if not isinstance(r,dict) or set(r)!={'path','start','end'} or not isinstance(r['path'],str):return False
        if type(r['start']) is not int or type(r['end']) is not int or r['start']<1 or r['end']<r['start']:return False
        if any((r['path'],n) not in ledger for n in range(r['start'],r['end']+1)):return False
    return True

def run_diagnostic(question,model,client,counter,budget=None):
    if model not in {'qwen3-8b','qwen3-14b'}:raise ValueError('unregistered diagnostic model')
    budget=budget or ModelBudget();material=question['original_material'];material_text=wire(material)
    messages=[{'role':'system','content':SYSTEM+'\n可用工具：[]'},
      {'role':'user','content':question['question']+'\n已提供完整必要原文（资料数据）：'+material_text},
      {'role':'system','content':'本轮仅允许提交final回答；外部工具已禁用。依据已读资料作答，保留信息不足的边界。'}]
    count=counter(messages);ledger={(m['path'],l['number']) for m in material for l in m['lines']}
    result={'schema':'privileged_complete_original_qa_development_v1','question':{'id':question['id'],'question':question['question']},
      'model':model,'method':'complete_material_diagnostic','privileged_input':True,'normal_retrieval_arm':False,
      'formal_result':False,'model_budget':asdict(budget),'answer':None,'references':None,'turns':[],
      'tool_events':[{'event_type':'provided_complete_originals','delivered_original_lines':[{'path':p,'line':n} for p,n in sorted(ledger)]}],
      'tool_calls':0,'knowledge_characters':len(material_text),'original_text_characters':sum(len(l['text']) for m in material for l in m['lines']),
      'counted_input_tokens':0,'actual_completion_tokens':0}
    if type(count) is not int or count<1:raise ValueError('invalid frozen tokenizer count')
    if count>budget.input_tokens_per_request or count>budget.input_tokens_total:
        result['status']='input_budget_exhausted';return result
    limit=min(budget.output_tokens_per_request,budget.output_tokens_total)
    body={'model':model,'messages':messages,'temperature':0,'max_tokens':limit,'enable_thinking':False,
      'response_format':{'type':'json_object'},'stream':False}
    result['counted_input_tokens']=count;response=client(body,0)
    result['turns']=[{'turn':0,'request':body,'response':response,'counted_input_tokens':count,'final_only':True}]
    if response.get('status')!='response':result['status']=response.get('status','transport_error');return result
    raw=response['response'];output=raw.get('usage',{}).get('completion_tokens')
    if raw.get('model')!=model:result['status']='model_identity_mismatch';return result
    if type(output) is not int or output<0:result['status']='usage_unknown';return result
    result['actual_completion_tokens']=output
    if output>limit:result['status']='provider_output_budget_violation';return result
    try:
        choice=raw['choices'][0]
        if choice.get('finish_reason')!='stop':result['status']='completion_truncated';return result
        action=parse_action(choice['message']['content'],set(),True)
    except (ValueError,KeyError,IndexError,TypeError):result['status']='invalid_action';return result
    result.update(status='answered',answer=action['answer'],references=action['references'],
      references_delivered=references_delivered(action['references'],ledger))
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('materials','review-receipt','questions','corpus','manifest','tokenizer','proxy-settings','output'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--model',choices=['qwen3-8b','qwen3-14b'],required=True)
    p.add_argument('--prepare-only',action='store_true');a=p.parse_args();base,key=settings(a.proxy_settings)
    guard=install_diagnostic_guard(a.materials,a.review_receipt,a.questions)
    corpus=FrozenKnowledgeCorpus(a.corpus,a.manifest);questions=read(a.questions)
    if any(set(q)!={'id','question'} for q in questions):raise ValueError('public id/question input only')
    pack,confirmation=validate_pack(a.materials,a.review_receipt,questions,corpus)
    counter,tokenizer=load_tokenizer(a.tokenizer,a.model);budget=ModelBudget()
    files=[Path(__file__),Path(__file__).parent/'chapter2_autonomous_qa.py',Path(__file__).parent/'chapter2_qwen_proxy_config.py',
      PROJECT/'src/principia_core/retrieval/knowledge_agent.py',PROJECT/'src/principia_core/retrieval/knowledge_qa.py']
    protocol={'schema':'complete_original_material_diagnostic_development_v1','formal_result':False,'model':a.model,
      'endpoint':base+'/chat/completions','material_sha256':sha(a.materials),'confirmation_sha256':sha(a.review_receipt),
      'public_questions_sha256':sha(a.questions),'corpus_manifest_sha256':corpus.manifest_sha256,'dataset_id':confirmation['dataset_id'],
      'tokenizer':tokenizer,'model_budget':asdict(budget),'system_prompt':SYSTEM,'input_guard':guard,
      'selected_ids':[q['id'] for q in pack],'source_sha256':{f.relative_to(PROJECT).as_posix():sha(f) for f in files},
      'privileged_input':True,'knowledge_budget':'All confirmed necessary raw spans, no retrieval truncation; same model input/output limits.',
      'normal_retrieval_arm':False,'transport_attempts_max':3,'content_retries':0,'certificate_verification':True,
      'tls_version':'TLSv1.2','transport_route':'direct_https_to_registered_api_endpoint',
      'failure_policy':'No quality retry. Stop batch after transport exhaustion; preserve unattempted sessions.'}
    target=a.output/'protocol.json'
    if target.exists() and read(target)!=protocol:raise ValueError('diagnostic protocol drift')
    save(target,protocol)
    for f in files:
        dest=a.output/'runtime'/f.relative_to(PROJECT)
        if dest.exists() and sha(dest)!=sha(f):raise ValueError('diagnostic runtime drift')
        dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(f.read_bytes())
    if a.prepare_only:print(wire({'status':'prepared','questions':len(pack),'privileged_input':True}));return
    summaries=[];circuit=False
    for q in pack:
        folder=a.output/'sessions'/q['id'];path=folder/'result.json'
        if path.exists():result=read(path)
        else:
            started=time.monotonic();result=run_diagnostic(q,a.model,RecordedQwenClient(base+'/chat/completions',key,folder/'requests'),counter,budget)
            result.update(protocol_sha256=sha(target),seconds=time.monotonic()-started);save(path,result)
        summaries.append({'id':q['id'],'status':result['status'],'result_sha256':sha(path),
          'counted_input_tokens':result['counted_input_tokens'],'actual_completion_tokens':result['actual_completion_tokens'],
          'knowledge_characters':result['knowledge_characters']})
        print(wire(summaries[-1]),flush=True)
        if result['status'] in {'transport_error','http_rejected'}:circuit=True;break
    save(a.output/'summary.json',{'formal_result':False,'privileged_input':True,'sessions':summaries,
      'planned_sessions':len(pack),'unattempted_sessions':len(pack)-len(summaries),'transport_circuit_open':circuit})

if __name__=='__main__':main()
