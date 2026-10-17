# 专业知识问答与图谱检索实现

更新时间：2026-10-17。第2章只使用[277题专业知识问答集](../../../graduation-datasets/chapter02_knowledge_qa/README.md)，开发77题、测试200题；开发、方法比较、图谱消融及父内容处理共享该题集。实验归档见[第2章入口](../../../graduation-experiment-results/chapter2_retrieval/README.md)。

详细范围见[完整工程计划](KNOWLEDGE_QA_FULL_20261017.md)与[问答工程计划](KNOWLEDGE_QA_PLAN.md)。当前父内容策略开发1232会话及原v7评分完成，开发选择直接父内容；17136份正式回答和1536份双层AI来源意见已完成，自动评分与最终统计正在运行。基准图比较13536会话使用同一题集，不称为旧题集结果。

`chapter2_knowledge_*`维护专业问答的图、题目接口、原文复核和评测；`chapter2_full_*`维护完整比较计划、执行、评分和统计。`chapter2_sse_*`为可审计的传输与逻辑请求适配，不修改冻结v7的语义规则。正式运行使用独立源码快照，维护源修改不追溯改变已生成答案或评分。

批量从`.env.qwen_proxy`读取配置，`qwen3-8b`及`qwen3-14b`每模型最多16并发。小批量从`.env.qwen_local`读取专用配置；名称和参数见[部署说明](../../../QWEN_LOCAL_MODELS.md)。不同部署的分数不混用。离线构图与语义校验精确使用`deepseek-flash`。

来源图只持久化图与必要构图清单；BM25、E5和混合检索作为隔离对照，不进入图检索链路。Gold、参考答案及评分意见不进入构图、索引或被测输入。根据开发反馈调整方法，正式测试只评估已登记实现；不以目标百分比改动题目、评分或分母。主指标、必要点覆盖、原文送达和引用支持分别解释。

论文在[稿件项目](../../../graduation-thesis-materials/graduation-manuscript/README.md)直接以LaTeX维护；图表脚本在[制图项目](../../../graduation-thesis-materials/graduation-visualization/chapter_02_knowledge_graph_retrieval/README.md)，正式产物进入稿件assets。
