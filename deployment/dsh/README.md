# DSH profile 集成说明

DeepSeek Harness profile 属于机器本地运行状态。业务源码应以本仓库为唯一事实来源，再把 bundle 安装进 profile；不要把 Principia 代码复制到 DSH 上游检出目录。

## 本地开发安装

在已经安装 `dsh` 的 shell 中运行：

```bash
cd "$PRINCIPIA_PROJECT_ROOT"
npm --prefix packages/principia-dsh-bundle run check
dsh plugin --profile web add ./packages/principia-dsh-bundle
dsh --profile web --dump-config
dsh --profile web
```

如果直接从 DSH 上游源码运行，可按实际情况把 `dsh` 替换为 `corepack pnpm@11.7.0 --dir "$DSH_CHECKOUT" dsh`。启动会话时必须把 Principia 仓库作为工作目录，使 `.dsh/skills` 成为最高优先级的项目 Skill 根目录。

## 稳定安装

先构建经过测试的 tarball，再把它和发布版本或 CI 产物一起保存：

```bash
npm --prefix packages/principia-dsh-bundle pack
dsh plugin --profile web add ./packages/principia-dsh-bundle/principia-blastfoam-dsh-bundle-0.1.0.tgz
```

tarball 包含已提交的 JavaScript，因此安装时不需要开放构建脚本权限。通过 npm 发布时必须安装精确版本，不使用浮动 tag；通过 Git 依赖安装时必须固定 commit SHA。pnpm 在依赖执行 `prepare` 脚本前要求明确授权，本包因此有意不使用该脚本。

## 机器本地配置

以下变量应设置在 Git 之外：

- `PRINCIPIA_PROJECT_ROOT`：业务仓库根目录；未设置时使用 DSH 启动目录。
- `PRINCIPIA_PYTHON`：包含本项目和 `mcp` 的 Python 解释器；未设置时使用 `python3`。
- `PRINCIPIA_CASE_ROOT`：允许领域工具修改算例的唯一根目录；默认是 `PRINCIPIA_PROJECT_ROOT` 下的 `outputs`。
- `BLASTFOAM_TUTORIALS`：外部 blastFoam 教程根目录；默认是项目旁边的 `blastFoam_tutorials`。
- `PRINCIPIA_KNOWLEDGE_GRAPH`：可选的知识图谱文件覆盖路径。
- `ENABLE_EXECUTION` 和 `REQUIRE_EXECUTION`：默认均为 `true`。只做配置或 CI 时必须把两者都设为 `false`。
- `OPENFOAM_BASHRC` 和 `BLASTFOAM_BASHRC`：宿主机器的环境脚本。未设置时，预检会警告并依赖继承的 `PATH`；显式路径不存在时会阻断执行。
- `OPENFOAM_EXECUTION_USER`：DSH 以 root 启动时建议设置。`OPENFOAM_CHOWN_CASE=true` 时，领域服务只会把受限目录内生成算例的所有权移交给该用户。
- `RETRIEVAL_LLM_API_KEY`：可选的检索回退凭据。由于 stdio 子进程会清理疑似密钥的环境变量，MCP 客户端必须显式传递它。
- `DSH_PERMISSION_MODE`：通常使用 `workspace-write`；不得把生产密钥放入 profile patch。

bundle 中的 MCP 行默认 `failOnStartupError: false`，便于 Python 环境尚未完成时启动 DSH。评测或生产运行应把示例 patch 复制到 profile，并保持 `failOnStartupError: true`。

## DSH 升级流程

每次升级 DSH 时，先创建一次性 profile，安装当前精确 bundle 版本，执行 `--dump-config`，确认 MCP 工具存在，再完成兼容性验收矩阵。全部通过后才能提升已验证版本；原有已验证 profile 在此之前必须保留。

## 字典定位、条件检查与编辑

MCP 的三个只读工具供物理分析和案例设置角色使用；批量编辑工具仅向案例设置角色开放：

- `locate_case_edits(query, tutorial_case, translation?, budget?)`：按自然语言需求返回完整字典位置、来源及审核过的条件依赖。`tutorial_case` 使用如 `blastFoam/freeField` 的案例标识。
- `edit_case_dictionaries(case_path, edits, dry_run?)`：在已授权副本内按明确的 `path/entry/value` 批量编辑，全部修改文件经 OpenFOAM 解析后写回；null 删除，dry_run 只验证。支持直接位于 system、constant、0 下的字典，含指令/变量替换或新建场文件需另行处理；不推断物理配置。
- `read_knowledge_source(path, start?, end?, budget?)`：读取定位器返回的语料路径；`complete=false` 表示只返回范围前缀，应缩小行范围继续取证。
- `check_case_dependencies(case_path, tutorial_case, budget?)`：只读检查实际副本，路径必须位于 `PRINCIPIA_CASE_ROOT` 内。仅审核范围内全零常数黏度可排除当前黏性依赖；unknown 不表示适用或任务通过。

三个只读工具返回紧凑 JSON 文本，默认 5000 字符预算。静态图在进程内延迟加载并缓存，来源读取校验索引散列。审核条件保存于知识技能的 `references/conditional_requirements.json`，修改后重启 MCP 进程。当前只覆盖有限的来源审核规则，不是通用 OpenFOAM 物理验证器。

服务器在 stderr 输出工具名称、开始/结束和耗时，不记录查询参数或凭据，用于原生工作流采用率检查。这个日志不是模型 token 或完整耗时统计。新增工具的可用性不会自动保证 agent 采用，需要结合实际会话验证。

评测时可显式设置 `PRINCIPIA_TOOL_TRACE_DIR`，将完整工具参数、返回内容及耗时写入该目录；默认关闭。该记录可能包含案例内容，应保存在实验归档目录中。统计模型可见返回量时只计算 MCP 文本内容，不重复计算 structured result。

原生会话的 `session.v2.jsonl.zstd` 可能包含多个压缩帧，仅读首帧会误以为只有会话头。安装 dev 依赖后，使用 `experiments/retrieval_method/audit_native_session.py <会话文件> <归档JSON>` 统计全部工具、加载的技能和已报告用量。该统计不导出提示词内容；失败请求的未报告用量仍可能缺失。`totalTokens` 不应再次叠加缓存或推理字段。

执行评测前核对 DSH 自身的权限模式。宿主机缺少沙箱后端时，`workspace-write` 的 shell 会被拒绝；这属于环境阻断。已获全访问授权的隔离实验可显式设置 `DSH_PERMISSION_MODE=danger-full-access`，并在协议中记录，不能把不同权限模式下的结果当作仅检索方法不同的严格对照。
