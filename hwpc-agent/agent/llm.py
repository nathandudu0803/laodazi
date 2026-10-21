"""OpenAI 兼容大模型封装。配置全走环境变量,日志不打印 Key。"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_KEY_PATTERN = re.compile(r"(sk-[A-Za-z0-9_\-]{6,}|Bearer\s+[A-Za-z0-9_\-\.]{8,})")


class LLMError(RuntimeError):
    """大模型调用失败。"""


def redact(text: str, *extra_secrets: str) -> str:
    """脱敏:去掉疑似密钥,并把已知的 Key 原值替换掉。

    extra_secrets 用于界面填写的凭证 —— 它们不在环境变量里,必须显式传入,
    否则异常文本可能把 Key 带进日志。
    """
    text = _KEY_PATTERN.sub("***", str(text))
    values = [os.environ.get(name) for name in ("LLM_API_KEY", "IMA_OPENAPI_APIKEY", "IMA_OPENAPI_CLIENTID")]
    for val in list(values) + list(extra_secrets):
        if val and len(val) >= 6:
            text = text.replace(val, "***")
    return text


@dataclass(frozen=True)
class LLMConfig:
    """大模型配置。

    支持两种来源:界面上由使用者填写(优先),或环境变量。部署到公开平台时
    用前者,避免所有访客共用同一份额度。配置不写文件、不进日志。
    """

    base_url: str
    api_key: str
    model: str
    timeout: float = 60.0

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            base_url=(os.environ.get("LLM_BASE_URL") or "").strip(),
            api_key=(os.environ.get("LLM_API_KEY") or "").strip(),
            model=(os.environ.get("LLM_MODEL") or "").strip(),
            timeout=float(os.environ.get("LLM_TIMEOUT", "60")),
        )

    def require(self) -> "LLMConfig":
        """校验必填项,缺失时给出可操作的提示。"""
        missing = [
            name
            for name, val in (("Base URL", self.base_url), ("API Key", self.api_key), ("模型名", self.model))
            if not val
        ]
        if missing:
            raise LLMError(f"大模型配置不完整,缺少:{'、'.join(missing)}。请在界面填写,或配置对应环境变量。")
        return self

    def __repr__(self) -> str:  # 防止配置随对象被打印进日志
        return f"LLMConfig(base_url={self.base_url!r}, model={self.model!r}, api_key=***)"


def _client(config: LLMConfig | None = None):
    cfg = (config or LLMConfig.from_env()).require()
    from openai import OpenAI

    return OpenAI(base_url=cfg.base_url, api_key=cfg.api_key, timeout=cfg.timeout, max_retries=0)


def chat(messages: list[dict], retries: int = 3, config: LLMConfig | None = None, **kw) -> str:
    """调用对话接口,返回文本。失败按指数退避重试。

    config 为界面填写的配置;为 None 时回退到环境变量。
    """
    cfg = config or LLMConfig.from_env()
    model = kw.pop("model", None) or cfg.model
    if not model:
        raise LLMError("缺少模型名。请在界面填写,或配置环境变量 LLM_MODEL。")
    client = _client(cfg)
    last: Exception | None = None
    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(model=model, messages=messages, **kw)
            content = resp.choices[0].message.content
            if content is None:
                raise LLMError("模型返回空内容")
            return content
        except Exception as exc:  # noqa: BLE001
            last = exc
            logger.warning("LLM 调用失败(第 %d 次): %s", attempt + 1, redact(exc, cfg.api_key))
            if attempt < retries - 1:
                time.sleep(2**attempt)
    raise LLMError(f"LLM 调用失败: {redact(last, cfg.api_key)}")


def extract_json(text: str):
    """从模型输出中解析 JSON,兼容 ```json 围栏与前后多余文字。"""
    s = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", s, re.S)
    if fence:
        s = fence.group(1).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        i, j = s.find(open_c), s.rfind(close_c)
        if i != -1 and j > i:
            try:
                return json.loads(s[i : j + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError("无法从模型输出解析 JSON")


def chat_json(messages: list[dict], retries: int = 3, config: LLMConfig | None = None, **kw):
    """要求模型输出 JSON,解析失败时带提示重试。"""
    msgs = list(messages)
    last: Exception | None = None
    for _ in range(retries):
        out = chat(msgs, retries=1, config=config, **kw)
        try:
            return extract_json(out)
        except LLMError as exc:
            last = exc
            msgs = msgs + [
                {"role": "assistant", "content": out},
                {"role": "user", "content": "上面的输出不是合法 JSON。请只输出合法 JSON,不要任何解释。"},
            ]
    raise LLMError(f"JSON 输出多次解析失败: {last}")
