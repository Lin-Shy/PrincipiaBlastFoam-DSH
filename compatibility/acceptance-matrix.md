# DSH 兼容性验收矩阵

不得仅根据版本号更新所支持的 DSH commit。DSH 仍处于预稳定阶段，各子包版本可能独立变化。

| 检查项 | 必需证据 | 放行条件 |
|---|---|---|
| Bundle 包 | `npm run check` 与 `npm pack --dry-run` 均通过 | 必须通过 |
| Profile 合成 | `dsh --profile <test-profile> --dump-config` 包含策略、MCP 和 5 个角色工具，且不存在重复 ID | 必须通过 |
| MCP 启动 | `mcp__principia_retrieval__get_status` 返回知识图谱和教程状态 | 必须通过 |
| Skill 发现 | 会话工作目录为本仓库时，能够从 `.dsh/skills` 发现全部 7 个项目 Skill | 必须通过 |
| 角色隔离 | 物理分析员和审查员不能调用 shell 或写入/编辑工具；审查员只返回审查内容，不自行落盘 | 必须通过 |
| 产物契约 | 冒烟算例完整说明 7 项必需产物，且审查员没有修改受保护输入 | 必须通过 |
| 回归评测 | 选定冒烟用例和完整第 3 章 benchmark 保持预期状态 | 发布前必须通过 |

升级测试必须在一次性 profile 中进行，同时保留上一个已验证 profile。只有全部门槛通过后才能更新 `dsh-version.json`；如果存在已知失败，应如实记录，而不是推测性地放宽版本范围。
