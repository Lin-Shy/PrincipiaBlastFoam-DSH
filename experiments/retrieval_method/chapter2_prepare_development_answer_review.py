"""Outcome-blind, method-label-masked original review of actual dev answers."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from chapter2_autonomous_qa import read,save,sha
from chapter2_answer_scoring import scoring_payload
from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus

SEED='actual_dev_answer_review_v1'
def order(qid):return hashlib.sha256((SEED+'|'+qid).encode()).hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('matrix','dataset','corpus','manifest','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise FileExistsError('review pack revision is immutable')
    matrix=read(a.matrix);seal=read(a.dataset/'dataset-seal.json')
    for name,h in seal['files'].items():
        if sha(a.dataset/name)!=h:raise ValueError('sealed dataset drift')
    annotations={q['id']:q for q in read(a.dataset/'scoring/annotations.json')};evidence=read(a.dataset/'scoring/evidence.json')
    corpus=FrozenKnowledgeCorpus(a.corpus,a.manifest)
    # Round-robin method assignment after fixed hash order. Neither answer text,
    # generation status nor scores are read until selection is fixed.
    methods=['bm25','e5','hybrid','graph','none'];ids=sorted(matrix['question_ids'],key=order)
    selections=[(qid,methods[i%len(methods)]) for i,qid in enumerate(ids)]
    if len({annotations[q]['theme_id'] for q in ids})!=len(ids):raise ValueError('review expects one selected question per development theme')
    pack=[];blind=[]
    for i,(qid,method) in enumerate(selections,1):
        arm=next(r for r in matrix['arms'] if r['model']=='qwen3-14b' and r['method']==method)
        folder=Path(arm['command'][arm['command'].index('--output')+1]);path=folder/'sessions'/qid/'result.json';result=read(path)
        if sha(folder/'protocol.json')!=arm['protocol_sha256']:raise ValueError('development protocol drift')
        item={'review_id':'S'+str(i).zfill(3),'question_id':qid,'question':result['question']['question'],
          'generation_status':result['status'],'references':result.get('references'),'references_delivered':result.get('references_delivered')}
        if result['status']=='answered':
            delivered=[line for e in result.get('tool_events',[]) for line in e.get('delivered_original_lines',[])]
            payload=scoring_payload(result['question']['question'],annotations[qid],evidence,corpus,result['answer'],delivered)
            item.update(answer=payload['answer'],rubric=payload['rubric'],original_material=payload['original_material'])
        else:item.update(answer=None,rubric=None,original_material=None)
        pack.append(item)
        blind.append({'review_id':item['review_id'],'question_id':qid,'method':method,'model':'qwen3-14b',
          'result_file':str(path),'result_sha256':sha(path),'protocol_sha256':sha(folder/'protocol.json')})
    private=a.output/'evaluation_only';save(private/'inputs.json',pack);save(private/'blind-key.json',blind)
    save(a.output/'selection.json',{'schema':'method_masked_actual_development_answer_review_v1','seed':SEED,
      'selection_rule':'Fixed question hash order, round-robin among five methods, no outcomes read before selection.',
      'questions':len(pack),'themes':len(ids),'method_counts':dict(Counter(m for _,m in selections)),
      'inputs_sha256':sha(private/'inputs.json'),'blind_key_sha256':sha(private/'blind-key.json'),
      'matrix_sha256':sha(a.matrix),'dataset_seal_sha256':sha(a.dataset/'dataset-seal.json'),'implementation_sha256':sha(Path(__file__)),
      'human_review':False,'formal_result':False,'normal_production_input_prohibited':True,
      'review_status':'pending; inspect inputs without method key before writing verdicts'})
    target=a.output/'runtime'/Path(__file__).name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(Path(__file__).read_bytes())
    print(json.dumps({'questions':len(pack),'method_counts':dict(Counter(m for _,m in selections)),'review_status':'pending'}))

if __name__=='__main__':main()
