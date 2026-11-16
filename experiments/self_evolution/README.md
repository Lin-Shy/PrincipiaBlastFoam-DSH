# DSH单agent RSI实施入口

更新：2026-11-16。当前阶段：P0待执行；本轮仅更新设计与执行清单，尚无本设计下的实现验收或收益结果。

研究定义以[第4章共享设计](../../../graduation-thesis-materials/graduation-research/chapters/chapter04.md)为唯一来源；[PLAN.md](PLAN.md)为可直接交给Codex的唯一详细任务清单，涵盖现有真实算例清点、评测集并行建设、T/I/V/M演化、接受与回退、同一起点改进能力测量及正式实验准入。

2026-11-16用户允许修改任务执行、自改进逻辑与外部验收，基础权限与预算固定。外部验收为确定性程序，不引入额外评审agent；候选验收器不能批准自身。独立profile不加载第3章多角色bundle或预设轨迹。

任务在[第4章数据集入口](../../../graduation-datasets/chapter04_rsi_tasks/README.md)维护；原始证据、版本和运行结果进入`graduation-experiment-results/chapter4_self_evolution/dsh/<campaign>/`。当前尚未建立本设计的campaign。已人工入选的物理场景可以按资格用于开发，不自动成为正式参考基准或未见测试。

论文与PPT未同步此轮设计；执行清单默认不改稿件、不做Git操作。后续完成步骤后，在本入口记录实际阶段与campaign链接。
