"""第二轮路径、序列化与不可覆盖文件；生产模块不读取评分标注。"""
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
WORKSPACE = PROJECT.parent
LEGACY = PROJECT / 'experiments/retrieval_method'
ARCHIVE = WORKSPACE / 'graduation-experiment-results/chapter2_retrieval/round2_20261020'
RESOURCES = ARCHIVE.parent / 'resources'
CURRENT = ARCHIVE.parent / 'current'
HISTORICAL = CURRENT / 'model14b_200_20261019_002'
DATASET = WORKSPACE / 'graduation-datasets/chapter02_knowledge_qa/formal_v2_200'
QUESTIONS = DATASET / 'model/questions.json'
GRAPH = CURRENT / 'revision_200_20261019_002/graphs/selected.json'
sys.path[:0] = [str(LEGACY), str(PROJECT / 'src')]

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def wire(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as f:
        f.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')

def public_questions():
    questions = read(QUESTIONS)
    if len(questions) != 200 or len({q['id'] for q in questions}) != 200 or any(set(q) != {'id', 'question'} for q in questions):
        raise ValueError('exact public 200 id/question bank required')
    return questions
