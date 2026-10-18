"""OpenAI 兼容大模型封装。配置全走环境变量,日志不打印 Key。"""
from __future__ import annotations

import json
import logging
import os
import re
import time

logger = logging.getLogger(__name__)

_KEY_PATTERN = re.compile(r"(sk-[A-Za-z0-9_\-]{6,}|Bearer\s+[A-Za-z0-9_\-\.]{8,})")


class LLMError(RuntimeError):
    """大模型调用失败。"""


def redact(text: str) -> str:
    """脱敏:去掉疑似密钥,并把当前环境里的 Key 原值替换掉。"""
    text = _KEY_PATTERN.sub("***", str(text))
    for name in ("LLM_API_KEY", "IMA_OPENAPI_APIKEY", "IMA_OPENAPI_CLIENTID"):
        val = os.environ.get(name)
        if val and len(val) >= 6:
            text = text.replace(val, "***")
    return text


def _client():
    base_url = os.environ.get("LLM_BASE_URL")
    api_key = os.environ.get("LLM_API_KEY")
    if not base_url or not api_key:
        raise LLMError("缺少环境变量 LLM_BASE_URL 或 LLM_API_KEY,请参考 .env.example 配置")
    from openai import OpenAI

    timeout = float(os.environ.get("LLM_TIMEOUT", "60"))
    return OpenAI(base_url=base_url, api_key=api_key, timeout=timeout, max_retries=0)


def chat(messages: list[dict], retries: int = 3, **kw) -> str:
    """调用对话接口,返回文本。失败按指数退避重试。"""
    model = kw.pop("model", None) or os.environ.get("LLM_MODEL")
    if not model:
        raise LLMError("缺少环境变量 LLM_MODEL")
    client = _client()
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
            logger.warning("LLM 调用失败(第 %d 次): %s", attempt + 1, redact(exc))
            if attempt < retries - 1:
                time.sleep(2**attempt)
    raise LLMError(f"LLM 调用失败: {redact(last)}")


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


def chat_json(messages: list[dict], retries: int = 3, **kw):
    """要求模型输出 JSON,解析失败时带提示重试。"""
    msgs = list(messages)
    last: Exception | None = None
    for _ in range(retries):
        out = chat(msgs, retries=1, **kw)
        try:
            return extract_json(out)
        except LLMError as exc:
            last = exc
            msgs = msgs + [
                {"role": "assistant", "content": out},
                {"role": "user", "content": "上面的输出不是合法 JSON。请只输出合法 JSON,不要任何解释。"},
            ]
    raise LLMError(f"JSON 输出多次解析失败: {last}")
