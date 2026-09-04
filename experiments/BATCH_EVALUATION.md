# PrincipiaBlastFoam-DSH 批量评测指南

本文说明如何批量运行 DSH 多智能体工作流、真实 OpenFOAM 求解和第 3 章黑盒评分。评测产物应写入外部实验归档目录，不提交到业务源码仓库。

## 推荐的四级评测漏斗

不要直接对全部用例执行高成本真实求解。推荐按以下顺序逐级放行：

| 级别 | 运行内容 | 主要目的 | Solver |
|---|---|---|---|
| L0 | Python、bundle、MCP schema 和 profile 合成测试 | 发现代码、权限与配置错误 | 不启动 |
| L1 | 全量 benchmark `--dry-run` | 验证用例选择、命令构造和报告契约 | 不启动 |
| L2 | DSH 多智能体批量运行并加 `--disable-execution` | 评估检索、教程选择、配置方案和角色协作 | 明确禁用 |
| L3 | 代表性短时算例真实求解 | 验证执行链、日志、时间目录和产物契约 | 启动，严格限时 |
| L4 | 完整 benchmark 或代表性全时长算例 | 形成论文最终结果与综合统计 | 启动 |

只有前一级达到预设门槛后才进入下一级。例如，L2 可以要求教程选择正确率和配置完整率达到阈值；L3 必须要求无致命日志、存在正常 `End`、时间目录有效且 `artifact_contract.json` 为 `ok: true`。

## 真实求解前的统一环境

L3/L4 不应依赖交互式 shell 的偶然状态。批量调度进程至少要显式提供以下机器本地配置：

```bash
export PRINCIPIA_DSH_API_KEY_FILE="<本机密钥文件>"
export OPENFOAM_BASHRC="<OpenFOAM 环境脚本>"
export BLASTFOAM_BASHRC="<blastFoam 环境脚本>"
export OPENFOAM_EXECUTION_USER="<非特权求解用户>"
export OPENFOAM_CHOWN_CASE=true
```

启动批量任务前先对一个隔离短算例执行 `execution_preflight`。不得把 `ALLOW_ROOT_OPENFOAM=true` 当作方便的默认配置，也不得直接运行或改变原始教程目录的所有权。

## 方法一：使用适配器顺序批量运行

`experiments/end2end/run_agent_benchmark.py` 会在一个进程内依次运行所选用例。该方法状态最简单，适合小批量、基线验证和生成可直接评分的统一报告。

```bash
export PRINCIPIA_DSH_API_KEY_FILE="<本机密钥文件>"

.venv/bin/python experiments/end2end/run_agent_benchmark.py \
  --cases-file "<benchmark.json>" \
  --output-root "<实验归档目录>/sequential-baseline" \
  --workflow-timeout 900
```

可用的筛选方式：

- `--limit N`：只运行前 N 个用例，适合快速检查。
- 重复使用 `--case-id <id>`：运行指定用例集合。
- `--disable-execution`：运行 DSH 工作流但禁止 solver。
- `--dry-run`：只验证命令和报告结构，完全不启动 DSH。
- `--patch <path>`：叠加实验配置，用于 A/B 或消融实验。

适配器每完成一个用例都会更新 `benchmark_partial.json`，全部完成后写入 `benchmark_report.json`。

## 方法二：复用第 3 章黑盒评分器

既有第 3 章脚本可以负责数据集筛选、工作流启动和评分，本项目适配器只承担 DSH 兼容层。该方法最适合生成论文第 3 章正式统计。

```bash
export PRINCIPIA_DSH_API_KEY_FILE="<本机密钥文件>"

<评测环境的 Python> \
  <第3章评测目录>/scripts/run_chapter3_full_evaluation.py \
  --execute-workflow \
  --project-root "$PRINCIPIA_PROJECT_ROOT" \
  --python "$PRINCIPIA_PROJECT_ROOT/.venv/bin/python" \
  --limit 12 \
  --workflow-timeout 900 \
  --benchmark-runner-timeout 3600
```

教程修改评测还可以使用 `run_chapter3_tutorial_modification_evaluation.py`，按 `static`、`syntax`、`short_run`、`representative_full` 或 `all` 分层。已经存在原始运行结果时，优先使用它的 `--score-existing` 重新评分，避免重复消耗 API 和计算资源。

## 方法三：在外层进行分片并行

适配器内部有意保持顺序执行。大批量任务应在进程外按 case ID 分片，每个 worker 使用独立输出目录；建议同时使用独立 DSH profile，避免会话状态相互影响。

```bash
export PRINCIPIA_DSH_API_KEY_FILE="<本机密钥文件>"

.venv/bin/python experiments/end2end/run_agent_benchmark.py \
  --cases-file "<benchmark.json>" \
  --case-id case_a --case-id case_b \
  --dsh-profile headless-worker-01 \
  --output-root "<实验归档目录>/shard-01" &

.venv/bin/python experiments/end2end/run_agent_benchmark.py \
  --cases-file "<benchmark.json>" \
  --case-id case_c --case-id case_d \
  --dsh-profile headless-worker-02 \
  --output-root "<实验归档目录>/shard-02" &

wait
```

各 worker profile 都要预先安装同一版本的 bundle，并通过 `--dump-config`。不要让两个 worker 写入同一个 `output-root` 或算例目录。

真实 solver 并行度应按 CPU、内存和磁盘能力单独设定，不能只根据 API 并发上限决定。每个 Allrun 可能继续启动 MPI 进程，因此“worker 数 × 每个算例 MPI 核数”不得超过计算资源预算。小型串行算例可以从 1～2 个 worker 开始，观察峰值内存和磁盘增长后再增加。

## 方法四：A/B、消融与重复采样

可以为不同实验组准备独立 DSH profile 或 patch，例如：

- 完整系统：Skills + subagents + MCP；
- 去掉领域 Skill；
- 去掉 MCP 知识库，只保留通用工具；
- 单智能体基线；
- 不同 DSH 版本或不同模型配置。

每个实验组必须固定以下信息：

- Git commit、DSH commit、bundle 版本和 profile 名称；
- benchmark 数据版本与 case ID 列表；
- 模型、温度等推理配置；
- `ENABLE_EXECUTION`、超时、执行用户和 OpenFOAM 环境；
- 重复次数、随机种子（如果上游支持）和开始时间；
- 独立输出根目录。

LLM 工作流具有随机性。正式统计建议每个用例重复 3～5 次，同时报告均值、标准差、成功次数和失败类型，不能只挑选最好的一次。

## 方法五：使用作业调度系统

用例进一步扩大时，可以把“一个 case 或一个小分片”作为一个调度单元：

- 单机：systemd transient service、GNU Parallel 或受控进程池；
- 服务器/集群：Slurm job array；
- 长期平台：Redis/RQ、Celery 或自建任务队列；
- CI：只运行 L0、L1 和 `--disable-execution` 的轻量 L2；真实 solver 使用自托管 runner。

调度层应负责最大并发数、超时、重试、取消、磁盘配额和失败告警。DSH subagent 的并行能力用于单个工作流内部的独立证据收集，不应代替跨用例调度器。

## 结果结构与汇总指标

每个运行目录至少保留：

- `benchmark_report.json` 和运行中的 `benchmark_partial.json`；
- 每个 case 的 DSH 日志、solver 日志和标准七项产物；
- benchmark 数据快照或其 commit/hash；
- DSH/项目 Git commit、profile 和关键环境开关；
- 失败时的原始输出，不能只保留汇总分数。

建议统计以下指标：

- 任务通过率和各阶段通过率；
- 教程选择准确率；
- 字典/量纲/边界条件正确率；
- solver 启动率、正常结束率、超时率和致命错误率；
- 七项产物契约通过率；
- 后处理目标覆盖率；
- 单用例时延、token 用量、API 成本、CPU 时间和峰值磁盘占用；
- 按检索、物理、配置、执行、后处理、审查分类的失败分布。

## 断点恢复与重试

当前适配器不在原运行目录内自动断点续跑。中断后应读取 `benchmark_partial.json`，提取未完成或允许重试的 case ID，在新的输出根目录启动补跑，并在外层汇总时保留原运行 ID 和重试关系。

只重试基础设施型失败，例如 API 临时错误、节点重启或外部超时。物理模型错误、算例配置错误、solver 发散和产物验证失败属于系统能力结果，不应通过无限重试掩盖。

## 推荐起步方案

第一次批量评测可以采用以下规模：

1. 对全部 benchmark 执行 L1 `--dry-run`。
2. 对全部用例执行 L2 `--disable-execution`，检查教程选择和配置质量。
3. 选择约 12 个代表性短时用例执行 L3，先使用 1 个 solver worker。
4. L3 稳定后，再进行第 3 章完整评分或 A/B 消融，并逐步提高到 2～4 个 worker。

该方案能把大多数提示词、路由、权限和产物问题挡在真实 CFD 求解之前，同时保留最终端到端真实性。
