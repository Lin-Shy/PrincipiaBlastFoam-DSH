"""Planned-observation accounting and linked-knowledge-group comparisons."""
from collections import defaultdict
import math
import statistics
from chapter2_family_statistics import bounded_paired_bootstrap

def aggregate_planned(scores,annotations,question_ids,repeats):
    """Average repeats within questions, then questions within linked groups.

    Missing planned scores remain [0,1]. They never shrink a denominator or
    change the number of independent groups used by a comparison.
    """
    if type(repeats) is not int or repeats<1 or len(question_ids)!=len(set(question_ids)) or not question_ids:
        raise ValueError('nonempty unique planned IDs and positive repeats required')
    expected={(qid,rep) for qid in question_ids for rep in range(repeats)};actual={}
    for row in scores:
        key=(row['question_id'],row['replicate'])
        if key not in expected or key in actual:raise ValueError('unplanned or duplicate score observation')
        lo,hi=row['lower'],row['upper']
        if isinstance(lo,bool) or isinstance(hi,bool) or not isinstance(lo,(int,float)) or not isinstance(hi,(int,float)) or not 0<=lo<=hi<=1:
            raise ValueError('finite outcome bounds in [0,1] required')
        actual[key]=(lo,hi)
    grouped=defaultdict(list);question_bounds={}
    for qid in question_ids:
        bounds=[actual.get((qid,rep),(0,1)) for rep in range(repeats)]
        value=(statistics.mean(lo for lo,hi in bounds),statistics.mean(hi for lo,hi in bounds))
        question_bounds[qid]=value;grouped[annotations[qid]['split_group']].append(value)
    means={g:(statistics.mean(lo for lo,hi in xs),statistics.mean(hi for lo,hi in xs)) for g,xs in grouped.items()}
    return {'planned_questions':len(question_ids),'planned_observations':len(expected),
      'missing_observations':len(expected-set(actual)),'observed_unknown':sum(lo!=hi for lo,hi in actual.values()),
      'independent_groups':len(grouped),'question_bounds':question_bounds,'group_question_bounds':dict(grouped),
      'group_mean_bounds':means,'group_macro_bounds':(statistics.mean(lo for lo,hi in means.values()),statistics.mean(hi for lo,hi in means.values())),
      'question_micro_bounds':(statistics.mean(lo for lo,hi in question_bounds.values()),statistics.mean(hi for lo,hi in question_bounds.values()))}

def exact_signflip(differences):
    """One-sided paired group sign test under sign-exchangeable null effects."""
    if not differences or any(not isinstance(d,(int,float)) or not math.isfinite(d) for d in differences):raise ValueError('finite nonempty paired differences required')
    values=[d for d in differences if d!=0]
    if len(values)>20:raise ValueError('exact enumeration limited to 20 nonzero independent groups')
    observed=sum(values);extreme=0;n=1<<len(values)
    for mask in range(n):
        value=sum(d if mask&(1<<i) else -d for i,d in enumerate(values))
        if value>=observed-1e-12:extreme+=1
    return {'p_one_sided':extreme/n,'nonzero_groups':len(values),'permutations':n,
      'assumption':'paired linked-knowledge-group differences are sign-exchangeable under the null; repeated questions are not independent permutations'}

def paired_comparison(left,right,*,resamples=10000,seed=20261013):
    if set(left['question_bounds'])!=set(right['question_bounds']):raise ValueError('comparisons require identical planned questions')
    bounds=bounded_paired_bootstrap(left['group_question_bounds'],right['group_question_bounds'],resamples=resamples,seed=seed)
    fully_known=all(lo==hi for a in (left,right) for lo,hi in a['question_bounds'].values())
    if fully_known:
        groups=sorted(left['group_mean_bounds'])
        test=exact_signflip([left['group_mean_bounds'][g][0]-right['group_mean_bounds'][g][0] for g in groups])
    else:test={'p_one_sided':None,'reason':'unresolved semantic/missing outcomes; no confirmatory significance claim'}
    return {'bounds':bounds,'test':test,'fully_known':fully_known,'significance_claim_allowed':fully_known}

def holm_planned(comparisons,alpha=.05):
    """Keep all preregistered hypotheses, including tests with unknown outcomes."""
    if not comparisons or not 0<alpha<1:raise ValueError('planned comparison family and valid alpha required')
    values=[]
    for name,result in comparisons.items():
        p=result['test']['p_one_sided']
        if p is not None and not 0<=p<=1:raise ValueError('invalid p value')
        values.append((1 if p is None else p,name,p is not None))
    values.sort();m=len(values);adjusted=0;rows={}
    for rank,(p,name,known) in enumerate(values):
        adjusted=max(adjusted,min(1,(m-rank)*p))
        rows[name]={'holm_adjusted_p':adjusted if known else None,'test_known':known,
          'reject':bool(known and adjusted<=alpha and comparisons[name]['significance_claim_allowed']),
          'planned_family_size':m}
    return rows
