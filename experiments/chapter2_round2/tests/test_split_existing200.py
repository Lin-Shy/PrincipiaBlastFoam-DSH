from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
from common import *
from split_existing200 import SPLIT,OUT,verify,summarize_grid

def test_exact_existing_partition_no_new_questions():
    p=verify();d=p['development'];t=p['test']
    assert set(t['ids'])==set(read(DATASET/'dataset.json')['new_ids'])
    assert len(d['ids'])==160 and len(t['ids'])==40 and not set(d['ids'])&set(t['ids'])
    assert t['types']==dict(S0=7,S1=6,M0=20,M1=7)
    assert len(t['knowledge_groups'])==5 and len(d['knowledge_groups'])==20
    assert p['researcher_confirmation']['recorded_now_not_backdated']
    assert not p['policy']['new_generation']and not p['policy']['new_judging']

@pytest.mark.parametrize('model',['8b','14b'])
def test_rows_are_exact_references_to_unchanged_originals(model):
    full=read(CURRENT/'basic_search_200_20261019_001'/('qwen3-'+model)/'analysis_001/session-metrics.json')
    by={(r['arm'],r['id']):r for r in full};seen=set()
    for part,n in [('development',160),('test',40)]:
        rows=read(OUT/model/part/'session-metrics.json');summary=read(OUT/model/part/'summary.json')
        assert len(rows)==n*8 and all(r==by[(r['arm'],r['id'])]for r in rows)
        assert not seen&{(r['arm'],r['id'])for r in rows};seen|={(r['arm'],r['id'])for r in rows}
        for arm,v in summary['by_arm'].items():
            own=[r for r in rows if r['arm']==arm]
            assert v['n']==n and v['score_lower']==pytest.approx(sum(r['score_lower']for r in own)/n)
    assert seen==set(by)

@pytest.mark.parametrize('model',['8b','14b'])
def test_statistics_use_actual5_groups_and_correct_families(model):
    p=read(OUT/model/'test/summary.json')
    assert p['knowledge_groups']==5 and len(p['comparisons']['primary'])==5 and len(p['comparisons']['ablation'])==2
    for values in p['comparisons'].values():
        assert all(not v['statistical_positive_identified']and v['holm_p_upper']>=.05 for v in values)
    assert read(OUT/model/'development/summary.json')['comparisons']=={}

def test_missing_or_duplicate_rows_refused():
    p=read(OUT/'8b/test/summary.json');rows=read(OUT/'8b/test/session-metrics.json');ids=verify()['test']['ids']
    with pytest.raises(ValueError):summarize_grid(rows[:-1],list(p['by_arm']),ids,True)
    with pytest.raises(ValueError):summarize_grid(rows[:-1]+[rows[0]],list(p['by_arm']),ids,True)

def test_rejected_drafts_and_builders_removed():
    assert not(DATASET.parent/'holdout_v1_60_draft_20261020').exists()
    assert not(DATASET.parent/'holdout_v2_40_draft_20261020').exists()
    assert not(HERE/'holdout_authoring.py').exists()and not(HERE/'holdout40_execution.py').exists()
    assert not(ARCHIVE/'authorizations/holdout40_v1.json').exists()
