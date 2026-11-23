# DSH Linux部署与维护

更新：2026-11-23。DSH源码、Git、依赖、agent、模型API及领域工具均在Linux；Windows通过SSH维护，Web浏览器用于人工调试。Windows不维护DSH源码副本，第2章独立留在Windows的chapter2-knowledge-qa。

迁移和离线检查已完成，真实模型与单个100单元方腔的功能链已验收，包含维护恢复；作业9283604在cnode4754完成，40次请求含1次未知用量。详见[单算例验收](../acceptance/README.md)。不将此结果解释为无干预自主成功或研究收益，不复用已结束额度。

Web入口为[启动实现](../web/serve_web.py)，状态在工作区services/chapter3-web-20261123。已验证真实聊天、get_status输入输出展开、执行轨迹、刷新历史、服务重启历史恢复与SSH隧道自动重连。独立100次预算不属于正式批次。Windows一键入口在本地毕业工作区根目录。

加载工作区environment.sh后使用dsh-dev；只读配置为dsh-dev --profile headless --dump-config。现用Node/pnpm位于workspace/runtime；controller_20261122的source/application副本及退役启动器已验证清理。源码修改不自动部署。按任务规模和资源需求选择执行位置：轻量建网、checkMesh、小规模初始化/预处理、摘要统计与绘图可在独立Linux本地执行；大型网格、长时或高资源求解、MPI并行及大型重构/后处理经yhbatch在超算分配节点执行。不得仅按命令名称一刀切；先核对工具、输入规模及CPU/内存/磁盘余量，并设置任务适用的超时和输出限制。公共登录节点仍只做轻量传输、提交和查询，不运行网格或求解。大结果留超算。旧Windows启动器和历史工作器不是当前入口。详见[部署规则](linux-controller-plan.md)。当前只维护文档，不启动批量实验。

2026-11-23运行组件整理：Node/pnpm已迁到workspace/runtime，正常Web配置、认证页面、只读领域MCP与持久账本检查通过；旧controller_20261122/source、application和退役启动器已删除。模型请求与节点作业均未增加。记录见workspace/runtime/verification.json与cleanup.json。
