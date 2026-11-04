"""Offline, source-only functional checks for all current retrieval configurations."""
from pathlib import Path
import json,sys
from models import EXPERIMENT,encoded,now
from matrix import METHODS,ABLATIONS,BUDGETS
from tokenization import ChatCounter
from runtime import tools_for

def main():
    # Match worker library initialization, then enforce no dataset/Gold access.
    ChatCounter('qwen3-8b')
    from chapter2_knowledge_input_guard import install
    guard=install();rows=[]
    for method in METHODS+ABLATIONS:
        for mode in ('single_pass','agentic'):
            for tier in (('M',) if method in ABLATIONS else BUDGETS):
                t=tools_for(method,mode,tier)
                if method=='basic' and mode=='agentic':value=t.execute('grep',dict(pattern='JWL'))
                else:value=t.execute('search',dict(query='JWL equationOfState'))
                packet=json.loads(value)
                passed=t.characters<=BUDGETS[tier] and len(value)<=(BUDGETS[tier] if mode=='single_pass' else 6000) and t.events[-1]['status']=='returned' and bool(packet.get('evidence'))
                rows.append(dict(method=method,mode=mode,tier=tier,characters=t.characters,unique_lines=len(t.delivered_lines),passed=passed))
        print(json.dumps(dict(method=method,passed=all(r['passed'] for r in rows if r['method']==method))),flush=True)
    direct=tools_for('direct','direct',None)
    report=dict(created_utc=now(),synthetic_queries_only=True,formal_questions_used=0,gold_used=False,model_requests=0,
        guard=guard,configurations=rows,direct_no_external_inputs=direct.corpus is None and direct.backend is None,
        passed=len(rows)==56 and all(r['passed'] for r in rows) and direct.corpus is None)
    (EXPERIMENT/'release/validation/resource_checks.json').write_bytes(encoded(report));print(json.dumps(dict(passed=report['passed'],configurations=len(rows)+1)),flush=True)

if __name__=='__main__':main()
