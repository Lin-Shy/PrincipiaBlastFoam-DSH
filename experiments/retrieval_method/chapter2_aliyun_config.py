"""阿里云第2章在线8B配置；不修改离线deepseek-flash构图配置。"""
from pathlib import Path

BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODELS = {"8b": "qwen3-8b"}


def read_settings(path: Path, *, require_key=True):
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("Invalid Aliyun settings line")
        name, value = (part.strip() for part in line.split("=", 1))
        if name not in {"DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL"} or name in values:
            raise ValueError("Unknown or duplicate Aliyun field")
        values[name] = value.strip('\"\'')
    if values.get("DASHSCOPE_BASE_URL", "").rstrip("/") != BASE_URL:
        raise ValueError("Unexpected Aliyun endpoint; no provider fallback")
    key = values.get("DASHSCOPE_API_KEY", "")
    if require_key and (not key or any(ch.isspace() for ch in key)):
        raise ValueError("Missing or invalid DASHSCOPE_API_KEY")
    return key


def configure_qa(qa, size="8b"):
    model = MODELS[size]
    qa.MODEL = model
    qa.ENDPOINT = BASE_URL + "/chat/completions"

    def request(messages, final=False):
        return {"model": model, "temperature": 0, "enable_thinking": False,
                "max_tokens": 2400 if final else 700,
                "response_format": {"type": "json_object"}, "messages": messages}

    qa.request = request
    return model
