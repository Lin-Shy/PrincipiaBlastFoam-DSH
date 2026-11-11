# 第 3 章 DSH benchmark 适配器

## B01 2端到端开发入口

2026-11-02起使用`run_development_sample.py`接入[公开输入开发样题](../../../graduation-datasets/chapter03_simulation_tasks/benchmark/development_samples/b01_2_e2e_20261102/README.md)。该入口从空case与公开资料出发，不使用下方历史适配器的复制教程提示，也不加载Gold曲线或计算精度分数。条件、求解完成和交付由`check_development_delivery.py`独立核查；它不授予科学准确性通过结论。

模型通过[第3章独立配置](../../config/llm/chapter3/README.md)接入XCM，使用专用key。运行目录位于实验归档`development_samples/b01_2_dsh/`，包含公开输入散列、原生DSH会话、SSH回传结果与外部检查。`prepare`准备独立运行状态，`dump-config`不调用模型，`run`启动一次任务，`collect`回传并保留远端证据；需显式传入同一个`--run-dir`。同目录存在execution.json时禁止再次运行。

SSH运行保持已安装应用bundle的角色与有序阶段，但使用原生SSH文件和Bash工具，关闭Windows专用检索/执行MCP；阶段角色的工具白名单只在本次overlay中适配，不改全局bundle。`probe_ssh_runtime.mjs`可在不调用模型或求解器时检查Agent Host和公开任务可读性。SSH插件需要建立本地转发隧道，因此其`sshArgs`不能设置`ClearAllForwardings=yes`；独立上传/下载连接仍清除继承转发。

总工作流技能通过`skill-filesystem.bundledSkillDir`在本地加载，关闭默认技能根目录；不会上传项目技能或内部资料。`probe_local_workflow.mjs <application_skills目录>`使用拒绝所有路由文件访问的替身验证目录发现和正文加载。任务输入仅为样题`public/`的九个文件；应用另外上传`operator_tools/guarded_remote_job.py`，与题目资料分开记录哈希。实际模型看到的公开输入、流程规程及其哈希保存在每次运行的manifest中。

本次headless运行时没有独立`glob`、`grep`工具，overlay从专家白名单移除这两个未注册名称，否则`tools.restrict()`会直接拒绝委派。配置、执行和后处理角色通过原生`bash`完成搜索；物理分析和审查角色保留只读工具。机器上的Agent Host CLI可能自动下载新版本；运行前先用无模型SSH探针验证，必要时通过`--remote-code`指定已安装版本的启动脚本。磁盘不足时使用满足公开资源条件的独立目录，通过`--remote-root`显式记录，不能降低空间门槛。

物理分析和审查角色另有`principia_list_directory`，仅允许列出当前任务及两处OpenFOAM/blastFoam安装根目录，最多500条，不提供shell或写入能力。SSH manager同时显式登记安装目录路由；否则原生`read`对工作区外的Linux绝对路径可能回退到本地Windows。`probe_ssh_routing.mjs`使用真实manager/router，并拒绝本地后端，独立验证安装文档读取与任务目录列举。单一RemoteFs后端的探针不能替代这项整合检查。

模型异常时保留结果并报告，不修复求解器、不改物理条件来求通过。历史适配器与结果保持原身份。

2026-11-02补充应用执行看护：生产任务通过`guarded_remote_job.py start`后台启动，短请求读取同一个job的`status.json`；原始输出写入`process.log`，不向工具通道持续回传完整求解日志。worker与AHP/SSH会话解耦，持有单工作区执行锁，累计计入墙钟预算。实际施加单CPU亲和性、继承的每进程3GiB地址空间上限与512MiB单文件上限，并监控最小空闲空间和2GiB工作区存储额度。地址空间上限不是聚合cgroup RSS限制；目录存储额度为运行期间轮询检查。

遇非正温度、非有限值或致命错误，终止本次进程组并保留日志；模型异常会写入工作区账本，禁止再次启动。人工停止可在job目录创建`STOP`文件。`process_completed`仅代表进程正常退出，仍须独立验收条件、终止时间、场和交付物；失败报告及缺失产物清单不能替代完整成功交付。工具断开时不得推断后台任务已退出，也不得据此另起一份求解。

`probe_guarded_jobs.mjs`通过实际manager/AHP shell与文件系统进行无模型诊断，关闭连接后重新读取后台任务状态。断线存活、实际资源限制、超时、累计预算、异常停止和禁止重启的证据在[开发活动归档](../../../graduation-experiment-results/chapter3_end_to_end_evaluation/development_samples/b01_2_dsh/README.md)。这些检查没有启动blastFoam，不证明原通道中断根因已经修复，也不改变B01-2失败结论。新入口使用该看护器仍依赖Agent按规程调用；现有通用Bash工具不构成禁止绕过的强制沙箱，绕过时不能授予资源验收通过。

研究目标、章节关系与证据边界见[第3章共享设计](../../../graduation-thesis-materials/graduation-research/chapters/chapter03.md)。本目录维护DSH适配与运行方式，具体实验活动另行冻结协议并归档结果；历史框架分数不作为DSH结果。

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
