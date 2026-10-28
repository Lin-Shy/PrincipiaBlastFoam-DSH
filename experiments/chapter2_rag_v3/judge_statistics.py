"""Offline human-reference comparison. Missing/unknown are never invented labels."""
import argparse
import collections
import hashlib
import json
import math
from pathlib import Path
import random
import statistics

from judge_contract import SUPPORTED_JUDGES as JUDGES,metrics,validate,validate_sources


def ordinal_agreement(pairs):
    known=[(x,y) for x,y in pairs if type(x) in (int,float) and type(y) in (int,float) and x in (0,.25,.5,.75,1) and y in (0,.25,.5,.75,1)]
    if not known:return dict(n=0,unknown_pairs=len(pairs),exact=None,quadratic_kappa=None,
                             mae=None,bias_right_minus_left=None,confusion=[])
    cats=[0,.25,.5,.75,1];n=len(known)
    observed=sum((x-y)**2 for x,y in known)/n
    left=collections.Counter(x for x,_ in known);right=collections.Counter(y for _,y in known)
    expected=sum(left[x]*right[y]*(x-y)**2 for x in cats for y in cats)/n**2
    return dict(n=n,unknown_pairs=len(pairs)-n,exact=sum(x==y for x,y in known)/n,
                mae=statistics.mean(abs(y-x) for x,y in known),
                bias_right_minus_left=statistics.mean(y-x for x,y in known),
                max_absolute_difference=max(abs(y-x) for x,y in known),
                left_distribution=dict(sorted(left.items())),right_distribution=dict(sorted(right.items())),
                confusion=[dict(left=x,right=y,count=count) for (x,y),count in sorted(collections.Counter(known).items())],
                quadratic_kappa=1-observed/expected if expected else None,
                kappa_status='defined' if expected else 'undefined_zero_expected_disagreement')


def gate_agreement(pairs):
    # Compatibility entry: F and A now use the same five-level ordinal statistic.
    return ordinal_agreement(pairs)


def cluster_intervals(values,resamples=2000,seed=20261021):
    # values: (question_id, signed EAS difference); resample question clusters.
    grouped=collections.defaultdict(list)
    for q,v in values:grouped[q].append(v)
    if not grouped:return dict(questions=0,mae_interval=None,bias_interval=None)
    keys=sorted(grouped);rng=random.Random(seed);mae=[];bias=[]
    for _ in range(resamples):
        sample=[v for q in rng.choices(keys,k=len(keys)) for v in grouped[q]]
        mae.append(statistics.mean(abs(v) for v in sample));bias.append(statistics.mean(sample))
    def interval(values):
        values=sorted(values);return [values[int(.025*(len(values)-1))],values[int(.975*(len(values)-1))]]
    return dict(questions=len(keys),mae_interval=interval(mae),bias_interval=interval(bias),resamples=resamples,seed=seed,
                interpretation='Small-sample diagnostic cluster bootstrap, not reliability certification')


def metric_error(values):
    """(question_id, right-minus-left) pairs; errors use the metric's native units."""
    return dict(identified_pairs=len(values),
                mae=statistics.mean(abs(v) for _,v in values) if values else None,
                bias_right_minus_left=statistics.mean(v for _,v in values) if values else None,
                uncertainty=cluster_intervals(values))


def dual_eas(values):
    """Per-answer average of exactly two judges, BEFORE Human-reference errors."""
    if len(values)!=2:raise ValueError('Exactly two independent judges required')
    result={}
    for name in ('arith','geo'):
        key='EAS_'+name;bound='eas_'+name+'_bounds'
        result[key]=statistics.mean(v[key] for v in values) if all(v[key] is not None for v in values) else None
        result[bound]=[statistics.mean(v[bound][i] for v in values) for i in (0,1)]
    return result


if __name__=='__main__':
    from scoring import report
    report()
