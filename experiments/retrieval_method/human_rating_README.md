# 第2章离线人工五分制评分

本工具读取原冻结48份盲样本，生成双击可用的独立HTML。事实完整正确性、引用支持性各选1–5分或“无法判断”；备注选填，不要求人工写理由。它采用新增量表，不替换旧 `chapter2_human_review*.py` 的二元、强制理由协议。

## 生成页面

从工作区根目录执行，输出必须使用不存在的新目录：

```bash
python3 PrincipiaBlastFoam-DSH/experiments/retrieval_method/chapter2_human_rating.py build \
  --experiment graduation-experiment-results/chapter2_retrieval/aliyun_8b_cross_source_v1 \
  --scores graduation-experiment-results/chapter2_retrieval/aliyun_8b_cross_source_v1/audit/formal_proxy_bounded_postprocess_004_resume_20261004_001/scores_001.json \
  --output /tmp/ch2_human_rating_new
```

生成 `人工评分.html`、`unblind.json`、`使用说明.md` 与来源/产物哈希清单。HTML只内嵌原题、原答、要求、权威证据和引用；不内嵌逐样本模型标签或方法身份。`unblind.json` 单独保存。请先完成并下载48份封存JSON，再通过页面加载此文件。此交付是操作流程约束，不是加密隐藏作者手上的身份文件。

页面不使用CDN、外部字体或联网库；公式以原始LaTeX文本展示。浏览器缓存按样本、模型评分哈希及审阅者代号区分；下载JSON才是可移植的结果。禁止将测试夹具或AI判断作为人工结果导入正式归档。

## 接收人工结果

```bash
python3 PrincipiaBlastFoam-DSH/experiments/retrieval_method/chapter2_human_rating.py analyze \
  --experiment graduation-experiment-results/chapter2_retrieval/aliyun_8b_cross_source_v1 \
  --scores graduation-experiment-results/chapter2_retrieval/aliyun_8b_cross_source_v1/audit/formal_proxy_bounded_postprocess_004_resume_20261004_001/scores_001.json \
  --ratings /path/to/人工评分_审阅者_blind_sealed_时间.json \
  --output /tmp/ch2_human_analysis_new
```

分析只接收全部48份完成且校验通过的封存JSON，输出原人工文件副本、分析JSON、逐样本解盲CSV、Markdown统计和SHA-256清单。原模型未知项及全部冻结分母保留。CSV为查看格式，JSON为权威格式；CSV对公式前缀作转义，JSON保留备注原文。

## 结果格式与解释

- `schema=chapter2-human-rating-v1`；`binding` 包含协议、样本、模型评分SHA-256与48份分母。
- `reviewer` 一次记录代号、是否参与开发、是否此前接触输出；字段为自报信息，不认证真人身份。
- `rows` 保留48份唯一 `blind_id`；`claim_correctness` 与 `citation_support` 为1–5整数、`uncertain`，草稿另允许null；`notes` 可空；`updated_at` 保留UTC时间。
- `status=draft/sealed`；封存绑定创建/完成时间及规范化JSON的 `sealed_payload_sha256`。校验用于检测损坏，不是身份签名。
- `revision_phase=blind/post_unblind`；解盲后修改建立新版本，`parent_seal_sha256` 绑定前一封存版；不得覆盖已下载原版。

统计报告两维分布、均值、有效数和无法判断数。分数不映射pass/fail，不算二元一致率，不将均分认作全量正确率。48会话来自8族，同族相关，首版只提供描述统计。每份评分可查看原始模型严格判断及引用状态，但它们不是同一量表。

当前维护实现只依赖Python标准库，在线模型调用为0。它验证所需冻结输入的哈希与身份，不重建历史在线运行环境或宣称重跑冻结实验。题集、方法、回答、评分和论文结论均不由此工具改写。

## 验证

在DSH项目内运行：

```bash
.venv/bin/python -m pytest tests/test_chapter2_human_rating.py
node --check experiments/retrieval_method/human_rating.js
```

页面交付应额外验证真实浏览器下的评分、缓存恢复、导入冲突、下载封存、解盲和修订，并记录核验结果。评分理由可空是用户本轮指定的新协议，不应通过生成占位理由去适配旧脚本。
