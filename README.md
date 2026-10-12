# PrincipiaBlastFoam-DSH

PrincipiaBlastFoam-DSH 是一个独立的 DeepSeek Harness 应用，通过自然语言完成 blastFoam/OpenFOAM 物理分析、算例配置、求解执行、后处理和质量审查。

业务源码由本仓库管理；上游 DeepSeek Harness 检出目录只是可替换的宿主运行时：

```text
DeepSeek Harness profile
  -> principia-blastfoam-dsh-bundle
     -> 工作流策略与角色专属 subagent 工具
     -> @deepseek-ai/dsh-mcp-client
        -> Python Principia 检索与领域服务
  -> 项目级 .dsh/skills
```

## 共享研究设计

研究定位与章节边界统一引用 [共享设计入口](../graduation-research/README.md)和[总体设计](../graduation-research/OVERVIEW.md)。本项目分别对应[第2章检索](../graduation-research/chapters/chapter02.md)、[第3章多智能体执行](../graduation-research/chapters/chapter03.md)和[第4章独立单agent RSI](../graduation-research/chapters/chapter04.md)。共享设计说明研究目标，本项目维护源码、配置与详细实施计划，实验归档维护冻结协议和证据；当前实现状态须依据代码和验证记录核验。

## 知识图谱与检索定位

第2章维护实现位于 `experiments/retrieval_method/`，实验统一在外部 `graduation-experiment-results/chapter2_retrieval/`。题集入口为 `datasets/natural_navigation_qa/`；最新论文结果为 `aliyun_8b_cross_source_v1/`，使用离线 `deepseek-flash` 与在线 `qwen3-8b`。该正式实验独立冻结44事实组合族/132题，不与公共题集50族/300题混算。留出集不锁定，gold仅供评测，不进入生产检索或回答。

自研最终方法只持久化图谱与构图清单，读取原始权威文件核验；BM25/E5为隔离对照，Graphify `.txt`仅为可逆摄取适配。图关系表示文档/配置支持，不能直接声称物理运行条件已满足。最新实验的引用非劣效未获支持，同8B评分与AI复核仍有局限。实验适配器中的方法与生产MCP的接入状态须分别验证，不能因为论文成绩就假定线上集成完成。

## 论文与第4章方向

本项目是当前唯一在开发的PrincipiaBlastFoam多智能体应用，后续第3、4章正文和实验基于DSH。论文直接在同级 `graduation-manuscript/` 以LaTeX维护，所有最终图件在其 `assets/`。

第4章独立研究单agent递归自改进（RSI），仅使用DSH框架，不继承第3章多角色系统。基线为冻结初始agent，对照为一次性自改进与多轮递归自改进；底层模型、工具权限和公共评分固定。设计、消融和实现顺序见 [DSH自进化计划](experiments/self_evolution/PLAN.md)。目前只有设计，没有DSH自进化正式收益结果；历史框架结果保留原身份。

## 当前实现

- 7 个项目级 Skill，覆盖总编排、知识检索和 5 个有序工作阶段。
- 1 个可安装的 bundle，挂载稳定的工作流/产物策略，并通过 DSH 官方进程内 `spawn` provider 提供 5 个专职 subagent。
- 1 个基于 stdio 的 Python MCP 服务，向 DSH 暴露 17 个工具，工具名格式为 `mcp__principia_retrieval__<tool>`。
- `compatibility/` 保存精确的上游兼容版本、验收门槛和验证证据。

工作流顺序如下：

```text
物理分析 -> 算例配置 -> 求解执行 -> 后处理 -> 独立审查
```

存在依赖关系的阶段不得并行；同一阶段内相互独立的证据检索可以并行。

## 快速开始

推荐把宿主、运行状态和业务源码分开存放：

```text
<workspace>/deepseek-harness                        可替换的上游 DSH 宿主
<workspace>/dsh-home                               机器本地 DSH profile
<workspace>/graduation-projects/PrincipiaBlastFoam-DSH
                                                   受 Git 管理的业务应用
```

在已经安装本项目包装命令的机器上启动 Web 模式：

```bash
cd "$PRINCIPIA_PROJECT_ROOT"
principia-dsh --profile web
```

无界面任务可在 `--profile headless` 后追加任务文本。包装命令只把机器本地 API Key 注入子进程，不会把凭据复制到本仓库或 DSH profile。

本项目默认执行真实 solver。只做检索、配置或 CI 检查时，必须显式关闭：

```bash
ENABLE_EXECUTION=false REQUIRE_EXECUTION=false \
  principia-dsh --profile headless "检查算例配置，不运行求解器"
```

## 重建开发环境

创建 Python 环境：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
```

执行真实求解时，应在宿主环境设置 `OPENFOAM_BASHRC` 和 `BLASTFOAM_BASHRC`，指向该机器上的实际环境脚本。仓库不提供机器特定的绝对路径默认值。如果 MCP 进程已经继承完整的 OpenFOAM 环境，可以留空；预检会明确记录其正在依赖继承的 `PATH`。显式配置但文件不存在或不可读时，执行会被阻断。

跟踪模板中的 `ENABLE_EXECUTION` 和 `REQUIRE_EXECUTION` 默认为 `true`；显式设为 `false` 是配置检查和紧急停用方式。DSH 以 root 启动时，还应设置非特权的 `OPENFOAM_EXECUTION_USER`。

安装并检查 bundle：

```bash
npm --prefix packages/principia-dsh-bundle install
npm --prefix packages/principia-dsh-bundle run check
```

导出 `PRINCIPIA_PROJECT_ROOT` 和 `PRINCIPIA_PYTHON` 后，把 bundle 安装到 DSH profile，并在启动前检查合成配置树。具体命令见 [DSH 部署说明](deployment/dsh/README.md)，升级门槛见 [兼容性验收矩阵](compatibility/acceptance-matrix.md)。

## 评测

- [第 3 章端到端适配器](experiments/end2end/README.md)：兼容已有黑盒评分器。
- [批量评测指南](experiments/BATCH_EVALUATION.md)：介绍分层评测、用例筛选、分片并行、A/B 对照、结果归档和恢复策略。

适配器的 `--dry-run` 只验证用例选择、命令和结果结构，不启动 DSH 或 solver；正常 benchmark 默认执行真实求解。

## 仓库边界

不得把业务代码写入上游 DeepSeek Harness 检出目录，也不得把实时 DSH profile 提交到 Git。本仓库只提交 bundle 源码与构建输入、Skills、MCP/领域代码、测试和配置模板。凭据、机器路径、生成算例、运行日志与实验结果保存在外部运行环境或毕业实验归档目录。

DeepSeek Harness 当前仍处于预稳定阶段。`compatibility/dsh-version.json` 中的 commit 只代表已经验证的基线，不代表对任意新版本的兼容承诺。
