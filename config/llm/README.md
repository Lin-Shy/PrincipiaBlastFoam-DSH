# Terra候选优化入口（2026-10-28）

候选开发使用`terra_candidate.py --execute`；原生Responses候选使用同入口的`--native`。这是独立候选试验，未修改冻结Prompt、五档规则或原Sol结果。流重建、身份与usage校验由`terra_stream.py`/`terra_native.py`执行；候选协议与技术恢复修订在正式实验release/protocol中。请求medium/high不等于独立证实服务端内部推理等级。

当前接口控制受上游过载和无回执断连阻塞，没有新候选通过验收，不能把候选评分用于正式替换。诊断入口为正式实验evaluation/judges/terra_candidate/index.html。原正式补评分支的验收门控继续保留；本候选入口不会自动解锁旧配置。

# 当前Test160 GPT接口（2026-10-28）

负责人追加Terra验证要求，进一步正式调用须先通过`terra_validation.py`的固定人工参考验收；协议为正式实验`release/protocol/terra_validation.json`。验证或重评未闭合时，不把Sol统计改称Terra统计。

GPT新增补评使用 **gpt-6.1-terra**，DeepSeek继续使用 **deepseek-v4.1-flash**。活动运行配置为本目录 `test160_gpt_runtime.json`，入口为 `experiments/chapter2_rag_v3/test160_terra.py --authorization <正式test160_approval.json>`。不新增凭据文件，沿用已有独立Key和代理。

该配置在冻结请求上仅替换body.model，其他输入、Prompt、Schema、额度及有界恢复规则保持原样。models.yaml/judging.yaml为冻结基础配置，不回写；gpt_sol是沿用的契约/存储槽标识，不代表新增响应仍由Sol生成。每份请求保存实际模型profile，响应须精确匹配gpt-6.1-terra，否则停止该分支。

既有Sol分数复用并保留原身份；人工校准/审计仍属原Sol模型，Terra尚无人评验证。不得批量重命名历史响应。授权变更见正式实验release/protocol/test160_gpt_terra_amendment.json。以下为历史配置与执行范围说明。

# 历史五档双指标评分（2026-10-24）

当前唯一运行入口为 `experiments/chapter2_rag_v3/scoring.py`。规则在同目录 `scoring_rules.json`，两个裁判共用 `judge_prompt.txt` 并附加同一规则。一次五档K/F/A评分计算 `EAS_arith` 和 `EAS_geo`，分别保留单裁判结果和两裁判简单平均。当前配置版本由 `judging.yaml` 顶层及 `dual_judge.selected_prompt_versions` 统一绑定。

GPT使用 `gpt-6-sol`，DeepSeek使用 `deepseek-v4.1-flash`，沿用各自已有凭据变量与路由，不在请求中展示另一裁判或人工分数。请求输入/输出分项额度26624/6144；接收时严格检查输入加输出总计不超过32768，代理忽略分项输出限制的情况单独记录，不隐瞒。当前仅授权固定18答校准，最多72次有界物理请求，无自动传输重试；本次36次已完成，各裁判18条有效。审计及Test160未授权。

当前人工入口和规范结果见实验主目录 `scoring/README.md`；旧人工待确认，原始证据不改。下方均为按时间保留的历史配置说明；其中旧脚本已移到源码 `legacy/`，旧门控统计不可作为当前五档结果，历史276次等额度不用于本次执行。

# 历史双裁判维护（2026-10-23）

活动裁判为 **GPT `gpt-6-sol`** 与 **DeepSeek `deepseek-v4.1-flash`**，分别沿用 `XCM_GPT_API_KEY`、`XCM_DEEPSEEK_API_KEY`，不使用共享 Key。Qwen3-14B 仅用于生成，既有裁判结果只读保留。`judging.yaml` 的 `dual_judge` 与 `execution.yaml` 的 `dual_judge_sol_flash` 为当前范围；旧阶段授权已关闭，历史配置和结果不回写。

两个新模型均已通过精确响应 ID、usage 与两阶段 JSON 契约实测。关闭思考请求仍观察到推理 token/内容，因此使用各自受支持的 `low` 请求参数；HTTP 接受参数不等于独立证明服务端实际推理等级。GPT 使用 `reasoning_effort=low`、`max_completion_tokens`；DeepSeek 使用 `thinking.type=enabled`、`reasoning_effort=low`、`max_tokens`。JSON object 请求配合本地严格 Schema、语义及引用校验，不声称服务端强制 JSON Schema。连接15秒、读取300秒，总输入输出不超过32768 tokens。

入口 `experiments/chapter2_rag_v3/dual_judge.py` 默认 dry-run；`--execute --probes` 与 `--execute --calibration` 才会请求。持久账本、独占锁与模型/阶段白名单限制总计276次物理请求：每模型最多4次验证、108次校准（最多3个 Prompt 候选）、2次受控传输恢复、24次一次性审计。不得删除旧尝试或择优重试。四题审计必须同时具备完整人工两阶段标签与最终配置冻结才能运行；当前尚不具备条件。

负责人已确认 Human Phase1 已完成、Phase2 未进行；只在6题18答上校准。当前不作裁判可靠性通过声明，不启动全面 Dev40 调参或 Test160。结果入口为 `09_dual_judge_sol_flash_20261023_v1/`；其中 AI Phase2 细节保持封存直到独立人工 Phase2 提交。最终保留两个裁判各自 EAS/Strict，综合指标预设为两者 EAS 均值；Unknown 保留区间，缺失不代填。

## 历史 AI 交叉校准记录（2026-10-22）

负责人已调整为先用 GPT、DeepSeek 交叉检查 Qwen，人工验证后置；4 道审计题保持封存。追加调用只限固定 6 题的 18 条匿名回答，Qwen 候选最多 3 个（包含原始 v1）。当前范围与有限技术恢复额度见 `execution.yaml` 的 `ai_cross_calibration_v2`，不授权全面调参或 Test160。

GPT 当前评分路径为 Chat Completions，`reasoning_effort=low`、`max_completion_tokens`；DeepSeek 为 Chat Completions，`thinking.type=enabled`、`reasoning_effort=low`。关闭思考未被实测确认，low 参数接受也不等于内部级别已独立鉴证。连接与读取分别限时，读取最长 300 秒；推理 token 包含在输出预算中，超预算、截断和契约失败不得转成有效分数。

本轮入口为 `experiments/chapter2_rag_v3/ai_cross_calibrate.py`，运行需显式 `--execute` 且通过持久账本、锁和额度检查。既有状态不重发；恢复不得清空账本、删除失败或临时改模型。完成后的 `08_ai_cross_calibration_20261022_v1/EXECUTION_CLOSED.json` 阻止继续请求。所有评分与初始/最终候选的论文证据保存在实验目录，源码库不存真实评分和密钥。`.env` 不复制、不打印、不生成密钥哈希。

## 先前连续执行授权记录（下文保留历史说明）

本轮仅允许三个单次连通性请求、Dev120（120会话、至多1080请求）及六题首轮校准（每裁判18回答、两阶段共至多36请求）。`execution.yaml` 以 `owner_authorized_request_quota_v1` 控制；缺少单价不再阻塞，实际费用没有返回时记录 Unknown。旧金额门禁仍用于未切换到此有限授权模式的配置。无自动重试、模型替换、审计解封或 Test160 调用。

实际生成使用已有 `.local/knowledge-qa-venv/Scripts/python.exe`，由 `continuous_dev120.py` 在 Qwen 连通性通过后执行。`continuous_calibration.py` 在全部120单元产生结果后封存固定30条回答、导出独立Human材料，仅执行连通性及思考模式验证通过的裁判。人工先提交覆盖阶段，再领取事实/条件阶段；AI结果不进入Human目录。


## 先前配置说明（金额门禁及入口状态已由上述授权更新）

# 第2章统一 LLM 配置

本目录是本轮第2章新实验的模型配置入口。密钥、端点、模型参数不再由各新运行脚本单独维护。旧实验的冻结源码和配置只读保留，不回写历史身份，也不得绕过本入口重新执行旧付费脚本。

配置文件采用 **YAML 1.2 的 JSON 子集**，使用标准库解析，无需安装新的 YAML 依赖；修改时保留双引号、逗号和 JSON 的 true/false/null。

|文件|用途|
|---|---|
|providers.yaml|服务商、Base URL、协议、凭据变量与私有文件位置|
|models.yaml|精确请求ID、允许的响应ID、各自思考控制字段和能力证据级别|
|generation.yaml|Dev120三个方法、32K总上下文、工具/token/请求次数预算|
|judging.yaml|四裁判、既定6/4题单、统一Prompt版本、两阶段预算与审计封存|
|execution.yaml|负责人已授权范围、默认dry-run、有限阶段/会话/请求配额|
|.env.example|空凭据模板；不是可用凭据|

## 按模型区分密钥

- GPT-6 Astra：`XCM_GPT_API_KEY`，独立 provider `xcm_gpt`。
- DeepSeek V4 Pro：`XCM_DEEPSEEK_API_KEY`，独立 provider `xcm_deepseek`。
- Qwen3-14B?`QWEN_PROXY_API_KEY`??????????? `.env` ? `.env.private`?
- Qwen3-8B?`QWEN_LOCAL_API_KEY`??????????? `.env` ? `.env.private`??????? `QWEN_LOCAL_8B_BASE_URL`?

**不读取、不回退到共享 `XCM_API_KEY`。** GPT 与 DeepSeek 的计费组、金额上限和账本阶段也分别维护。私有值可以来自进程环境，或本目录未跟踪的 `.env` / `.env.private`；也可分别放在工作区 `.env.xcm_gpt`、`.env.xcm_deepseek`。不要把真实Key发到对话、填入公开YAML、命令参数或报告。本目录 `.env`、`.env.*`（除示例）及 `*.private.yaml/json` 已被Git忽略。

若同一变量在环境与私有文件中存在不同值，加载器停止，不能静默选择一个。Qwen/XCM端点与已注册公开端点不一致同样停止；本地8B端点仅从私有配置读取，不能自动切换到代理或其他模型。公开快照只含配置与其哈希，不复制私有文件、密钥值或其哈希。

## 离线预检与最小验证

从项目根目录执行，`--out` 必须是实验目录下尚不存在的新目录：

```powershell
python experiments/chapter2_rag_v3/central_execution.py --out ../graduation-experiment-results/chapter2_retrieval/rerun_dev40_test160_20261021_v1/06_unified_api_execution_20261022_v1
```

默认只做离线检查：生成去敏配置快照、三模型预检、Dev120配置派生与哈希核验，以及空的持久请求账本。发现预算、凭据、端点问题，退出码2，`STOP.json`明确记载发送0次，不会发送请求。

负责人已经授权三个模型各一次最小验证、Dev120及6题首次AI评分；但没有给出金额硬上限。`execution.yaml` 将**调用范围授权与财务配置分开**。每个阶段须在负责人明确批准后填写 `financial.approved`、`currency`、`hard_limit`、`input_price_per_million`、`output_price_per_million`。金额和单价不得编造，也不能用设为0来绕过。GPT与DeepSeek按各自Key的真实计费组确认单价，不能共用一个假定报价。本次不再计算预测费用。

上述门禁齐备后才可使用 `--execute-connectivity`。每模型一个短文本请求，固定配置参数与模型ID，无 `/v1/models`，不尝试替代模型、参数或接口。单进程锁、跨输出目录不可重复的尝试占位、先持久化预算预留再发送请求；超时、401/403/404、身份不符、截断、格式或usage异常即停止，不自动重试。实际响应、允许的元数据、usage与服务商自带费用字段保存在实验目录，认证头不落盘。

HTTP成功只证明接口接受了请求，不能证明内部推理一定受控。GPT响应应核对reasoning.effort回显；Qwen/DeepSeek检查有无非预期reasoning_content及reasoning tokens。缺少可核实模式证据时保留未确认状态并停止，不按200盲目放行。

## Dev120与四裁判后续入口

`central_execution.py`当前负责配置预检和最小验证，不会在验证命令末尾暗中启动120个会话。Dev120配置由中心派生并绑定已有冻结runner、题单、资源与实现快照；网络授权仍为false。下一步仅在三个验证成功、模式确认、凭据和生成预算齐备后，生成其精确配置SHA授权再启动原有受控runner。不得直接手改历史pending配置或去掉原金额闸门。

新裁判请求构建通过 `judge_api_adapter.py --judge gpt_astra|deepseek|qwen3_14b` 读取此中心，不再使用旧准备版独立profile。当前裁判适配器只有离线build/parse，live评分须后续受控执行接入；尚未执行评分，不可将其称为已完成的AI评分结果。

Dev120未完成时不创建30答封存或可评分的人工作答材料。既有独立人工表只是模板，不能当成模型代填的人评。生成完成后使用既有封存/分阶段导出工具，先交付Human独立材料，再按授权首次运行6题18答×2阶段×3AI；4题审计仍封存。人工提交前不聚合宣布一致性通过，不启动Test160。

当前阻塞及实际状态以新实验 `06_unified_api_execution_20261022_v1/` 为准；先前 `05_api_preparation_20261022_v1/` 中已完成的费用或准备报告仅保留历史，不再继续更新。
