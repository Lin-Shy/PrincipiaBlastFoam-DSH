#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
project_root=${1:-$(cd -- "$script_dir/../../.." && pwd)}
cd "$project_root"

required=(
  graduation-experiment-results/chapter2_retrieval/leaderboard/ablation-flash-gate-v11/state.json
  graduation-experiment-results/chapter2_retrieval/leaderboard/runs/candidate_ablation_flash_v1/protocol.json
  graduation-experiment-results/chapter2_retrieval/leaderboard/final-method-selection-preregistration-v1.json
  graduation-experiment-results/chapter2_retrieval/leaderboard/runs/current_methods_flash_v11/protocol.json
  graduation-experiment-results/chapter2_retrieval/leaderboard/baseline-flash-followup-v11/quality.json
  graduation-experiment-results/chapter2_retrieval/leaderboard/baseline-flash-followup-v11/cost-and-grid.json
  graduation-experiment-results/chapter2_retrieval/leaderboard/runs/candidate_flash_v14/protocol.json
  graduation-experiment-results/chapter2_retrieval/leaderboard/candidate-flash-followup-v11/candidate-quality.json
  graduation-experiment-results/chapter2_retrieval/leaderboard/candidate-flash-followup-v11/candidate-cost-and-grid.json
  graduation-experiment-results/chapter2_retrieval/task_navigation_v1/dataset/v1_1/frozen/manifest.json
  /data/deepseek-api.txt
)
for path in "${required[@]}"; do
  test -f "$path" || { echo "missing required input: $path" >&2; exit 2; }
done

exec graduation-experiment-results/chapter2_retrieval/leaderboard/candidate/runtime/bin/python \
  PrincipiaBlastFoam-DSH/experiments/retrieval_method/final_evaluation_gate.py \
  --ablation-gate graduation-experiment-results/chapter2_retrieval/leaderboard/ablation-flash-gate-v11 \
  --ablation-run graduation-experiment-results/chapter2_retrieval/leaderboard/runs/candidate_ablation_flash_v1 \
  --ablation-analysis graduation-experiment-results/chapter2_retrieval/leaderboard/candidate-ablation-flash-analysis-v1 \
  --selection-registration graduation-experiment-results/chapter2_retrieval/leaderboard/final-method-selection-preregistration-v1.json \
  --baseline-run graduation-experiment-results/chapter2_retrieval/leaderboard/runs/current_methods_flash_v11 \
  --baseline-quality graduation-experiment-results/chapter2_retrieval/leaderboard/baseline-flash-followup-v11/quality.json \
  --baseline-cost graduation-experiment-results/chapter2_retrieval/leaderboard/baseline-flash-followup-v11/cost-and-grid.json \
  --candidate-run graduation-experiment-results/chapter2_retrieval/leaderboard/runs/candidate_flash_v14 \
  --candidate-quality graduation-experiment-results/chapter2_retrieval/leaderboard/candidate-flash-followup-v11/candidate-quality.json \
  --candidate-cost graduation-experiment-results/chapter2_retrieval/leaderboard/candidate-flash-followup-v11/candidate-cost-and-grid.json \
  --dataset graduation-experiment-results/chapter2_retrieval/task_navigation_v1/dataset/v1_1/frozen \
  --baseline-python graduation-experiment-results/chapter2_retrieval/graphify_baseline_v1/runtime/bin/python \
  --candidate-python graduation-experiment-results/chapter2_retrieval/leaderboard/candidate/runtime/bin/python \
  --review-python graduation-experiment-results/chapter2_retrieval/graphify_baseline_v1/runtime/bin/python \
  --key-file /data/deepseek-api.txt \
  --output graduation-experiment-results/chapter2_retrieval/leaderboard/final-evaluation-flash-v1
