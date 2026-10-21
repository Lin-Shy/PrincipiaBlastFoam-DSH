# DSH profile 集成说明

日常启动和面向初学者的操作步骤见 [DSH 新手使用手册](../../docs/新手使用手册.md)。本页保留部署与兼容性细节。

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
- `BLASTFOAM_TUTORIALS`：外部 blastFoam 教程根目录；默认是工作区内的 `graduation-datasets/raw-corpus/blastfoam/blastFoam_tutorials`。可用此变量覆盖其他部署位置。
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


## Windows 本地宿主与 Linux 远程求解：独立 MCP 方案（2026-10-12，保留）

采用用户共享讨论的最终方案：agent、知识检索、实验归档与主要文件留在 Windows；Linux 只运行独立的仿真 MCP 与临时算例。服务不含 DSH、角色或第3章产物契约，第4章可复用同一服务。共享讨论：[远程仿真开发方案](https://chatgpt.com/share/6acccf53-4ca0-83eb-b401-c90555549ce7)。

本地宿主位于工作区父目录的 deepseek-harness，固定 compatibility/dsh-version.json 的 commit d347e703908d0406b7a7ef80e3a0e594d86b2215（0.1.3-alpha.1），使用 Node 24 与 pnpm 11.7.0。dsh-tools 存放局部 pnpm shim。两章分别使用父目录 dsh-home/chapter3 与 dsh-home/chapter4；第3章 web/headless 已安装应用 bundle，第4章不安装它。后者使用独立工作目录并关闭 subagent、fork、控制和 workflow 工具；这是单 agent 启动配置，尚无 RSI 控制器或收益结果。

Windows 入口（在应用根目录执行）：

~~~powershell
# 先检查合成配置；不会调用模型或 solver。
./deployment/windows/Start-Principia.ps1 -Chapter 3 -Profile headless -DumpConfig
./deployment/windows/Start-Principia.ps1 -Chapter 4 -Profile headless -DumpConfig
# 本地 Web 开发，无本地 solver。
./deployment/windows/Start-Principia.ps1 -Chapter 3
~~~

机器设置复制 deployment/windows/windows.ps1.example 到 .local/windows.ps1；该目录已忽略。设置实际 PRINCIPIA_REMOTE_SIMULATION_ROOT。可用 -CaseRoot 为每轮实验选择独立本地算例目录。凭据与模型配置继续放在机器设置或 DSH home，模板不含密钥。

远端部署只上传 build_package.py 选中的几个 Python/脚本文件，压缩包约6 KB，不上传知识语料、实验归档或 Harness：

~~~powershell
# 需要可用的 SSH 登录；RemoteDirectory 必须是实际选定的 Linux 部署目录。
./deployment/windows/Deploy-Simulation.ps1 -RemoteDirectory '/your/service/directory'
~~~

随后在 Linux 将 simulation.env.example 复制为 simulation.env，设置实际 OpenFOAM/blastFoam 环境脚本、SIMULATION_ROOT 和 SIMULATION_RUN_SCRIPT；把 service.example 中的目录和非 root 用户替换为实际值，再通过 systemd 启动。仅需 Python >=3.11 与 mcp>=1.27,<2（与现有项目一致，不照搬共享讨论中的 SDK v2 示例）。服务只监听 127.0.0.1:8000/mcp，不开放公网 MCP 端口。

启动 SSH 隧道（该命令持续占用当前终端）：

~~~powershell
./deployment/windows/Open-SimulationTunnel.ps1
# 另一个终端启动远程模式；MCP 不可连接时启动失败，避免假装可用。
./deployment/windows/Start-Principia.ps1 -Chapter 3 -Remote
./deployment/windows/Start-Principia.ps1 -Chapter 4 -Remote
~~~

隧道保留用户指定的反向代理 7897，同时把本地8000转发到Linux回环8000。新建 ssh/scp 文件传输连接清除继承的转发配置，避免与长期隧道竞争端口。

工具流程：upload_simulation_case（本地 SFTP 文件桥）→ run_simulation（远端异步提交）→ get_simulation_status/log → get_simulation_result → download_simulation_result（SFTP 下载并核对 SHA256）→ 本地解压、任务验证及归档 → cleanup_simulation（携带已下载散列）。大文件不进入 MCP JSON；下载失败或散列不匹配时保留远端结果。远端提交后移除已复制的 staging 输入，默认最多1个活动任务，输入上限512 MiB，默认至少保留2 GiB磁盘空间，运行中不足空间会终止进程组。终态仍保留完整结果，必须回传后主动清理。

独立 worker 保存 request/status/result JSON，MCP 客户端断开或服务重启不影响正常后台任务；timeout/cancel 会终止 solver 进程组。服务器重启、worker 被外部强杀或磁盘耗尽仍需运维检查，不能把正常服务重连等同于任意故障下自动恢复。completed 只代表退出码0，日志 End 也只是有限证据；时间目录、必要场、非有限值和用户需求须由本地确定性验证器核验。

第3章最终产物仍由本地应用组织；远程模式不要调用会再次启动本地求解的 complete_workflow。取得结果后先在本地完成执行证据与输出检查，再调用 write_evidence、write_post_processing 和 validate_artifacts。当前旧 benchmark 适配器已修复 Node 启动和 Windows 进程终止，dry-run 可用；新远程链路的正式评分接入和真实 solver 验收仍需另行完成与冻结，不能把本次工具测试当作第3章正式结果。

本次本地验证包括 bundle 构建/测试、两章配置树、检索 MCP stdio 状态、仿真 MCP 真实 HTTP 协议、模拟进程的成功/失败/超时/取消、并发和存储限制，以及 SFTP 路径/下载散列检查。按2026-10-12用户后续要求，MCP 部署和 SSH 联调暂时跳过。远程工具源码与模板仅作为待接入内容；真实 Linux 部署、仿真 smoke 与正式评分未执行。

Windows 本地验收记录见 [windows-migration-20261012.json](../../compatibility/windows-migration-20261012.json)：64项Python测试通过、1项因Windows符号链接权限跳过，bundle 3项测试通过，官方构建记录222项客户端产物，Web认证HTTP200。历史Linux兼容基线不覆盖；真实 solver 与正式 benchmark 未运行。知识语料和索引的 Git 换行转换已禁用，Linux脚本保持LF，避免以后checkout破坏原始散列。


## Remote SSH 工作区：首次本地安装（2026-10-13 历史记录）

按用户本轮要求，使用 [Yan-Zero/dsh-remote-ssh](https://github.com/Yan-Zero/dsh-remote-ssh) 直接连接 OpenSSH Host，并把所选远端工作区的文件、Bash、搜索与后台进程交给 Linux。DSH 仍运行于 Windows；这一路径使用远程工作区，不会启动上节的仿真 MCP 服务。现有本地 web/headless 配置保留。

插件安装在工作区父目录的 dsh-remote-ssh。固定上游 v0.2.1 的 commit 6fe4c24a0386ba1047ec8d3919484f50dd3ebc6d；不采用需要额外宿主/TUI 依赖的后续版本。由于 npm 同名包已下架，安装来源为上述 GitHub 固定源码与本地构建 tarball。当前 Harness 仍是 compatibility/dsh-version.json 固定版本。

上游插件依赖的 settingsNamespace 导出在本机 Harness 中已移除；[兼容补丁](../windows/remote-ssh-0.2.1.patch) 改为兼容新旧 API 的设置命名空间，并标记版本为精确 0.2.1-principia.2。没有修改 Harness 源码。补丁、安装版本和验证边界见 [验收记录](../../compatibility/remote-ssh-20261013.json)。

两章各自在原来的 DSH home 中新增 web-ssh profile。第3章安装应用 bundle；第4章不安装该 bundle，仍使用独立本地工作目录和 single-agent overlay。远程第4章工作目录也必须与第3章隔离，不得从第3章项目发现角色或技能。

在工作区根目录启动：

~~~powershell
./PrincipiaBlastFoam-DSH/deployment/windows/Start-Principia.ps1 -Chapter 3 -Ssh
# 第4章使用相同入口，启动后选择独立的 Linux 工作目录：
./PrincipiaBlastFoam-DSH/deployment/windows/Start-Principia.ps1 -Chapter 4 -Ssh
~~~

机器配置保存在被忽略的 .local/windows.ps1：PRINCIPIA_SSH_HOST 指向用户选择的 Host（本机为 yan_yun）；可选 DSH_REMOTE_SSH_CONFIG 指定 OpenSSH 配置文件、DSH_REMOTE_SSH_WORKSPACE 指定该章的真实 Linux 工作目录、DSH_REMOTE_SSH_CODE 指定已有 Agent Host CLI 命令。未设置远端工作目录时，从 Web 的 Settings → Remote SSH 或工作区入口选择 Host 并浏览 Linux 目录；尚未选择 Remote 工作区的会话仍在本地执行。-Ssh 与旧 -Remote 开关互斥，当前 SSH 入口只支持 Web。

插件 bundle 明确采用 danger-full-access 和 approval=never，以 SSH 账户作为远端权限边界。因此仅在专用 web-ssh profile 启用。首次配置曾给插件连接添加 ClearAllForwardings=yes；该选项也会清除插件自己的 -L 隧道，已在下节接入验收中修正。只读 SSH/scp 检查仍可使用该选项；用户的 SSH 配置保持原样。

先在本机验证免交互登录：

~~~powershell
ssh -o BatchMode=yes -o ClearAllForwardings=yes yan_yun "uname -s"
~~~

若返回 Permission denied，先配置用户自己的密钥或 SSH agent；仅手动输入密码成功不足以满足插件调用。无需在聊天或 Git 中提供密码、私钥或 Web token。登录后还须检查 bash、base64、mkfifo、rg、blastFoam/OpenFOAM 环境，以及兼容的 VS Code Agent Host（已安装的 code、缓存的 VS Code Server 或插件私有 CLI）。未检查前不声称仿真可用；未部署任何远端 CLI。

本机已通过插件40项测试、两个 profile 配置合成与 Web 启动、插件 API 识别 Host、应用 bundle 3项测试、部署相关 Python 45项测试（10项平台跳过）、检索 MCP 冒烟。全套历史检索测试在 Windows 收集时有20项因 fcntl 不可用失败，保留 Linux 运行要求。内置浏览器在本会话不可用，页面交互未验收。

当前远端验收阻塞于 SSH 认证，未选择远程工作目录，未验证 Agent Host、远程文件/搜索/Bash/会话方言，也未运行真实 solver 或正式实验。Chapter 3 原有本地领域 MCP 不会因 SSH 插件自动迁移到 Linux：其路径仍指向本地。远端仿真应在已选择的 Remote 工作区通过 Bash 执行；跨本地检索/产物与远端算例的正式实验适配仍须另行验收。

复现插件构建：在全新固定 commit 的插件检出目录中应用上述 patch，然后运行 corepack pnpm@11.21.0 install --frozen-lockfile、corepack pnpm@11.21.0 run check 和 corepack pnpm@11.21.0 pack。将完整构建 tarball 保存到 Git 之外。profile 中设置 auto-install-peers=false（.npmrc），用本机 DSH CLI 的 plugin --profile web-ssh add <绝对 tarball 路径> 安装，沿用 profile 的 pnpm@11.7.0，避免自动引入浮动版本或第二套 DSH。profile manifest 的基础 bundle 顺序应为 dsh-base、dsh-web-app、可选第3章应用 bundle、dsh-remote-ssh；机器 override 由启动入口加载。


## 非 root Remote SSH：当前已验收入口（2026-10-13）

当前机器配置已切换为用户提供的 yan_yun_agent；ssh -G 与远端 id -un 均确认实际用户为 agent，免交互公钥登录通过。启动入口会拒绝解析为 root 的 SSH 用户。两章在该用户 home 下分别使用 principia/chapter3 与 principia/chapter4；实际机器路径只保存于被忽略的 .local/windows.ps1，变量名分别为 PRINCIPIA_SSH_CHAPTER3_WORKSPACE 和 PRINCIPIA_SSH_CHAPTER4_WORKSPACE。

保持前述一条启动命令，使用 -Chapter 3 -Ssh 或 -Chapter 4 -Ssh。启动后的 Remote 工作区名为 yan_yun_agent > chapter3 或 yan_yun_agent > chapter4；需要在会话中选择相应 Remote 工作区，Local 会话继续留在 Windows。

按用户明确授权，在 agent 用户 home 的 .dsh-remote-ssh 下安装官方 VS Code CLI 和 ripgrep 14.1.1；发布的 ripgrep SHA256 已核对。私有 code-with-env 包装脚本设置仅供 Agent Host 及其子进程使用的 PATH，加载已安装的 OpenFOAM/blastFoam 环境，并提供仅监听回环的代理。不修改系统软件或 shell startup 文件，不调用 sudo，不读取私钥。

现有 Agent Host 实际接受 AHP 0.10；最初的 SDK 0.7 与前向 0.8 无法握手。当前插件精确版本为 0.2.1-principia.4，使用官方 SDK 1.0.0，并增加经实际文件/Bash/搜索验证的 0.10 前向握手。SDK 正式版本列表不包括这一宿主提供的 0.10，所以这项兼容性以本次真实工具验收为依据，不能据此宣布支持任意后续协议。Harness commit 与版本保持不变。完整补丁及锁文件见 [remote-ssh-agent.patch](../windows/remote-ssh-agent.patch)；在固定上游 commit 的干净插件 checkout 中应用此补丁，再执行 pnpm@11.21.0 install --frozen-lockfile、run check、pack。它替代首次安装的较旧兼容补丁；不要叠加两份 patch。

Linux 直连官方更新服务器超时；Agent Host 下载由官方 CLI 通过用户原有 Windows 7897 代理完成。机器配置 PRINCIPIA_SSH_PROXY_PORT 可让 [Ensure-RemoteSshProxy.ps1](../windows/Ensure-RemoteSshProxy.ps1) 自动建立或复用 agent SSH 回环转发；本地代理必须运行。代理隧道在后台独立运行，跨章节启动复用。脚本只复用能通过官方更新端点检查的代理，拒绝 root 用户和带既有转发规则的 Host；PID 与日志仅保存在 .local。直接 SSH/scp 验证清除继承转发，插件的服务器 sshArgs 保持空数组，让自身 -L 隧道正常工作。

[install_remote_ssh_user_deps.sh](../remote/install_remote_ssh_user_deps.sh) 接受已经下载并校验的 staging 文件、实际 OpenFOAM/blastFoam bashrc 和可选 proxy URL；它拒绝 root 与用户 home 以外的 staging。CLI 安装包来自官方端点，其实际版本与归档校验值保存于 [本次验收记录](../../compatibility/remote-ssh-agent-20261013.json)。新增的固定 CLI 版本与已下载的新版缓存均保留；版本升级后须重新验证宿主协议。不要仅靠最新版标签推断兼容。

本次实际 DSH 验收包括：两章的远端目录列举；第3章 Remote 工作区内文件写入/读取；Bash 的 id -un、pwd、blastFoam -help；通过 DSH subprocess 路由执行远端 rg；本地文件路由继续读取应用文件；远端方言为 bash、本地为 pwsh；两章认证 Web HTTP 200；第4章不包含第3章 bundle，subagent/fork/control/workflow 工具仍禁用。插件40项测试通过。测试未调用模型，未启动真实仿真算例；未验证浏览器页面交互、模型侧工具卡片、RSI 或正式实验收益。Windows 本地领域 MCP 的路径不会因本插件自动迁移到 Linux，正式跨端实验适配仍须另行验收。
