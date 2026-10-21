# 第2章检索与专业问答实验

8B、14B均已完成全部200题的六方法与两项消融，生成、匿名AI评分及统计均已闭合；每模型1600、合计3200个比较会话。32B等待用户提供API，尚无结果。 研究设计由[共享入口](../../../graduation-thesis-materials/graduation-research/chapters/chapter02.md)维护，实施见[工程计划](KNOWLEDGE_QA_PLAN.md)，实际批次与结果见[实验总入口](../../../graduation-experiment-results/chapter2_retrieval/current/README.md)。

正式图已获用户接受，不再择图。六方法包括基础搜索（glob/grep/原文读取）与模型直接作答（无工具）；原2800条证据和新增400条分别保留身份。主指标为端到端有效回答得分，严格完整有效率（整题全部正确）保留为辅助指标；失败计0、未知保留上下界，全部200题保留分母。

离线交付核验均不调用模型：

- `chapter2_verify_basic_search_delivery.py`：当前3200条、六方法及两消融、原证据不变、图表与正式论文。
- `chapter2_verify_model_scale_delivery.py`：原两模型七组2800条；当前论文范围另由前一核验器确认。
- `chapter2_verify_revision_delivery_200.py`：原8B修订1400条、数据与构图来源重放。

冻结实现不得随维护覆盖；新增实验另冻结。应用源码在本项目，运行及评分在实验归档，题库在统一数据集，正文与最终图表在统一材料仓库。
