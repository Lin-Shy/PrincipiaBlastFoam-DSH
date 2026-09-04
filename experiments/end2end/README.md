# 第 3 章 DSH benchmark 适配器

`run_agent_benchmark.py` 是既有第 3 章评测框架与本 DeepSeek Harness 应用之间的兼容边界。外层评分脚本不需要实现 DSH 专用解析器：把它的 `--project-root` 指向本仓库，把 `--python` 指向本项目虚拟环境即可。

适配器兼容两套第 3 章启动器使用的旧参数。每个用例启动一个 DSH headless 任务，并写出既有结果契约：

```text
<output-root>/run_<UTC 时间戳>/
  benchmark_partial.json
  benchmark_report.json
  logs/<case-id>.log
  cases/<case-id>/...
```

## 安全 dry-run

下面的命令验证用例选择、DSH 命令构造和结果结构，不调用 DSH、不创建算例，也不启动 OpenFOAM：

```bash
.venv/bin/python experiments/end2end/run_agent_benchmark.py \
  --cases-file ../graduation-experiment-results/chapter3_end_to_end_evaluation/data/e2e_agent_benchmark_cases.json \
  --output-root /tmp/principia-dsh-benchmark-dry-run \
  --limit 1 \
  --dry-run
```

## 接入既有第 3 章评分器

调用旧评测器时，启用其工作流执行开关并选择本仓库：

```bash
<workspace>/conda-envs/principia-blastfoam/bin/python \
  ../graduation-experiment-results/chapter3_end_to_end_evaluation/scripts/run_chapter3_tutorial_modification_evaluation.py \
  --execute-workflow \
  --project-root . \
  --python .venv/bin/python
```

需要更完整的批量运行、分片并行、A/B 对照和归档方法时，参见[批量评测指南](../BATCH_EVALUATION.md)。

## 运行时与凭据

默认情况下，适配器根据本仓库的工作区根目录推导同级 `deepseek-harness` 检出目录和 `dsh-home`，profile 使用 `headless`。可通过 `--dsh-bin`、`--dsh-home` 和 `--dsh-profile` 覆盖；另行准备的 bundle patch 可以重复传入 `--patch`。

凭据可以由进程环境提供，也可以使用 `--api-key-file` 或 `PRINCIPIA_DSH_API_KEY_FILE`。文件内容只会以 `DEEPSEEK_API_KEY` 注入 DSH 子进程，不会写入 benchmark 报告；报告中的命令也不会包含密钥或完整提示词。

真实 DSH benchmark 默认执行 solver，适配器会设置 `ENABLE_EXECUTION=true` 和 `REQUIRE_EXECUTION=true`，因此旧版第 3 章外层启动器不需要新增参数。批量启动前必须检查 OpenFOAM 环境、算例输出根目录、超时和清理策略。

配置开发或 CI 可使用 `--disable-execution`。为保持兼容，`--enable-execution` 仍可显式传入。`--dry-run` 无论执行开关为何值都只构造命令和结果契约，绝不会启动 DSH 或 OpenFOAM。

## 当前边界

- 适配器内部按用例顺序执行，不在单进程中并发。
- `benchmark_partial.json` 会在每个用例后更新，便于观察中间状态；跨进程断点续跑与结果合并应由外层批量调度器负责。
- `--cleanup-final` 只记录清理意图；为保留评分证据，适配器本身不删除算例，实验活动结束后由归档流程统一处理。
