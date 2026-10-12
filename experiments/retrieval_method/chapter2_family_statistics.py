"""事实族配对bootstrap；问法和重复先在族内聚合，不扩大独立样本数。"""
import math
import random
import statistics


def percentile(values, fraction):
    ordered = sorted(values)
    position = (len(ordered)-1)*fraction
    left, right = math.floor(position), math.ceil(position)
    return ordered[left]+(ordered[right]-ordered[left])*(position-left)


def paired_bootstrap(left, right, *, resamples=10000, seed=20261003):
    """输入{family:[question/replicate values]}；只对完全相同事实族配对。"""
    if not left or set(left)!=set(right):
        raise ValueError("nonempty identical family sets required")
    if type(resamples) is not int or resamples<1:
        raise ValueError("positive resample count required")
    families=sorted(left)
    differences=[]
    for family in families:
        if not left[family] or not right[family]:
            raise ValueError("each paired family must contain planned observations")
        if any(not isinstance(x,(int,float)) or not math.isfinite(x) for x in left[family]+right[family]):
            raise ValueError("finite numeric outcomes required; represent unknowns as explicit bounds")
        differences.append(statistics.mean(left[family])-statistics.mean(right[family]))
    rng=random.Random(seed)
    n=len(families)
    samples=[sum(differences[rng.randrange(n)] for _ in range(n))/n for _ in range(resamples)]
    return {"independent_families":n,"families":families,"difference":statistics.mean(differences),
            "ci95":[percentile(samples,.025),percentile(samples,.975)],"resamples":resamples,"seed":seed,
            "unit":"paired fact family; within-family variants/repeats averaged before resampling"}


def bounded_paired_bootstrap(left, right, *, resamples=10000, seed=20261003):
    """输入{family:[(lower,upper)]}；未知评分不能按答案失败补零。"""
    for values in (left,right):
        for observations in values.values():
            if any(not 0<=lo<=hi<=1 for lo,hi in observations):
                raise ValueError("outcome probability bounds must lie in [0,1]")
    pessimistic=paired_bootstrap({f:[lo for lo,hi in xs] for f,xs in left.items()},
                                {f:[hi for lo,hi in xs] for f,xs in right.items()},resamples=resamples,seed=seed)
    optimistic=paired_bootstrap({f:[hi for lo,hi in xs] for f,xs in left.items()},
                               {f:[lo for lo,hi in xs] for f,xs in right.items()},resamples=resamples,seed=seed)
    return {"independent_families":pessimistic["independent_families"],
            "difference_bounds":[pessimistic["difference"],optimistic["difference"]],
            "bootstrap_envelope95":[pessimistic["ci95"][0],optimistic["ci95"][1]],
            "pessimistic":pessimistic,"optimistic":optimistic,
            "limits":"identification bounds plus family bootstrap; not a conventional CI for a fully observed semantic score"}
