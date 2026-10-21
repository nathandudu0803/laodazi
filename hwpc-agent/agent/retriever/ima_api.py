"""ima OpenAPI 客户端(Python 实现,不依赖 Node)。

为什么不调官方 ima_api.cjs:
  1. 魔搭创空间是 Python 镜像,不保证有 node;
  2. 官方 Skill 包属第三方文件,不随本仓库发布;
  3. 官方脚本每天检查一次 Skill 更新,发现新版本会拒绝发送原请求(返回 -200)。
官方脚本做的事等价于:POST https://ima.qq.com/<path>,带三个请求头,body 为 JSON。
本模块按 ima-skill/knowledge-base/references/api.md 实现同样的调用。

安全约束:
  - 只允许调用读接口(见 READ_ONLY_PATHS)。手册规定参赛者不得删除、修改知识库。
  - 凭证只经请求头发往 ima.qq.com,不写文件、不进日志。异常信息统一脱敏。
  - base_url 固定,不从环境变量读取,避免凭证被指向其他主机。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Iterator

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://ima.qq.com"
BASE_PATH = "openapi/wiki/v1"

# 只读白名单。写接口(create_media / add_knowledge / import_urls / delete 等)一律不实现。
READ_ONLY_PATHS = frozenset(
    {
        "search_knowledge_base",  # 按名称找知识库,取 kb_id
        "get_knowledge_base",  # 知识库详情
        "get_knowledge_list",  # 浏览目录(文件 + 文件夹)
        "search_knowledge",  # 按关键词搜资料
        "get_media_info",  # 取原文访问链接
    }
)

DEFAULT_TIMEOUT = 30.0

# 实测:文件夹条目的 media_type 为 99,media_id 带 "folder_" 前缀
FOLDER_MEDIA_TYPE = 99
FOLDER_ID_PREFIX = "folder_"

# 实测:当日取原文次数用尽时返回此错误码(目录浏览不受限)
QUOTA_EXCEEDED_CODE = 220021


class ImaError(RuntimeError):
    """ima 接口调用失败。message 已脱敏,可直接展示给使用者。"""

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


class ImaAuthError(ImaError):
    """凭证缺失或无效。"""


class ImaQuotaError(ImaError):
    """当日取原文配额已用完。实测 code=220021,目录浏览不受影响,只有读原文受限。"""


@dataclass(frozen=True)
class ImaCredentials:
    """ima 接口凭证。

    支持两种来源:界面上由使用者填写(优先),或环境变量
    IMA_OPENAPI_CLIENTID / IMA_OPENAPI_APIKEY。两者都不写入文件。
    """

    client_id: str
    api_key: str

    @classmethod
    def from_env(cls) -> "ImaCredentials":
        cid = (os.environ.get("IMA_OPENAPI_CLIENTID") or os.environ.get("IMA_CLIENT_ID") or "").strip()
        key = (os.environ.get("IMA_OPENAPI_APIKEY") or os.environ.get("IMA_API_KEY") or "").strip()
        if not cid or not key:
            raise ImaAuthError(
                "缺少 ima 凭证。请在界面填写 Client ID 与 API Key,"
                "或设置环境变量 IMA_OPENAPI_CLIENTID / IMA_OPENAPI_APIKEY。"
                "凭证可在 https://ima.qq.com/agent-interface 获取,须与加入共享知识库的账号一致。"
            )
        return cls(client_id=cid, api_key=key)

    def __repr__(self) -> str:  # 防止凭证随对象被打印进日志
        return "ImaCredentials(client_id='***', api_key='***')"


def _redact(text: str, creds: ImaCredentials | None = None) -> str:
    """去掉可能出现在异常文本里的凭证原值。"""
    out = str(text)
    values = []
    if creds:
        values += [creds.client_id, creds.api_key]
    for name in ("IMA_OPENAPI_CLIENTID", "IMA_OPENAPI_APIKEY", "IMA_CLIENT_ID", "IMA_API_KEY"):
        v = os.environ.get(name)
        if v:
            values.append(v)
    for v in values:
        if v and len(v) >= 6:
            out = out.replace(v, "***")
    return out


class ImaClient:
    """ima 读接口客户端。调用方只需关心返回的 data 字段。"""

    def __init__(self, creds: ImaCredentials | None = None, timeout: float = DEFAULT_TIMEOUT):
        self.creds = creds or ImaCredentials.from_env()
        self._client = httpx.Client(
            base_url=BASE_URL,
            timeout=timeout,
            headers={
                "ima-openapi-clientid": self.creds.client_id,
                "ima-openapi-apikey": self.creds.api_key,
                "ima-openapi-ctx": "skill_version=1.1.10",
                "Content-Type": "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ImaClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def call(self, path: str, body: dict | None = None) -> dict:
        """调用一个读接口,返回 data。path 为接口名,如 search_knowledge_base。"""
        name = path.strip().strip("/").split("/")[-1]
        if name not in READ_ONLY_PATHS:
            raise ImaError(f"拒绝调用非只读接口:{name}。本项目只读取知识库,不做任何写入。")
        try:
            resp = self._client.post(f"/{BASE_PATH}/{name}", json=body or {})
        except httpx.HTTPError as exc:
            raise ImaError(f"网络错误({type(exc).__name__}):{_redact(exc, self.creds)}") from exc
        if resp.status_code in (401, 403):
            raise ImaAuthError(f"凭证被拒绝(HTTP {resp.status_code})。请确认 Client ID 与 API Key 正确且未过期。")
        if resp.status_code != 200:
            raise ImaError(f"接口返回 HTTP {resp.status_code}:{_redact(resp.text[:200], self.creds)}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ImaError("接口返回不是合法 JSON") from exc
        code = payload.get("code")
        if code != 0:
            msg = _redact(payload.get("msg") or "未知错误", self.creds)
            if code == QUOTA_EXCEEDED_CODE:
                raise ImaQuotaError(
                    f"ima 当日取原文次数已用完({msg})。请明天再试,"
                    "或开发期把 RETRIEVER 设为 local 使用本地副本。",
                    code=code,
                )
            raise ImaError(f"ima 返回错误 code={code}:{msg}", code=code)
        return payload.get("data") or {}

    # ---------- 分页 ----------
    def paginate(self, path: str, body: dict, list_key: str, limit: int, max_pages: int = 40) -> Iterator[dict]:
        """翻页取全部条目。ima 的游标字段为 cursor / next_cursor / is_end。"""
        cursor = ""
        for _ in range(max_pages):
            data = self.call(path, {**body, "cursor": cursor, "limit": limit})
            for item in data.get(list_key) or []:
                yield item
            if data.get("is_end") or not data.get("next_cursor"):
                return
            cursor = data["next_cursor"]

    # ---------- 四个读接口 ----------
    def list_knowledge_bases(self) -> list[dict]:
        """列出账号下所有知识库(query 传空字符串)。用于诊断与区分"没加入"和"名字不对"。"""
        return list(self.paginate("search_knowledge_base", {"query": ""}, "info_list", limit=20))

    def find_knowledge_base(self, name: str) -> dict:
        """按名称查找知识库。返回的 dict 用 kb_id_of / kb_name_of 取字段。"""
        matches = list(self.paginate("search_knowledge_base", {"query": name}, "info_list", limit=20))
        if not matches:  # 按名称搜不到,再列全部,便于给出可操作的提示
            everything = self.list_knowledge_bases()
            names = "、".join(kb_name_of(kb) or "?" for kb in everything) or "(无)"
            raise ImaError(
                f"未找到知识库「{name}」。当前账号可见的知识库:{names}。"
                "若为空,请先用 ima 客户端扫码加入举办方共享知识库,并确认接口凭证与该账号一致。"
            )
        exact = [kb for kb in matches if kb_name_of(kb) == name]
        chosen = exact[0] if exact else matches[0]
        if not kb_id_of(chosen):
            raise ImaError(
                f"知识库「{name}」的返回里没有 id 字段。实际字段:{sorted(chosen)}。"
                "接口字段可能又变了,需要更新 kb_id_of。"
            )
        return chosen

    def list_entries(self, kb_id: str, folder_id: str | None = None) -> list[dict]:
        """浏览一层目录。返回的条目既可能是文件也可能是文件夹。"""
        body: dict[str, Any] = {"knowledge_base_id": kb_id}
        if folder_id and folder_id != kb_id:  # 根目录的 folder_id 等于 kb_id,省略即可
            body["folder_id"] = folder_id
        return list(self.paginate("get_knowledge_list", body, "knowledge_list", limit=50))

    def search(self, kb_id: str, query: str) -> list[dict]:
        """按关键词搜索。注意:搜索为空不等于无权限,应回退到 list_entries 逐级浏览。"""
        return list(self.paginate("search_knowledge", {"knowledge_base_id": kb_id, "query": query}, "info_list", limit=50))

    def media_url(self, media_id: str) -> tuple[str, dict]:
        """取原文访问链接。返回 (url, headers);不可访问时返回 ("", {})。"""
        data = self.call("get_media_info", {"media_id": media_id})
        info = data.get("url_info") or {}
        return info.get("url") or "", info.get("headers") or {}

    def fetch_text(self, media_id: str) -> str:
        """取原文文本。链接不可用时抛 ImaError。"""
        url, headers = self.media_url(media_id)
        if not url:
            raise ImaError(f"该条目没有可访问的原文链接(media_id={media_id}),请在 ima 客户端查看原文。")
        try:
            resp = httpx.get(url, headers=headers, timeout=DEFAULT_TIMEOUT, follow_redirects=True)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ImaError(f"下载原文失败({type(exc).__name__})") from exc
        resp.encoding = resp.encoding or "utf-8"
        return resp.text


def kb_id_of(kb: dict) -> str:
    """知识库 ID。

    references/api.md 写的是 `id`,但赛题手册第六节的实测结论是实际返回 `kb_id`、`kb_name`。
    两种都兼容,以免接口字段再变。
    """
    return kb.get("id") or kb.get("kb_id") or ""


def kb_name_of(kb: dict) -> str:
    return kb.get("name") or kb.get("kb_name") or ""


def is_folder(entry: dict) -> bool:
    """目录条目是文件夹还是文件。

    真实接口里 get_knowledge_list 的条目统一只有 media_id,文件夹靠
    media_type == 99 和 media_id 的 "folder_" 前缀区分,没有独立的 folder_id
    字段(folder_id 只出现在 current_path 里)。两种形态都认,以兼容
    api.md 文档所述结构。
    """
    if entry.get("media_type") == FOLDER_MEDIA_TYPE:
        return True
    media_id = str(entry.get("media_id") or "")
    if media_id.startswith(FOLDER_ID_PREFIX):
        return True
    return bool(entry.get("folder_id")) and not media_id


def entry_id(entry: dict) -> str:
    """条目 ID。文件夹取 media_id(形如 folder_123),可直接作为 folder_id 回传。"""
    return entry.get("media_id") or entry.get("folder_id") or ""


def entry_title(entry: dict) -> str:
    return entry.get("name") or entry.get("title") or ""
