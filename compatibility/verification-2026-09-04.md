# 兼容性验证记录（2026-09-04）

验证基线：上游 DSH commit `d347e703908d0406b7a7ef80e3a0e594d86b2215`，根版本 `0.1.3-alpha.1`，Node `v24.15.0`，pnpm `11.7.0`。

## 已通过检查

- `npm run check` 通过 TypeScript 编译以及 Node 策略/manifest 测试。
- `npm pack --dry-run --json` 验证 tarball 包含 bundle patch、已编译 ESM 入口、类型声明、源码和 README。
- 一次性 Web profile 成功安装本地 bundle；`--dump-config` 合成了策略插件、MCP 客户端、5 个独立角色工具、`PRINCIPIA_CASE_ROOT` 和教程根目录，且没有重复行 ID。
- 短时 Web 宿主启动成功；Web 地址发布前，stdio MCP 服务已经响应 DSH 的 `ListToolsRequest`。
- 无密钥集成检查把当前 DSH `@deepseek-ai/dsh-mcp-client` 直接连接到项目 `.venv`（`mcp==1.29.1`），发现全部 17 个工具，并真实完成 `get_status`、非执行 `complete_workflow` 和受执行闸门控制的 `run_case` 调用。
- 同一 DSH 客户端保留了 MCP schema 限制（`top_k <= 20`）；越过 `PRINCIPIA_CASE_ROOT` 的算例路径和 `max_lines=1001` 均返回工具错误，且没有启动 solver。
- 官方 `FileSystemSkillProvider` 从本仓库发现 7 个来源标记为 `project-dsh` 的 Skill。
- 项目隔离虚拟环境通过全部 38 个 Python 领域/MCP 测试，覆盖默认执行、显式停用、非执行回退、教程路由、可移植环境和无效 bashrc 失败关闭，并暴露 17 个 MCP 工具。
- 第 3 章兼容适配器从既有 benchmark 中选择 1 个用例完成 `--dry-run`，写出旧版 `run_*/benchmark_report.json` 结构，报告 `cases_executed: 0`，且没有创建算例或日志目录。
- 注入凭据的上游 headless 冒烟返回 `DSH_SMOKE_OK`；凭据始终位于 Git 之外，也没有持久化到 DSH profile。
- 第二次只读 headless 冒烟加载 `blastfoam-workflow`，由父智能体调用 MCP 状态和意图检索工具，把请求解析为 `blastFoam/freeField`。
- 检索服务从 28 个图谱文件中报告 3,990 个算例节点和 5,303 条关系。
- `blastfoam_physics_analyst` 在角色白名单约束下启动，独立调用相同的两个 MCP 工具，选择相同教程，并返回包含可测验收条件的物理交接结果。
- 会话证据中不存在 shell、写入、编辑、算例初始化、工作流收尾或执行调用，没有创建算例或启动 solver。
- 另一轮四角色 headless 冒烟按严格顺序作用于忽略目录中的 `outputs/dsh-role-smoke-freefield`，设置 `ENABLE_EXECUTION=false`，并把算例根边界限制在仓库 `outputs` 目录。
- `blastfoam_case_setup` 只调用 `initialize_case` 和 `case_digest`，选择 `blastFoam/freeField`，在受限输出目录内复制算例，报告 15 个字典且核心文件无缺失，没有调用 shell 或通用文件工具。
- `blastfoam_execution_specialist` 只调用执行 Skill、`execution_preflight` 和 `run_case`。预检通过，但 `run_case` 返回 `started: false`、`blocked: true`，并明确说明 solver 未启动。
- `blastfoam_postprocessor` 只调用后处理 Skill、`write_post_processing` 和 `diagnostics`，没有使用其获准的 bash 能力。确定性报告只记录初始时间 `0`，不存在 `postProcessing` 目录或探针字段。
- `blastfoam_quality_reviewer` 只调用允许的 `skill`、`read`、`glob`、`grep`（调用次数分别为 1、23、9、4），没有写入或 shell 调用，并在响应文本中执行失败关闭审查。
- 父会话只调用 4 个具名角色工具、Skills 和待办跟踪，没有调用 shell、写入或编辑。运行后算例树中不存在 `0` 之后的时间目录、solver 日志、`processor*` 或 `postProcessing` 输出。
- 该角色冒烟保留了真实的负面证据：审查员发现球形装药请求与教程箱形装药不匹配，当时生成的物理报告错误声称执行已启用，且缺少 3 项最终产物。随后已经把回退执行标志修正为实际 `ENABLE_EXECUTION` 闸门并加入 Python 回归测试；保留的忽略目录夹具生成于修复之前。几何和产物缺口仍然存在，因此这次角色冒烟不宣称端到端成功。
- 领域服务、MCP schema、DSH bundle 环境、本机包装命令和第 3 章适配器现在都默认开启 solver。`ENABLE_EXECUTION=false` 与 `REQUIRE_EXECUTION=false` 是显式非执行覆盖方式。
- 第一次真实 solver 路由冒烟暴露了一个平分问题：中文激波管请求被错误选为 `blastFoam/triplePointShockInteration`。虽然 solver 正常结束，但该运行被判定为教程选择失败，没有计入验证成功。
- 修正确定性路由并增加回归测试后，新建的隔离 MCP 领域冒烟正确选择 `blastFoam/shockTube_tabulated`，以非特权 `openfoam` 用户运行，限制 60 秒，最终返回码为 0、没有超时、solver 日志以 `End` 正常结束，并产生 `5e-06` 和 `1e-05` 输出时间。
- 修正后的运行通过物理、执行、后处理、执行状态、诊断和审查的全部严格检查，七项产物契约为 `ok: true`；仅记录一个非阻断的 `mesh_default_patch` 警告。证据保存在忽略目录 `outputs/runtime-smoke-shocktube-fixed.LyyLrQ`。

## 尚未宣称通过

- 尚未执行基于真实 DSH/OpenFOAM 的完整第 3 章端到端 benchmark；目前只通过了不执行求解的适配器 `--dry-run`。
- 早期球形装药角色夹具仍存在教程/请求几何不匹配和产物不完整；修正后的激波管真实 solver 夹具已经通过严格产物契约。
- Web 启动测试通过 SIGINT 主动终止；强制关闭期间，Python FastMCP 子进程打印了取消异常堆栈。

## Npm 发布说明

上游源码树为 `@deepseek-ai/dsh-mcp-client` 和 `@deepseek-ai/dsh-tool-subagent` 声明了 `0.1.3-alpha.1`，但验证时 npm 上没有对应版本的 MCP client。DSH 应用运行时已经持有这些包，因此本 bundle 引用宿主副本，不安装可能造成 Cordis 服务身份分裂的旧版副本。
