"""Explicit provider contracts; no arbitrary endpoint or secret in settings."""
import os
import re


QWEN_BEIJING_SHARED_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
QWEN_BEIJING_WORKSPACE_URL = re.compile(
    r"https://[A-Za-z0-9][A-Za-z0-9-]*\.cn-beijing\.maas\.aliyuncs\.com/compatible-mode/v1",
    re.IGNORECASE,
)

PROVIDERS = {
    "deepseek": {"name": "DeepSeek", "url": "https://api.deepseek.com", "env": "DEEPSEEK_API_KEY",
                 "models": {"deepseek-flash": "V4.1 Flash", "deepseek-v4-pro": "V4 Pro"}},
    "kimi": {"name": "Kimi（国际）", "url": "https://api.moonshot.cn/v1", "env": "MOONSHOT_API_KEY",
             "models": {"kimi-k3": "Kimi K3"}},
    "qwen": {"name": "Qwen（北京）", "url": QWEN_BEIJING_SHARED_URL, "env": "DASHSCOPE_API_KEY",
             "models": {"qwen-plus": "Qwen Plus"}},
    "openai": {"name": "OpenAI", "url": "https://api.openai.com/v1", "env": "OPENAI_API_KEY",
               "models": {"gpt-5.4": "GPT-5.4"}},
}

# DeepSeek keeps old identifiers as compatibility routes. Normalize them at
# the configuration boundary so existing data directories continue to work,
# while new requests use the current public identifier.
MODEL_ALIASES = {
    "deepseek-v4-flash": "deepseek-flash",
    "deepseek-v4.1-flash": "deepseek-flash",
}


def resolve_base_url(provider, config):
    """Return the validated API base URL for a provider.

    Qwen Beijing supports the legacy shared DashScope host and the current
    business-space host. Other providers keep their explicit fixed endpoint.
    The returned value never includes ``/chat/completions``; the client adds
    that path when it sends a request.
    """
    info = PROVIDERS[provider]
    raw = config.get("base_url")
    if raw is None:
        return info["url"]
    if not isinstance(raw, str):
        raise ValueError("服务地址必须是文本。")
    value = raw.strip().rstrip("/")
    if not value:
        return info["url"]
    if value == info["url"]:
        return value
    if provider == "qwen" and QWEN_BEIJING_WORKSPACE_URL.fullmatch(value):
        return value
    if provider == "qwen":
        raise ValueError("Qwen 北京服务地址必须是百炼北京共享地址或业务空间专属地址。")
    raise ValueError("服务地址与所选服务商不匹配，请通过模型设置重新选择。")


def selection(config):
    provider = config.get("provider", "deepseek")
    if not isinstance(provider, str) or provider not in PROVIDERS:
        raise ValueError("不支持的模型服务商。")
    info = PROVIDERS[provider]
    raw_model = config.get("model", next(iter(info["models"])))
    model = MODEL_ALIASES.get(raw_model, raw_model) if isinstance(raw_model, str) else raw_model
    thinking = config.get("thinking", False)
    mode = config.get("mode", "live")
    if not isinstance(model, str) or model not in info["models"] or type(thinking) is not bool or mode not in ("demo", "live"):
        raise ValueError("模型、思考模式或运行模式不合法。")
    resolve_base_url(provider, config)
    return {"provider": provider, "model": model, "thinking": thinking, "mode": mode}


def request_body(settings, max_tokens, messages):
    provider, thinking = settings["provider"], settings["thinking"]
    body = {"model": settings["model"], "stream": False, "messages": messages,
            "response_format": {"type": "json_object"}}
    if provider == "openai":
        body.update(max_completion_tokens=max_tokens, reasoning_effort="medium" if thinking else "none")
    else:
        body["max_tokens"] = max_tokens
        if provider == "qwen":
            body["enable_thinking"] = thinking
            if thinking:
                # Qwen Plus JSON mode only supports non-thinking; validate the
                # prompted JSON answer through the same strict workflow validators.
                body.pop("response_format")
        else:
            body["thinking"] = {"type": "enabled" if thinking else "disabled"}
            if provider == "deepseek" and not thinking:
                body["temperature"] = 0.2
    return body


def key_available(provider):
    return bool(os.environ.get(PROVIDERS[provider]["env"], "").strip())
