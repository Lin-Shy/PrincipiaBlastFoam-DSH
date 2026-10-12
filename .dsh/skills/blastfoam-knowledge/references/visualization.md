# 离线图谱导出

在 skill 目录执行，产物写入外部实验归档的新目录：

```bash
python scripts/export_visualization.py --output <外部归档目录>/graph
# 使用已有冻结配置索引，确保浏览的正是该轮实验所用图谱
python scripts/export_visualization.py --index <实验目录>/derived-graph.json --output <外部归档目录>/graph
```

导出器验证来源文件 SHA-256、行号及节点连接，生成：

- `graph.html`：无需服务端或网络，直接用浏览器打开；搜索、按案例/关系筛选、文件聚合、一跳邻域、原文与条件查看、拖动缩放、当前视图 SVG/JSON 下载。
- `graph.json`：完整的两层节点、关系和原文内容，适合后续分析；HTML 也内嵌完整数据。
- `overview.svg`：配置证据图按案例/手册聚合的静态总览，省略组内关系。
- `manifest.json`：两层快照、数量和产物摘要；导出不调用模型。

配置证据图保留作用域和静态关系；原有语义定位图展示实体与来源卡片，保留抽取条件、审核状态和公式图表需人工核对的标记。颜色按案例/手册来源分组，没有运行社区发现。原文定位通过校验不等于语义或仿真已验证。

为避免大图遮挡，页面默认显示文件总览，每页最多 300 个节点，可切换到 1,000 个并翻页。界面显示完整数量、筛选数量和当前数量；跨页连线不绘制，全部数据仍在导出文件中。图中选择节点后，右侧可查看所有相邻关系；实体原文位于相邻来源卡片。文件聚合时同文件内部连接省略，切换“片段／实体”查看。

交互设计参考 [graphify v8 HTML 导出器](https://github.com/Graphify-Labs/graphify/blob/v8/graphify/exporters/html.py) 的分组、搜索、节点详情和邻域浏览；本实现为独立的原生 Canvas 离线页面，不依赖 graphify、CDN 或可视化服务。不修改检索索引或排序。
