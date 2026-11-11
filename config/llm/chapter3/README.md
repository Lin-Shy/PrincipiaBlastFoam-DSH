# 第3章独立模型接入

第3章使用与第2章相同的XCM端点及OpenAI兼容Chat Completions协议，当前用户指定的flash模型在XCM模型列表中对应`deepseek-v4.1-flash`。凭据单独保存在本目录已忽略的`.env.private`，变量为`CHAPTER3_API_KEY`；不得复制或回退到第2章key。

从`.env.example`建立私有配置，设置`CHAPTER3_BASE_URL`、`CHAPTER3_MODEL`和`CHAPTER3_API_KEY`。运行器只读取这一文件，缺少任一项就拒绝启动。它清除继承的其他模型认证变量，仅把独立key通过`PRINCIPIA_CHAPTER3_API_KEY`传给本次DSH子进程；不将key写入profile、报告、公开输入或远端上传包。

本次开发配置采用32768总上下文；初始单次输出上限4096，v10起因max-tokens截断改为8192，最多1次请求重试；这些是开发运行配置，不改第2章冻结协议。DSH原生会话保存模型和工具用量，失败调用中供应商未报告的用量保持未知。没有已知单价时不估造费用。

入口为`experiments/end2end/run_development_sample.py`。每次使用独立运行目录和全新的DSH home，复用已安装的应用bundle与SSH插件，不读取旧home的凭据/模型设置。Windows本地MCP求解关闭，真实操作通过既有SSH工具在Linux工作区完成。
