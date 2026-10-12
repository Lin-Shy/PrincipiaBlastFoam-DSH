import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from leaderboard_cost import peak, price, stage


SCRIPT = Path(__file__).resolve().parents[1] / 'experiments/retrieval_method/leaderboard_cost.py'


def test_reported_cost_retains_unknown_and_peak_boundary_range():
    keys=['prompt_cache_hit_tokens','prompt_cache_miss_tokens','completion_tokens']
    spec={'effective_utc':'2026-08-16T16:00:00+00:00','usd_per_million':{
        'peak':dict(zip(keys,[.014,.44,1.32])),'off_peak':dict(zip(keys,[.007,.22,.66]))}}
    def event(iso,seconds):return {'started_unix_ns':int(datetime.fromisoformat(iso).timestamp()*1e9),'seconds':seconds}
    usage=dict(zip(keys,[0,1000000,1000000]));usage.update(prompt_tokens=1000000,total_tokens=2000000)
    assert price(None,event('2026-09-10T03:00:00+00:00',10),spec) is None
    assert price(usage,event('2026-09-10T03:00:00+00:00',10),spec)==(1.76,1.76)
    assert price(usage,event('2026-09-10T03:59:59+00:00',2),spec)==(.88,1.76)
    assert not peak(datetime.fromisoformat('2026-09-12T03:00:00+00:00').timestamp())


def test_inherited_physical_attempt_is_not_charged_twice(tmp_path):
    from leaderboard_cost import stage
    import leaderboard_audit as audit
    import shutil
    keys=['prompt_cache_hit_tokens','prompt_cache_miss_tokens','completion_tokens']
    spec={'model':'fixture','effective_utc':'2026-08-16T16:00:00+00:00',
        'usd_per_million':{'peak':dict(zip(keys,[.014,.44,1.32])), 'off_peak':dict(zip(keys,[.007,.22,.66]))}}
    usage=dict(zip(keys,[0,1000000,1000000]));usage.update(prompt_tokens=1000000,total_tokens=2000000)
    record={'request_sha256':'same-request','request':{'model':'fixture'},'events':[{'status':'response','usage':usage,
        'started_unix_ns':int(datetime.fromisoformat('2026-09-10T03:00:00+00:00').timestamp()*1e9),'seconds':1}]}
    audit.save(tmp_path/'old/sessions/q/final.json',record)
    shutil.copytree(tmp_path/'old',tmp_path/'new')
    seen=set();first=stage(tmp_path/'old',spec,seen);second=stage(tmp_path/'new',spec,seen)
    assert first['priced_attempts']==1 and second['priced_attempts']==0
    assert second['duplicate_inherited_attempts_excluded']==1
    assert stage(tmp_path/'new',spec)['priced_attempts']==1


def test_other_model_attempt_is_explicitly_outside_flash_scope(tmp_path):
    import leaderboard_audit as audit
    keys=['prompt_cache_hit_tokens','prompt_cache_miss_tokens','completion_tokens']
    spec={'model':'deepseek-flash','effective_utc':'2026-08-16T16:00:00+00:00',
        'usd_per_million':{'peak':dict(zip(keys,[.014,.44,1.32])), 'off_peak':dict(zip(keys,[.007,.22,.66]))}}
    usage=dict(zip(keys,[0,100,20]));usage.update(prompt_tokens=100,total_tokens=120)
    record={'request_sha256':'historical-request','request':{'model':'another-model'},'events':[{'status':'response','usage':usage,
        'started_unix_ns':int(datetime.fromisoformat('2026-09-10T03:00:00+00:00').timestamp()*1e9),'seconds':1}]}
    audit.save(tmp_path/'construction/sessions/q/final.json',record)
    result=stage(tmp_path/'construction',spec)
    assert result['priced_attempts']==0
    assert result['unpriced_reason_counts']=={'model_outside_flash_scope':1}
    assert result['unpriced_attempt_models']=={'another-model':1}


def test_main_deduplicates_review_recovery_attempts(tmp_path):
    import leaderboard_audit as audit
    import shutil
    root=tmp_path/'leaderboard';(root/'runs').mkdir(parents=True);(root/'reviews').mkdir()
    keys=['prompt_cache_hit_tokens','prompt_cache_miss_tokens','completion_tokens']
    spec={'model':'deepseek-flash','effective_utc':'2026-08-16T16:00:00+00:00',
        'usd_per_million':{'peak':dict(zip(keys,[.014,.44,1.32])), 'off_peak':dict(zip(keys,[.007,.22,.66]))}}
    prices=tmp_path/'prices.json';audit.save(prices,spec)
    usage=dict(zip(keys,[0,100,20]));usage.update(prompt_tokens=100,total_tokens=120)
    record={'request_sha256':'same-review','request':{'model':'deepseek-flash'},'events':[{'status':'response','usage':usage,
        'started_unix_ns':int(datetime.fromisoformat('2026-09-10T03:00:00+00:00').timestamp()*1e9),'seconds':1}]}
    audit.save(root/'reviews/original/sessions/q/review-1.json',record)
    shutil.copytree(root/'reviews/original',root/'reviews/recovery')
    output=tmp_path/'cost.json'
    subprocess.run([sys.executable,str(SCRIPT),'--root',str(root),'--prices',str(prices),'--output',str(output)],check=True)
    result=json.loads(output.read_text())
    assert result['unique_review_attempts']['priced_attempts']==1
    assert result['unique_review_attempts']['reported_usage']['total_tokens']==120
    assert result['unique_review_attempts']['inherited_duplicates_excluded']==1
