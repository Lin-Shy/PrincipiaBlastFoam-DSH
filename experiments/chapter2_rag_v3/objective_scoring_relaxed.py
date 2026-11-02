"""Supplementary parser: also accept a single unambiguous bare answer line.

The frozen strict score remains authoritative for the original protocol. This
analysis is applied uniformly to every response, without consulting correctness
to choose which parser to use.
"""
import re
from objective_scoring import normalize, score as strict_score

VERSION='objective_rules_v2_supplementary_bare_line'

def score(question,gold,result):
    original=result.get('answer') or ''
    strict=strict_score(question,gold,result)
    strict['scoring_version']=VERSION
    if result.get('status')!='answered':
        strict['parse_route']='generation_failed'
        return strict
    strict['parse_route']='explicit_marker'
    if strict['reason']!='missing_or_multiple_final_marker':
        return strict
    lines=[line.strip() for line in original.splitlines() if line.strip()]
    if len(lines)!=1 or 'FINAL:' in original:
        strict['parse_route']='unparsed'
        return strict
    value=normalize(lines[0]);kind=question['type']
    if kind=='single':allowed=bool(re.fullmatch(r'[ABCD]',value))
    elif kind=='judge':allowed=value in {'正确','错误','true','false','是','否','对','错'}
    elif gold.get('numeric'):allowed=bool(re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?',value))
    else:allowed=bool(re.fullmatch(r'[-\w.<>]+',value))
    if not allowed:
        strict['parse_route']='unparsed'
        return strict
    synthetic={**result,'answer':'FINAL: '+value}
    revised=strict_score(question,gold,synthetic)
    revised.update(raw_answer=original,scoring_version=VERSION,parse_route='bare_single_line')
    return revised
