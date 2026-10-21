from pathlib import Path
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from common import *


def test_current_policy_and_actual_status_are_consistent():
    for rel in ['AGENTS.md','graduation-datasets/AGENTS.md',
                'graduation-experiment-results/chapter2_retrieval/AGENTS.md',
                'PrincipiaBlastFoam-DSH/AGENTS.md',
                'graduation-thesis-materials/graduation-manuscript/AGENTS.md']:
        text=(WORKSPACE/rel).read_text(encoding='utf-8')
        assert '4600'in text and '九种方法'in text and 'pending'in text
        assert '从未参与调参的未见留出集'in text
        assert '全部200题保留分母'not in text
    p=read(CURRENT/'publication-plan.json')
    assert p['comparison_sessions']==4600 and p['main_methods']==9 and p['ablations']==4
    assert p['human_judge_validation']==p['graph_quality_validation']=='pending'


def test_active_navigation_links_exist():
    files=[CURRENT/'README.md',CURRENT/'HUMAN_REVIEW.md',
           WORKSPACE/'graduation-thesis-materials/graduation-manuscript/README.md',
           WORKSPACE/'graduation-thesis-materials/graduation-manuscript/CHAPTER2_SOURCES.md']
    for file in files:
        for target in re.findall(r'\]\(([^)]+)\)',file.read_text(encoding='utf-8')):
            if '://'in target or target.startswith('#'):continue
            target=target.split('#',1)[0]
            if target=='unified-maintenance.md':continue  # written after completed test suite
            assert (file.parent/target).exists(),(str(file),target)


def test_old_plot_entry_points_delegate_to_one_current_publisher():
    root=WORKSPACE/'graduation-thesis-materials/graduation-visualization/chapter_02_knowledge_graph_retrieval'
    for name in ['build_split_results.py','build_round2_split_results.py']:
        text=(root/name).read_text(encoding='utf-8')
        assert 'from build_unified_results import main'in text
        assert 'round2/overall.tex'not in text
