# Chapter 3 DSH benchmark adapter

`run_agent_benchmark.py` is the compatibility boundary between the existing
Chapter 3 evaluation harness and this DeepSeek Harness application. The outer
evaluation scripts do not need a DSH-specific result parser: point their
`--project-root` at this repository and their `--python` at this project's
virtual environment.

The adapter accepts the legacy runner flags used by both Chapter 3 launchers,
starts one DSH headless task per case, and writes the established contract:

```text
<output-root>/run_<UTC timestamp>/
  benchmark_partial.json
  benchmark_report.json
  logs/<case-id>.log
  cases/<case-id>/...
```

## Safe dry run

This verifies case selection, DSH command construction, and result shape. It
does not invoke DSH, create a case, or start OpenFOAM:

```bash
.venv/bin/python experiments/end2end/run_agent_benchmark.py \
  --cases-file ../graduation-experiment-results/chapter3_end_to_end_evaluation/data/e2e_agent_benchmark_cases.json \
  --output-root /tmp/principia-dsh-benchmark-dry-run \
  --limit 1 \
  --dry-run
```

For integration through the existing Chapter 3 evaluator, add its workflow
execution flag and select this repository:

```bash
<workspace>/conda-envs/principia-blastfoam/bin/python \
  ../graduation-experiment-results/chapter3_end_to_end_evaluation/scripts/run_chapter3_tutorial_modification_evaluation.py \
  --execute-workflow \
  --project-root . \
  --python .venv/bin/python
```

## Runtime and credentials

By default the adapter derives the sibling `deepseek-harness` checkout and
`dsh-home` paths from this repository's workspace root; profile is `headless`. Override them with
`--dsh-bin`, `--dsh-home`, and `--dsh-profile`. A separately provisioned bundle
patch can be repeated with `--patch`.

Provide credentials in the process environment, or use `--api-key-file` (or
`PRINCIPIA_DSH_API_KEY_FILE`). The file content is injected only into the DSH
child process as `DEEPSEEK_API_KEY`; neither the key nor the prompt is stored in
the benchmark report or printed in its command field.

Solver execution is disabled by default even for a real DSH run. The adapter
sets both `ENABLE_EXECUTION=false` and `REQUIRE_EXECUTION=false`. A future
controlled solver campaign must opt in explicitly with `--enable-execution`,
after separately verifying OpenFOAM environment and cleanup policy. The current
Chapter 3 outer runner does not forward that new flag, so its DSH migration path
remains non-executing until the campaign launcher is intentionally updated.
