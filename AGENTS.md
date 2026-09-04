# PrincipiaBlastFoam-DSH 贡献者说明

本仓库是 PrincipiaBlastFoam 基于 DeepSeek Harness 实现的独立应用源码。DeepSeek Harness 只是上游运行时依赖；不得在上游 DSH 检出目录中实现 Principia 业务功能。

## 目录职责

- `.dsh/skills/`：供模型读取的 blastFoam 操作规程。Skill 名称保持 kebab-case，每个 Skill 只使用一个直接入口 `<name>/SKILL.md`。
- `packages/principia-dsh-bundle/`：可安装的 DSH bundle，包含策略插件、角色专属 subagent 工具行和 MCP 客户端配置。
- `src/principia_core/`：不依赖智能体框架的 Python 领域服务。
- `mcp_servers/`：领域服务之上的 MCP 协议适配层。
- `deployment/dsh/`：只提交配置模板；机器路径、profile 状态、API Key 和其他凭据均放在 Git 之外。
- `compatibility/`：经过验证的 DSH commit、包版本和升级证据。
- `experiments/`：评测适配器与评测方法文档；正式实验结果仍写入外部毕业实验归档目录。

## 不可破坏的约束

- 保持 DSH bundle 与 profile 分离：`dsh.bundle` 属于可安装包，profile manifest 由 DSH 创建和管理。
- 精确固定预发布 DSH 包版本，不使用 `latest`、脱字符范围或未验证的版本范围。
- profile patch 会替换目标条目的完整 `config`，因此必须重新声明所有必需字段。
- 复用官方 `spawn` subagent provider，不注册同名的第二个进程级 provider。
- 确定性领域逻辑和产物验证必须放在提示词之外；提示词只能引导行为，不能充当强制约束。
- 不得提交凭据或机器特定的绝对路径。
- 除非是明确需要版本控制的测试夹具，否则生成算例、日志、报告、benchmark 结果、缓存和 DSH profile 状态均不得进入源码仓库。
- 项目文档以中文为主体；命令、环境变量、协议字段、代码标识符和上游包名保留英文。

## 验证要求

至少运行 bundle 检查、Python 测试、profile `--dump-config`、MCP 状态冒烟测试和相关 benchmark 用例。升级 DSH 后，只有通过兼容性验收矩阵，才能更新 `compatibility/dsh-version.json`。
