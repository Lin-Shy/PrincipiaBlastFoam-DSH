"""汇总独立人工图审标签；pending不算人工判断，不输出虚假正确率。"""
import argparse
from collections import Counter,defaultdict
from common import *

def summarize(directory,output):
    files=[('nodes','graph_nodes_50.json','node',lambda r:r['node']['kind']),
           ('edges','graph_edges_50.json','edge',lambda r:str((r['edge']['relation'],r['edge']['cross_owner']))),
           ('aliases','graph_aliases_30.json','alias',lambda r:'generated_alias')]
    result={}
    for kind,name,identity,stratum in files:
        submitted=read(directory/name);original=read(ARCHIVE/'human_review'/name)
        if len(submitted)!=len(original):raise ValueError('sample denominator changed')
        groups=defaultdict(list)
        for row,ref in zip(submitted,original):
            if row[identity]!=ref[identity]:raise ValueError('sample identity/source changed')
            if row['status']=='complete':
                if row['judgment'] not in ['pass','fail','unknown'] or not row['reviewer_id'].strip():raise ValueError('real reviewer and valid label required')
            elif row['status']!='pending':raise ValueError('unknown review state')
            groups[stratum(row)].append(row)
        report={}
        for key,rows in groups.items():
            filled=[r for r in rows if r['status']=='complete'];counts=Counter(r['judgment'] for r in filled)
            report[key]=dict(sample_n=len(rows),reviewed_n=len(filled),pending_n=len(rows)-len(filled),judgments=dict(counts),
                correctness_lower=counts['pass']/len(filled) if filled else None,
                correctness_upper=(counts['pass']+counts['unknown'])/len(filled) if filled else None,
                interpretation='reviewed sample only; unknown bounded; pending is not a judgment')
        result[kind]=dict(status='pending' if all(r['status']=='pending' for r in submitted) else 'filled_or_partial',
            sample_n=len(submitted),strata=report,input_sha256=sha(directory/name))
    save(ARCHIVE/'reports'/output/'graph_review_summary.json',dict(results=result,script_sha256=sha(Path(__file__)),
        overall_graph_accuracy='pending independent complete labels; do not equate raw stratified sample mean with population accuracy'))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--directory',type=Path,required=True);p.add_argument('--output',required=True)
    a=p.parse_args();summarize(a.directory,a.output)
