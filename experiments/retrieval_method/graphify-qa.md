# Graphify 基线的统一检索问答评测

`graphify_qa.py` 使用真实 Graphify 基线图，不调用自研图构建器。构图与来源身份见 `graphify-baseline.md`。全部实验输出留在外部毕业实验归档，不进入源码仓库。

公共输入为相同原始文件和只读工具。原生图、文本扩展名适配图各有可选图/优先图两种策略，共用一个无图对照，形成五臂。图工具调用原生 MCP 查询核心，不为问题补图，不直接把图标签记成已读原文。适配只还原图导航返回的来源路径。

## 运行

为 `GRAPHIFY_PYTHON`、`QA_RUN`、`GRAPHIFY_ARCHIVE`、`FROZEN_DATASET`、`DEEPSEEK_KEY_FILE` 指定外部实验路径。凭据文件仅由进程读取；不要把密钥放在命令行值、文档或环境转储中。

```bash
PYTHONHASHSEED=0 "$GRAPHIFY_PYTHON" experiments/retrieval_method/graphify_qa.py prepare \
  --run "$QA_RUN" --archive "$GRAPHIFY_ARCHIVE" --dataset "$FROZEN_DATASET"
PYTHONHASHSEED=0 "$GRAPHIFY_PYTHON" experiments/retrieval_method/graphify_qa_preflight.py --run "$QA_RUN"
PYTHONHASHSEED=0 "$GRAPHIFY_PYTHON" "$QA_RUN/runner.py" run \
  --run "$QA_RUN" --key-file "$DEEPSEEK_KEY_FILE" --workers 3 --only Q001-p1 Q007-p1 Q013-p1
PYTHONHASHSEED=0 "$GRAPHIFY_PYTHON" "$QA_RUN/runner.py" replay \
  --run "$QA_RUN" --workers 3 --only Q001-p1 Q007-p1 Q013-p1
```

每条命令必须分别检查退出码和产物，再进入下一阶段；不能在无条件串行调度中忽略回放失败。全量运行省略 `--only`，已完成结果会复用，传输失败只允许相同请求恢复。回放不带 key，不向模型发送新请求。

冻结后不修改被测文件、图、题目或评分器，改动使用新目录。`prepare` 拒绝覆盖已有实验。运行期锁避免同一个目录被两个 runner 同时消费；所有 HTTP 尝试先保存状态，中断未知用量与时长不得补零。

## 可复现性检查

首轮真实试验暴露原生 BFS 集合遍历的边顺序随进程哈希种子改变。在公共返回预算下，不仅顺序，最终保留的边集合也可能不同。保留原始图和该失败证据，后续对全部五臂统一固定 `PYTHONHASHSEED=0`，并校验解释器版本和实际 hash probe；这不是修改 Graphify 查询算法。

`graphify_qa_diagnose.py` 离线对照单场已发生查询；`graphify_qa_repro_check.py` 对已完成场次中的全部图查询，在三个 seed=0 进程及一个 seed=1 进程中比较原生返回与预算裁剪结果。两者均零 LLM 调用。

## 评分与成本

`navigation_review.py` 生成来源审阅包并编译显式逐项审阅，不能按关键词或证据跨度自动判答对。审阅时记录同一研究 agent、非独立盲评的限制。使用 `graphify_qa_report.py --reviews-root ...` 汇总五臂，调用各实验冻结的计量/评分函数。

API usage、未知失败、重试、重复发送上下文、原文扫描、图属性读取、候选与邻接遍历、图/原文缓存初始化、延迟均分别保存。字符等价量存在重叠，不应相加冒充统一 token 成本；未知 API 用量非零缺失时只报告已知下界。原生报告中展示的简短返回量不能代替这些内部成本。

该离线实验不依赖已发布检索 MCP 索引。项目环境检查仍需另跑；旧索引或 MCP 故障应单独归档，不能借评测修补旧发布快照。
