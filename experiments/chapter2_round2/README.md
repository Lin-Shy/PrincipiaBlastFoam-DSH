# 第2章第二轮实验

## 当前维护入口（2026-10-20）

九方法与四消融、E5/BGE统一由`current/results.json`管理；完整图/BM25只采用原运行，当前保留4200会话，历史执行4600。开发160/测试40实体分开，人评/图质量pending，论文旧表图/PDF尚待单结果同步。旧round2_20261020目录已整体迁入`current/provenance`并移除，固定查询6600份交付和2200份轨迹在`current/fixed-query`。日常维护使用`current/manage_results.py`，材料检索使用`current/storage.html`；下列为早期执行说明，不能覆盖当前口径。

### 迁移后的离线分析入口

冻结common.py及实现快照保留原字节，原来的直接执行命令记录当时路径。当前需要离线分析时，通过`current/tools/run_analysis.py <命令> -- <原参数>`显式适配位置，见[来源与维护说明](../../../graduation-experiment-results/chapter2_retrieval/current/PROVENANCE.md)。此入口不包含付费生成、评分或新检索；本次未执行分析或测试套件，也没有启动新实验。

## 早期执行说明（保留历史身份）

## 当前指令覆盖：取消新造题，采用原200题的160/40划分

新增40题与60题草稿及专属流程已清理；旧人审等待和280会话计划取消。研究者已明确更正未同步记录，原基础160题用于调参、原补充40题从未参与调参，作为未见留出测试。只引用原题ID与既有回答评分，不新增题目或调用。当前划分和统计位于split160_40_20261020，论文以测试40题为主、开发160题另列；以下为旧过程快照。既有1400会话付费评分已闭合，当前实体拆分不产生新调用。

## 实体划分维护

`split_existing200.py`按原ID汇总，`materialize_split.py`建立160/40题集与所有历史问答实体目录；旧holdout40/60构造与执行流程已删除。当前1400付费评分已闭合，无新增题目或付费调用。详见归档README。

源码与测试仅在本目录维护。当前结果实体统一在[current](../../../graduation-experiment-results/chapter2_retrieval/current/README.md)，固定查询原始交付、逐题评价与轨迹见[current/fixed-query](../../../graduation-experiment-results/chapter2_retrieval/current/fixed-query/README.md)；其余历史协议和审计均已迁入[current/provenance](../../../graduation-experiment-results/chapter2_retrieval/current/PROVENANCE.md)。冻结文件正文和哈希不改；下面旧执行命令采用当时路径，迁移映射见current/storage-migration.json及fixed-query/migration.json，本次不重新执行实验。

固定查询：原200题自然问题，2000/4000/6000实际JSON字符，10交付槽位，统一按原文行去重且不回填。新Embedding仅官方BGE-M3 Dense。完整图保持原字节与rank/read_native语义；A1独立关闭候选关系路径，A2保留完整组槽位只交付节点锚点交集。

从工作区根目录 PowerShell运行；正式输出目录拒绝覆盖，故不要重发同号运行。`$ch2py` 是已存在的CPU专用环境：

```powershell
$ch2py = 'PrincipiaBlastFoam-DSH/.local/knowledge-qa-venv/Scripts/python.exe'
$ch2src = 'PrincipiaBlastFoam-DSH/experiments/chapter2_round2'
python -X utf8 "$ch2src/audit.py" prepare
& $ch2py -X utf8 -m pytest "$ch2src/test_round2.py" "$ch2src/test_workflows.py" -o addopts= -q
python -X utf8 "$ch2src/download_bge.py"
& $ch2py -X utf8 "$ch2src/bge_m3_dense.py"
python -X utf8 "$ch2src/retrieval.py" freeze
& $ch2py -X utf8 "$ch2src/retrieval.py" run --method graph --run-id smoke_v1 --smoke
& $ch2py -X utf8 "$ch2src/retrieval.py" run --method graph --run-id fixed200_v1
```

其余方法独立进程同命令，method取`bm25,bge_m3,bm25_bge_m3,bm25_parent,no_traversal,anchor_only,e5,bm25_e5,no_cross,no_aliases`。所有方法必须先非正式英文语料问题冒烟；不是留出题。已有完整运行应读取回执而不重发；需复验时单独run-id保留原记录。

```powershell
python -X utf8 "$ch2src/evaluate.py" --run-id fixed200_v1 --output final_001
python -X utf8 "$ch2src/validate_traces.py" --run-id fixed200_v1 --output graph_trace_invariants.json
python -X utf8 "$ch2src/plot_results.py" --source final_001 --output final_001
python -X utf8 "$ch2src/cases.py" --evaluation final_001 --output cases_001
python -X utf8 "$ch2src/human_review.py" export
python -X utf8 "$ch2src/holdout_gate.py" template
python -X utf8 "$ch2src/costs.py"
python -X utf8 "$ch2src/audit.py" verify --output historical_preservation.json
```

Python审计钩子阻止Gold、其他题库及子进程；纯检索额外禁止网络。文本基线不加载图；运行完成记录实际打开文件。独立评价进程才读评分，严格按实际序列化响应里的原文行并集计登记证据完整取得；部分行重叠另报，语义支持仍pending。

`e2e.py prepare`在真实BGE索引完成后离线冻结14B协议，七组×200=1400（含400核心参照重跑）。生成必须收到用户明确批准，并创建绑定该协议SHA256、scope=generation、max_sessions及用户原话的批准文件，才允许`e2e.py answer --arm ... --run-id ... --approval ...`。各臂顺序执行，不并发叠加；历史答案/裁判不重写。上述为原启动阶段说明：生成及独立冻结的付费评分现已全部完成；新造留出题计划取消，当前采用原题160/40实体划分。

具体审计、命令日志、测试与成本见归档报告。图表当前为可追溯草稿，待正式实验确认后再进入论文最终assets；未改写历史论文或分数。
