"""Chapter 2 SiliconFlow settings. Never serialize or print the API key."""
from pathlib import Path

BASE_URL = "https://api.siliconflow.cn/v1"
MODELS = {
    "8b": "Qwen/Qwen3-8B",
    "14b": "Qwen/Qwen3-14B",
    "32b": "Qwen/Qwen3-32B",
}


def read_settings(path: Path, *, require_key: bool = True) -> str:
    """Read the local key without evaluating shell code or accepting unknown settings."""
    if not path or not path.is_file():
        raise ValueError("Chapter 2 SiliconFlow settings file is missing")
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("Invalid Chapter 2 settings line")
        name, value = (part.strip() for part in line.split("=", 1))
        if name not in {"SILICONFLOW_API_KEY", "SILICONFLOW_BASE_URL"} or name in values:
            raise ValueError("Unknown or duplicate Chapter 2 setting: " + name)
        values[name] = value.strip('"\'')
    if values.get("SILICONFLOW_BASE_URL", BASE_URL).rstrip("/") != BASE_URL:
        raise ValueError("Chapter 2 endpoint must be the official SiliconFlow URL")
    key = values.get("SILICONFLOW_API_KEY", "")
    if require_key and (not key or any(ch.isspace() for ch in key)):
        raise ValueError("Fill SILICONFLOW_API_KEY in the Chapter 2 local settings file")
    return key


def configure_qa(qa, size: str) -> str:
    """Apply one identical answer model and request shape to all five arms."""
    model = MODELS[size]
    qa.MODEL = model
    qa.ENDPOINT = BASE_URL + "/chat/completions"

    def request(messages, final=False):
        return {"model": model, "temperature": 0, "enable_thinking": False,
                "max_tokens": 2400 if final else 700,
                "response_format": {"type": "json_object"}, "messages": messages}

    qa.request = request
    return model
