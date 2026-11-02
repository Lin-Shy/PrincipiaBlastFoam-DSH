"""Optional deterministic unit-aware scoring for explicitly dimensioned gold.

This is a new rule for future or separately registered analyses, not a change to
objective_rules_v1. Conversion is enabled only when gold declares answer_unit;
the caller must source that metadata independently. Unknown/incompatible units,
missing units and multiple candidates are never guessed.
"""
import re
from decimal import Decimal, DecimalException, localcontext
from objective_scoring import normalize, score as frozen_score

VERSION='objective_rules_v3_explicit_units'
# Multipliers convert to the canonical unit for each dimension; all exact decimals.
UNITS={
    's':('time',Decimal('1')), 'ms':('time',Decimal('0.001')),
    'us':('time',Decimal('0.000001')), 'μs':('time',Decimal('0.000001')),
    'm':('length',Decimal('1')), 'cm':('length',Decimal('0.01')), 'mm':('length',Decimal('0.001')),
    'kg':('mass',Decimal('1')), 'g':('mass',Decimal('0.001')),
    'Pa':('pressure',Decimal('1')), 'kPa':('pressure',Decimal('1000')),
    'MPa':('pressure',Decimal('1000000')), 'bar':('pressure',Decimal('100000')),
}
NUMBER=r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
VALUE=re.compile(r'('+NUMBER+r')\s*([A-Za-zμ]+)')

def numeric_with_units(value,gold):
    unit=normalize(gold['answer_unit'])
    if unit not in UNITS:raise ValueError('unsupported or missing gold unit')
    try:
        target=Decimal(str(gold['answer']))
        absolute=Decimal(str(gold.get('absolute_tolerance',0)))
        relative=Decimal(str(gold.get('relative_tolerance',0)))
    except DecimalException as exc:
        raise ValueError('invalid numeric target or tolerance') from exc
    if not target.is_finite() or not absolute.is_finite() or not relative.is_finite() or absolute<0 or relative<0:
        raise ValueError('invalid numeric target or tolerance')
    match=VALUE.fullmatch(normalize(value))
    if not match:return None,False
    number=Decimal(match.group(1));source=match.group(2)
    if not number.is_finite() or source not in UNITS or UNITS[source][0]!=UNITS[unit][0]:return None,False
    try:
        with localcontext() as context:
            context.prec=50
            converted=number*UNITS[source][1]/UNITS[unit][1]
            tolerance=max(absolute,abs(target)*relative)
            return converted,abs(converted-target)<=tolerance
    except DecimalException:
        return None,False

def score(question,gold,result):
    # No explicit unit means byte-for-byte frozen decision semantics.
    if not gold.get('numeric') or 'answer_unit' not in gold:
        return frozen_score(question,gold,result)
    row=frozen_score(question,gold,result)
    row['scoring_version']=VERSION
    if result.get('status')!='answered' or row['reason'] in ('missing_or_multiple_final_marker','empty_final'):
        return row
    converted,correct=numeric_with_units(row['normalized_answer'],gold)
    row['format_valid']=converted is not None
    row['normalized_answer']=str(converted)+' '+normalize(gold['answer_unit']) if converted is not None else row['normalized_answer']
    row['score']=int(correct)
    row['reason']='correct' if correct else ('wrong_answer' if converted is not None else 'invalid_final_format')
    return row
