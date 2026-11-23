# 无害管流开发对照

PIPE-01 从空工程创建稳态管流算例。受测系统负责边界条件、离散方程、生成输入、发起求解、读取结果、后处理及交件。两臂共用数值接口和节点线性求解器。公开工况、交件要求及误差阈值见 [TASK.md](TASK.md)。

| 入口 | 操作与核验 |
|---|---|
| `run_pair.py prepare` | 为本批次一次性建立两个独立工作区，复制公开材料，绑定源文件、运行时和评价协议哈希。已有批次拒绝覆盖。 |
| `run_pair.py general`、`run_pair.py professional` | 各臂通过原生 DSH 入口和既有模型预算网关运行。按顺序启动。完成时将 delivery 封存为 submission.zip，记录文件哈希和请求用量。 |
| `pipe_client.py submit`、`pipe_client.py collect` | 模型在本臂工作区登记 65 行有限数值；collect 等候本次作业回执。接口通过工作区文件传递消息，两臂权限相同。 |
| `operate.py general`、`operate.py professional` | 操作者在对应请求出现后运行。检查数据结构和固定程序哈希，仅上传重序列化的数值及固定程序。单节点经 yhbatch 分配。检查调度器、节点日志和归属，再交回 profile.csv 及回执。 |
| `reconcile.py general`、`reconcile.py professional` | 已有提交意图但缺 JobID 时使用。核对唯一记账项、作业名、分区、属主、工作目录与提交命令，恢复同一作业的回执并继续查询回收。 |
| `check_delivery.py general`、`check_delivery.py professional` | 从封存 ZIP 检查输入和节点原件，逐点比较解析速度，核对中心速度和体积流量。另从干净目录按交件说明复跑，以核验用户入口。 |

各入口用 Python 运行。此实现绑定 2026-11-20 独立开发归档及对应 run ID。原18题及其历史成绩保留在原批次。作业资源上限为一个节点、15分钟，每臂最多100次模型请求。真实运行依赖本地已获准的模型配置和 C 集群操作者配置。实际费用以账单为准。
