"""Synthetic plotting only; no scientific results or model calls."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
pytest.importorskip('matplotlib')
from qa_outputs import figures,MAIN,ABS

def test_six_standalone_png_pdf_pairs(tmp_path):
    arms=list(dict.fromkeys(MAIN+ABS));value=dict(score_lower=.4,score_upper=.6,necessary_evidence_recall=.7)
    effect=dict(comparison='graph vs bm25',difference_lower=-.1,difference_upper=.1,uncertainty_envelope_ci95=[-.2,.2])
    summary=dict(by_arm={a:value for a in arms},by_type={a:{t:value for t in ['S0','S1','M0','M1']}for a in arms},comparisons={'main':[effect]})
    rows=[dict(arm=a,id=str(i),necessary_evidence_recall=e,score_lower=.4,score_upper=.6)for a in arms for i,e in enumerate([0,.25,.5,1])]
    figures(tmp_path,summary,rows)
    assert len(list(tmp_path.glob('*.png')))==len(list(tmp_path.glob('*.pdf')))==6
    assert all(p.stat().st_size>1000 for p in tmp_path.iterdir())
