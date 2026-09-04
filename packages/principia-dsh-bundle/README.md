# principia-blastfoam-dsh-bundle

这是 PrincipiaBlastFoam 的可安装 DeepSeek Harness 配置 bundle。它提供一个策略插件、Python 检索 MCP 连接，以及基于官方进程内 `spawn` subagent provider 的 5 个角色工具。

本 bundle 应叠加在 `@deepseek-ai/dsh-base` 之后。官方 base 已经拥有进程级 `spawn` provider，因此本包不会注册第二个同名 provider。DSH 应用运行时提供 `@deepseek-ai/dsh-tool-subagent` 和 `@deepseek-ai/dsh-mcp-client`；本包不安装私有副本，以免不同 Cordis 副本造成服务身份分裂。宿主提供的兼容版本固定在仓库的 `compatibility/dsh-version.json`。

当前 DSH subagent 的 `toolFilter` 控制工具名称，而不是文件系统路径。因此各角色采用允许列表：审查员只能使用 `read`、`glob`、`grep` 和 `skill`，并以结构化内容返回审查结果。父智能体或确定性写入器负责生成 3 个审查阶段产物；提示词文字不被视为路径级安全控制。如果允许列表中的 MCP 工具未被发现，物理分析和算例配置角色必须失败关闭。

构建和测试：

```bash
npm install
npm run check
npm pack
```

已提交的 `lib/` 输出保证本地路径安装和 tarball 安装无需开放安装期构建脚本。启动 DSH 前必须设置 `PRINCIPIA_PROJECT_ROOT`；还可以设置 `PRINCIPIA_PYTHON`、`BLASTFOAM_TUTORIALS` 和 `PRINCIPIA_KNOWLEDGE_GRAPH`。

`ENABLE_EXECUTION=true` 和 `REQUIRE_EXECUTION=true` 使 solver 与严格执行产物默认开启。非执行会话必须显式把两者设为 `false`。
