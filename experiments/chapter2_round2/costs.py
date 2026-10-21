"""读取历史真实回执估算新批次；私有代理价格未知时绝不冒用公开价。"""
from common import *

def main():
    basis={};totals={}
    for role,base in [('generation',HISTORICAL/'generation'),('judge',HISTORICAL/'scoring_001/sessions')]:
        counts=dict(sessions=400,requests=0,input_tokens=0,output_tokens=0,unknown_usage=0,request_seconds=0.)
        for arm in ['graph','bm25']:
            for file in sorted((base/arm).glob('*/requests/*.json')):
                row=read(file);counts['requests']+=1
                usage=row.get('response',{}).get('usage',{})
                if not isinstance(usage.get('prompt_tokens'),int) or not isinstance(usage.get('completion_tokens'),int):
                    counts['unknown_usage']+=1
                else:
                    counts['input_tokens']+=usage['prompt_tokens'];counts['output_tokens']+=usage['completion_tokens']
                counts['request_seconds']+=row.get('seconds',0.)
        basis[role]=counts
    for scale in [1000,1400,300,420]:
        totals[str(scale)]={role:{k:value/400*scale for k,value in counts.items() if k not in ['sessions','unknown_usage']}
                           for role,counts in basis.items()}
    budgets=read(HISTORICAL/'protocol.json')['model_budget']
    save(ARCHIVE/'reports/cost_estimate.json',dict(schema='round2_preapproval_cost_v1',historical_basis=basis,
        basis_protocol_sha256=sha(HISTORICAL/'protocol.json'),per_session_projection=totals,
        generation_caps={str(n):dict(input_tokens=n*budgets['input_tokens_total'],output_tokens=n*budgets['output_tokens_total']) for n in [1000,1400]},
        price_status='private proxy actual price/balance/RPM/TPM unavailable; no account bill queried; no paid requests made',
        price_formula='Cost = input_tokens / 1e6 * actual_input_price + output_tokens / 1e6 * actual_output_price; generation and judging separately',
        quota='repository routing cap16 concurrency; not evidence of current supplier RPM/TPM or balance',
        historical_unknown_usage_policy='unknown usage not assumed zero; projections may undercount unknown attempts',
        formal_generation_approval='required',formal_judge_approval='required',holdout_approval='required',
        holdout='300/420 are planning scales only; no new holdout constructed or evaluated',script_sha256=sha(Path(__file__))))
    print(wire(dict(historical_basis=basis,projection_1400=totals['1400'])))

if __name__=='__main__':main()
