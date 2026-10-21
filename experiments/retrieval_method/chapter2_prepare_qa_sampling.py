"""Outcome-blind development and supplementary subsets, plus original review pack."""
import argparse
from collections import defaultdict,Counter
import hashlib
import html
import json
from pathlib import Path
from chapter2_autonomous_qa import read,save,sha
from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus

SEED='knowledge_qa_source_sealed_sampling_v1'
def order(qid,purpose):return hashlib.sha256((SEED+'|'+purpose+'|'+qid).encode('utf-8')).hexdigest()

def one_per(rows,key,purpose):
    groups=defaultdict(list)
    for r in rows:groups[r[key]].append(r['id'])
    return sorted(min(ids,key=lambda qid:order(qid,purpose)) for ids in groups.values())

def cover_cells(selected,rows,purpose):
    cells=defaultdict(list)
    for r in rows:cells[(r['labels']['evidence_integration'],r['labels']['condition_discrimination'])].append(r['id'])
    for ids in cells.values():
        if not set(ids)&set(selected):selected.append(min(ids,key=lambda qid:order(qid,purpose)))
    return sorted(set(selected))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--dataset',type=Path,required=True)
    p.add_argument('--corpus',type=Path,required=True);p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError('sampling revision is immutable')
    seal=read(a.dataset/'dataset-seal.json')
    for f,h in seal['files'].items():
        if sha(a.dataset/f)!=h:raise ValueError('sealed dataset drift')
    annotations=read(a.dataset/'scoring/annotations.json');questions={q['id']:q['question'] for q in read(a.dataset/'model/questions.json')}
    split=read(a.dataset/'split.json');evidence=read(a.dataset/'scoring/evidence.json')
    dev=[r for r in annotations if r['id'] in split['ids']['dev']];test=[r for r in annotations if r['id'] in split['ids']['test']]
    subsets={'development_pilot':cover_cells(one_per(dev,'theme_id','development'),dev,'development_cell'),
      'budget_analysis':cover_cells(one_per(test,'theme_id','budget'),test,'budget_cell'),
      'complete_material_diagnostic':cover_cells(one_per(test,'split_group','diagnostic'),test,'diagnostic_cell')}
    rows={r['id']:r for r in annotations};metadata={}
    for name,ids in subsets.items():
        metadata[name]={'ids':ids,'questions':len(ids),'themes':len({rows[i]['theme_id'] for i in ids}),
          'groups':len({rows[i]['split_group'] for i in ids}),
          'cells':dict(Counter(str((rows[i]['labels']['evidence_integration'],rows[i]['labels']['condition_discrimination'])) for i in ids))}
    save(a.output/'sampling.json',{'schema':'outcome_blind_qa_sampling_v1','seed':SEED,
      'dataset_id':seal['dataset_id'],'dataset_seal_sha256':sha(a.dataset/'dataset-seal.json'),
      'selection_policy':'One deterministic hash-selected question per dev theme, test theme for budgets, test linked knowledge group for original-material diagnostic; add uncovered type cells. No generated answers or method scores read.',
      'implementation_sha256':sha(Path(__file__)),'subsets':metadata,
      'formal_main_test_ids':split['ids']['test'],'human_original_review_status':'pending'} )
    corpus=FrozenKnowledgeCorpus(a.corpus,a.manifest);pack=[];sections=[]
    for qid in subsets['complete_material_diagnostic']:
        row=rows[qid];original=[]
        for eid in row['required_evidence_ids']:
            e=evidence[eid];raw=corpus.read(e['path'],e['line_start'],e['line_end'])
            if raw['sha256']!=e['file_sha256'] or '\n'.join(l['text'] for l in raw['lines'])!=e['excerpt']:raise ValueError('original review material drift')
            original.append(raw)
        pack.append({'id':qid,'question':questions[qid],'original_material':original})
        blocks=[]
        for raw in original:
            title=f"{raw['path']} : {raw['start']}–{raw['end']}"
            text='\n'.join(f"{l['number']:4d}  {l['text']}" for l in raw['lines'])
            blocks.append('<details open><summary>'+html.escape(title)+'</summary><pre>'+html.escape(text)+'</pre></details>')
        sections.append('<section id="'+html.escape(qid)+'"><h2>'+html.escape(qid)+'</h2><p>'+html.escape(questions[qid])+'</p>'+''.join(blocks)+'</section>')
    folder=a.output/'evaluation_only';save(folder/'complete-material-inputs.json',pack)
    page='''<!doctype html><html lang="zh"><meta charset="utf-8"><title>完整原文资料诊断复核包</title><style>body{max-width:1100px;margin:36px auto;padding:0 24px;font:17px/1.65 system-ui;color:#203047}h1{font-size:28px}h2{font-size:22px}section{border-top:2px solid #dbe3eb;margin-top:42px;padding-top:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f6f8;padding:18px;font:14px/1.65 Consolas,monospace}summary{font-weight:600;cursor:pointer}aside{background:#edf3fa;padding:20px}</style><h1>完整原文资料诊断：人工复核包</h1><aside>本包仅用于单独的完整资料诊断。请确认每题所列原文是否足以支持该题的必要专业解释和条件判断，并指出缺失或冗余资料。这里不给参考答案或评分要点；此前资料审查由 AI 完成，尚未取得人工确认。正常问答、图谱和索引均不得读取本包。</aside>'''+''.join(sections)+'</html>'
    (folder/'original-material-review.html').write_text(page,encoding='utf-8')
    save(folder/'review-status.json',{'schema':'human_original_material_review_pending_v1','status':'pending',
      'material_sha256':sha(folder/'complete-material-inputs.json'),'html_sha256':sha(folder/'original-material-review.html'),
      'question_ids':subsets['complete_material_diagnostic'],'human_confirmed':False,
      'normal_production_use_prohibited':True})
    print(json.dumps({k:{'questions':v['questions'],'groups':v['groups'],'themes':v['themes']} for k,v in metadata.items()}))

if __name__=='__main__':main()
