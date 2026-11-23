"""Shared paths and helpers retained for the completed local B11 evaluation."""
import hashlib
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import launch_attempt
from prepare_system_comparison import WS, common_environment, write

base = WS/'graduation-experiment-results/chapter3_end_to_end_evaluation/dsh'
batch = base/'development_batch18_20261118'
pair = base/'B11_dispatch_review_20261118/live'
arms = ('general','professional')
runtime = WS/'.chapter3-runtime/stage-20261117/dsh'
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == '__main__':
    raise SystemExit('B11 has a verified result for each system. See development_batch18_20261118/STATUS.md.')
