# 本地 Qwen3 非思考模式核验

2026-10-15：端点、模型名和 Bearer Token 仍取工作区 `.env.qwen_local`，部署说明为工作区 `QWEN_LOCAL_MODELS.md`。不得把密钥写进源码、日志或命令行。

Qwen 官方区分提示中的 `/no_think` 与模板配置的硬开关。vLLM 原始 JSON 请求使用：

```json
{"chat_template_kwargs": {"enable_thinking": false}}
```

依据：[Qwen 的 vLLM 部署说明](https://qwen.readthedocs.io/en/latest/deployment/vllm.html#thinking-non-thinking-modes)。这里的字段直接位于 HTTP 请求体；`extra_body` 是某些 SDK 的参数容器，不是原始 HTTP 的外层字段。

本地 14B 实际检查返回 HTTP 200。相同请求消息按冻结 tokenizer 计数：默认思考模板为 97 token，显式非思考模板为 101 token；服务返回输入量为 101，与显式非思考模板一致。响应格式合法不等于语义正确，检查中的条件判断仍有问题。此前 `/no_think` 单独接入的失败校准保持原身份，不能把新增配置追记为过去已使用。

新增 `chapter2_qwen_hard_nonthinking.py` 在既定结构化输出约束之外明确设置该字段，保留 `/no_think` 后缀、温度 0、输出上限 4096、原始提示和全部判断选项。3项模板配置测试通过；独立开发校准入口为 `chapter2_calibrate_qwen_local_nonthinking.py`，使用完整的42控制/156请求，输出位于活动 `development/local_score_calibration_003/`，请求等待上限为600秒。

该候选尚未获得正式评分验收。其实际输入预算、执行核验和分析登记必须使用显式非思考模板计数，不能继续沿用前两版默认模板的计数。最终必须通过原来的数值及语义验收；不降低门槛，不修补原始判决，不按质量重复请求。

证据：活动 `audit/local_qwen_transition_001/hard_nonthinking_template_verification.json`。原始请求/响应位于同目录 `structured_nonthinking_template_probe_001/`。
