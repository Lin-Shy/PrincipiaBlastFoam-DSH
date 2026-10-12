import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
import leaderboard_audit as audit
from leaderboard_report import render


def test_incomplete_source_review_cannot_publish_quality_ranking(tmp_path):
    run=tmp_path/'run';audit.save(run/'protocol.json',{'files':{}})
    report=tmp_path/'quality.json';audit.save(report,{'protocol_sha256':audit.sha(run/'protocol.json'),
        'all_arms_rankable':False,'replay_and_budget_admission':{'passed':True}})
    output=tmp_path/'ranking.md'
    with pytest.raises(ValueError,match='do not publish'):
        render(report,run,{},output)
    assert not output.exists()
