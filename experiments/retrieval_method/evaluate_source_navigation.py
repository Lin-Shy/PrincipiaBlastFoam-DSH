"""Replay full task variants without invoking an LLM; retain failed bindings."""
import argparse
import json
from pathlib import Path
import time
from experiments.retrieval_method.native_factory_server import locate


def main():
    p=argparse.ArgumentParser();p.add_argument('--suite',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--budget',type=int,default=5000)
    a=p.parse_args();results=[]
    for task in json.loads(a.suite.read_text())['tasks']:
        for prompt in task['prompts']:
            start=time.perf_counter();packet=locate(prompt,task['case'],budget=a.budget)
            edits={(e['path'],e['entry']):e['value'] for e in packet.get('model_draft',{}).get('edits',[])}
            expected={(e['path'],e['entry']):e['value'] for e in task['edits']}
            matched=edits==expected
            deps=[e for c in packet.get('conditional_drafts',[]) for e in c.get('preparation_edits',c.get('edits_if_true',[]))]
            results.append({'task':task['id'],'prompt':prompt,'packet':packet,'complete_edits':matched,
                            'dependency_edits':deps,'seconds':time.perf_counter()-start,
                            'characters':len(json.dumps(packet,ensure_ascii=False,separators=(',',':')))})
            print(json.dumps({k:v for k,v in results[-1].items() if k not in ('prompt','packet')},ensure_ascii=False),flush=True)
    a.output.write_text(json.dumps(results,ensure_ascii=False,indent=2))
    if not all(r['complete_edits'] and not r['dependency_edits'] for r in results):raise SystemExit(1)


if __name__=='__main__':main()
