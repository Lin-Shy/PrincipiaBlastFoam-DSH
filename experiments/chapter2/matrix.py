"""Current approved matrix, still not authorized for formal dispatch."""
from pathlib import Path
from collections import Counter
import hashlib,json
from models import MODELS,EXPERIMENT,WORK

DATASET=WORK/'graduation-datasets/chapter02_knowledge_qa'
METHODS=('graph','bm25','e5','bge_m3','bm25_e5','bm25_bge_m3','bm25_parent','basic')
ABLATIONS=('no_cross','no_aliases','no_traversal','anchor_only')
MODES=('single_pass','agentic')
BUDGETS={'S':6000,'M':12000,'L':24000}

def configurations():
    for model in MODELS:
        yield dict(model=model,method='direct',mode='direct',budget=None)
        for mode in MODES:
            for method in METHODS:
                for budget in BUDGETS:yield dict(model=model,method=method,mode=mode,budget=budget)
            for method in ABLATIONS:yield dict(model=model,method=method,mode=mode,budget='M')

def tasks():
    binding=json.loads((DATASET/'binding.json').read_text(encoding='utf-8'))['dataset_sha256']
    questions={part:json.loads((DATASET/part/'model/questions.json').read_text(encoding='utf-8')) for part in ('objective','open')}
    for config in configurations():
        for part,rows in questions.items():
            for question in rows:
                row=dict(dataset_sha256=binding,part=part,id=question['id'],repeat=1,**config)
                row['task_id']=hashlib.sha256(json.dumps(row,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                yield row

def prepare():
    rows=list(tasks());ids={r['task_id'] for r in rows}
    assert len(rows)==len(ids)==51300
    counts=dict(Counter(r['part'] for r in rows));assert counts=={'objective':34200,'open':17100}
    dest=EXPERIMENT/'release/planning';dest.mkdir(parents=True,exist_ok=True)
    (dest/'tasks.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
    report=dict(status='approved_matrix_not_dispatched',configurations=len(list(configurations())),tasks=len(rows),parts=counts,
                methods=METHODS,ablations=ABLATIONS,modes=MODES,budgets=BUDGETS,model_requests=0,
                direct_shared_between_modes=True,formal_generation_started=False,
                parameters_approved=True,human_plan=dict(reviewers=1,calibration=60,acceptance=60),
                remaining=['formal generation authorization','real-answer human calibration and locked acceptance','judge execution and statistical reporting protocol freeze'])
    (dest/'matrix.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report

if __name__=='__main__':print(json.dumps(prepare(),ensure_ascii=False))
