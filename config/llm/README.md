# 模型配置

8B仅使用超算服务，从工作区.env.supercomputer读取QWEN_SUPERCOMPUTER_BASE_URL、QWEN_SUPERCOMPUTER_MODEL、QWEN_SUPERCOMPUTER_API_KEY及QWEN_SUPERCOMPUTER_MAX_CONCURRENCY。实时地址和密钥只维护此私有文件。

14B使用代理，QWEN_PROXY_*保留在本目录.env或.env.private；双裁判为gpt-6-sol与deepseek-v4.1-flash，配置见models.yaml和judging.yaml，凭据不提交。

当前生成模型为Qwen3-8B、Qwen3-14B和Llama-3.1-8B-Instruct，统一由experiments/chapter2/models.py读取现有私有配置。两个8B独立服务最高已测64并发，14B保持20；每请求输入与预留输出采用32K约束，正式分词器及协议尚待冻结。

models.yaml仅登记本轮两个候选裁判的模型身份与参数，旧验收状态不沿用。generation.yaml、judging.yaml和execution.yaml记录当前讨论状态，不授权正式实验。负责人确认资源充足，不设置费用审批或费用上限；单人校准方案见实验release/planning/BUDGET_JUDGE_DISCUSSION.md。私有.env文件未修改。
