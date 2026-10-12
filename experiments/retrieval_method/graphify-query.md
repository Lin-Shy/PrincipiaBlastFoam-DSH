# Graphify 查询链路消融

此实现是研究侧适配器，不修改 Graphify 安装文件、冻结图或生产 MCP 默认入口。结果写入外部毕业实验归档。

## 实现

- `graphify_query_variants.py`：四种状态 original、compatible、atomic、combined。沿用固定 Graphify 的评分、种子和 BFS，分别修改自动过滤兼容性及完整关系打包。
- `graphify_query_replay.py`：冻结历史查询、代码、两图和路径映射；执行门禁、详细计量及独立进程比较。无 LLM 和凭据参数，不使用 gold 参与查询。
- `tests/test_graphify_query_variants.py`、`tests/test_graphify_query_replay.py`：预算、来源、端点完整性、过滤单因素、重放及冻结防护。

从项目根目录使用已核验的 Graphify 隔离 Python；不向项目或全局 Python 安装新依赖。

```bash
PYTHONHASHSEED=0 /path/to/graphify/python -m unittest discover -s tests -p 'test_graphify_query*.py' -v
PYTHONHASHSEED=0 /path/to/graphify/python -m experiments.retrieval_method.graphify_query_replay prepare --source-run /path/to/graphify_qa_v3 --run /path/to/fresh-experiment --plan /path/to/preregistered-plan.md
PYTHONHASHSEED=0 /path/to/graphify/python /path/to/fresh-experiment/code/replay.py run --run /path/to/fresh-experiment --output /path/to/fresh-experiment/runs/001
PYTHONHASHSEED=0 /path/to/graphify/python /path/to/fresh-experiment/code/replay.py run --run /path/to/fresh-experiment --output /path/to/fresh-experiment/runs/002
PYTHONHASHSEED=0 /path/to/graphify/python /path/to/fresh-experiment/code/replay.py compare --left /path/to/fresh-experiment/runs/001 --right /path/to/fresh-experiment/runs/002 --output /path/to/fresh-experiment/repeat-comparison.json
```

输入与输出目录均须明确指定。prepare/run 拒绝覆盖已有目录，结果写入拒绝覆盖已有文件。每次 run 必须从冻结的 `code/replay.py` 执行，使用原协议的解释器身份和 `PYTHONHASHSEED=0`。

## 解释边界

重放仅对照历史已经生成的查询，不模拟新返回导致的后续 agent 行为，不能复用旧答案评估新策略。候选和关系展示完整，不等于语义正确或必要证据完整。来源路径统计也不等于实际读取了原文。

公开 cap 与 native 正文预算均保留。完整关系打包可能减少来源覆盖，应同时看新增和丢失路径，不以边数自动选优。真实 QA 需要新冻结协议、统一的新开发题集和新无图回答，不能与本离线诊断混计。
