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
