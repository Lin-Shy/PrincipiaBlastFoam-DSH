"""Deterministic objective scoring, with strict answer boundaries and no LLM judge."""
import re, unicodedata
from decimal import Decimal, InvalidOperation

VERSION='objective_rules_v2_structured_final'
def normalize(s):
    return unicodedata.normalize('NFKC',str(s)).strip().strip('`').strip()

def score(question,gold,result):
    answer=result.get('answer') or ''
    row=dict(id=question['id'],type=question['type'],raw_answer=answer,normalized_answer='',
             score=0,score_bounds=[0,0],format_valid=False,reason='generation_failed',scoring_version=VERSION)
    if result.get('status')!='answered':
        if result.get('status') in {None,'not_run','started','in_flight','outcome_unknown','http_result_unknown','usage_unknown','runner_error','deployment_halted','not_dispatched_model_halted'}:
            row.update(score=None,score_bounds=[0,1],reason='not_run_or_outcome_unknown')
        return row
    # Exactly one explicit final marker; do not search explanations for the gold answer.
    lines=[line.strip() for line in answer.splitlines() if line.strip()]
    marked=[result['final_answer']] if 'final_answer' in result else [line.split(':',1)[1].strip() for line in lines if line.startswith('FINAL:')]
    if len(marked)!=1 or not isinstance(marked[0],str) or ('final_answer' not in result and (not lines or not lines[-1].startswith('FINAL:'))):
        row['reason']='missing_or_multiple_final_marker';return row
    value=normalize(marked[0]);row['normalized_answer']=value
    if not value:
        row['reason']='empty_final';return row
    kind=question['type'];accepted=[gold['answer']]+gold.get('aliases',[])
    if kind=='single':
        row['format_valid']=bool(re.fullmatch('[ABCD]',value))
        correct=value==gold['answer']
    elif kind=='judge':
        mapping={'正确':True,'错误':False,'true':True,'false':False,'是':True,'否':False,'对':True,'错':False}
        row['format_valid']=value in mapping
        correct=row['format_valid'] and mapping[value]==mapping[gold['answer']]
    elif gold.get('numeric'):
        # Inputs explicitly request original file units; unexpected suffixes are rejected.
        try:
            number=Decimal(value);target=Decimal(gold['answer'])
            row['format_valid']=number.is_finite() and bool(re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?',value))
            tolerance=max(Decimal(str(gold.get('absolute_tolerance',0))),abs(target)*Decimal(str(gold.get('relative_tolerance',0))))
            correct=row['format_valid'] and abs(number-target)<=tolerance
        except InvalidOperation:correct=False
    else:
        row['format_valid']=bool(re.fullmatch(r'[-\w.<>]+',value))
        correct=value in [normalize(x) for x in accepted]
    row['score']=int(row['format_valid'] and correct)
    row['score_bounds']=[row['score'],row['score']]
    row['reason']='correct' if row['score'] else ('wrong_answer' if row['format_valid'] else 'invalid_final_format')
    return row
