from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
from common import *
from split_existing200 import SPLIT,OUT
from unify_current import SOURCES


def test_catalog_has_both_embeddings_and_no_fabricated8b_runs():
    c=read(CURRENT/'results.json')
    assert c['sessions']==4600 and len(c['methods'])==13
    assert sum(x['family']=='main'for x in c['methods'].values())==9
    assert c['methods']['e5']['family']==c['methods']['bge_m3']['family']=='main'
    assert c['models']['qwen3-8b']['test']['runs']==['original']
    assert c['models']['qwen3-14b']['test']['runs']==['original','replicate']
    assert c['human_review']['judge_calibration']==c['human_review']['graph_quality']=='pending'


@pytest.mark.parametrize('model',['qwen3-8b','qwen3-14b'])
@pytest.mark.parametrize('part,n',[('development',160),('test',40)])
def test_exact_original_scored_objects_and_separate_question_roles(model,part,n):
    rows=read(CURRENT/model/part/'session-metrics.json')
    summary=read(CURRENT/model/part/'summary.json')
    assert summary['question_count']==n and not summary['run_averaging']
    assert len(rows)==summary['sessions']
    ids=set(read(SPLIT)[part]['ids'])
    assert len(rows)==len({(r['method'],r['run'],r['record']['id'])for r in rows})
    originals={run:{(r['arm'],r['id']):r for r in read(OUT/key/part/'session-metrics.json')}
               for key,(m,run)in SOURCES.items()if m==model}
    for r in rows:
        assert r['record']['id']in ids
        assert r['record']==originals[r['run']][r['method'],r['record']['id']]
        assert (CURRENT/model/part/r['generation']).is_file()
        assert (CURRENT/model/part/r['scoring']).is_file()
    if model=='qwen3-14b':
        assert {(r['run'])for r in rows if r['method']=='graph'}=={'original','replicate'}
        assert len(summary['by_run']['original']['comparisons'].get('primary',[]))==(5 if part=='test'else 0)
        assert len(summary['by_run']['replicate']['comparisons'].get('primary',[]))==(4 if part=='test'else 0)


def test_publication_and_fixed_query_bound_to_current_catalog():
    assets=WORKSPACE/'graduation-thesis-materials/graduation-manuscript/assets/chapter2/dev160_test40'
    m=read(assets/'source-manifest.json')
    assert m['main_methods']==9 and m['ablations']==4
    assert len(m['main_display_rows'])==11
    text=(assets/'overall.tex').read_text(encoding='utf-8')
    assert 'E5 Dense'in text and 'BGE-M3 Dense'in text
    assert '完整来源图（原）'in text and '完整来源图（复验）'in text
    assert not(assets/'round2').exists()
    for rel,h in m['input_sha256'].items():assert sha(WORKSPACE/rel)==h
    for rel,h in m['outputs_sha256'].items():assert sha(assets/rel)==h
    ret=read(CURRENT/'retrieval-summary.json')
    assert ret['original_deliveries']==6600 and ret['test_deliveries']==1320
    assert all(r['n']==40 for r in ret['test'])
    assert all(r['n']==160 for r in ret['development'])
