"""ImaRetriever:从 ima 共享知识库读取产品事实与图片。

与 LocalRetriever 实现同一个 Retriever 接口,上层(pipeline / compose / verify)不需要改。
提交前把 RETRIEVER 切到 ima,并在实库上跑一遍全量测试。

检索路径(手册要求):
    search_knowledge 搜型号 → 命中为空时回退 get_knowledge_list 逐级浏览
    → 进入 P1-产品参数库 → 找到型号目录 → 读取其中的条目原文
**搜索为空不等于无权限**,所以回退分支是必须的,不能当作"知识库里没有"。

解析复用 A 的 local_parsers,保证 ima 与本地副本产出同构的 Fact,
不会因为换了检索实现而让事实格式发生变化。

只读:底层 ImaClient 有只读白名单,写接口调用会被直接拒绝。
"""
from __future__ import annotations

import csv
import io
import logging
import os
import re
from pathlib import Path

from agent.contracts import Fact, ImageRef, ModelMatch
from agent.retriever import ima_api, local_parsers as P
from agent.retriever.base import Retriever
from agent.retriever.ima_api import ImaClient, ImaCredentials, ImaError
from agent.retriever.model_index import ModelIndex, normalize

logger = logging.getLogger(__name__)

DEFAULT_KB_NAME = "任德耀新建华为PC知识库"
P1 = "P1-产品参数库"

# 型号目录下的条目:按标题关键词匹配,容忍有无 .md 后缀、前后多余空白
ENTRY_FACTS = "产品事实"
ENTRY_SELLING = "卖点与限制"
ENTRY_IMAGE_INDEX = "图片索引"
ENTRY_PRICE = "官方价格快照"

_IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")


def _entry_matches(title: str, keyword: str) -> bool:
    return keyword in re.sub(r"\.(md|csv)$", "", (title or "").strip())


def _rows_from_csv_text(text: str) -> list[dict]:
    """解析 CSV 文本。ima 下拿到的是内容而非路径,所以不能用 P.read_csv_rows。"""
    text = text.lstrip("﻿")  # 知识库里的 CSV 带 BOM
    return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(io.StringIO(text))]


class ImaRetriever(Retriever):
    """通过 ima OpenAPI 读取知识库。

    kb_name 默认取环境变量 IMA_KB_NAME,再退到举办方共享知识库名。
    creds 可由界面传入(使用者自己填),不传则读环境变量。
    """

    def __init__(
        self,
        creds: ImaCredentials | None = None,
        kb_name: str | None = None,
        aliases_file: Path | None = None,
        client: ImaClient | None = None,
    ):
        self.kb_name = kb_name or os.environ.get("IMA_KB_NAME") or DEFAULT_KB_NAME
        self.client = client or ImaClient(creds)
        self.index = ModelIndex(aliases_file)
        self._kb_id: str | None = None
        self._cache: dict[tuple, object] = {}

    # ---------- 知识库与目录 ----------
    @property
    def kb_id(self) -> str:
        if self._kb_id is None:
            kb = self.client.find_knowledge_base(self.kb_name)
            # api.md 写 `id`,手册实测是 `kb_id`,kb_id_of 兼容两者
            self._kb_id = ima_api.kb_id_of(kb)
            if not self._kb_id:
                raise ImaError(f"知识库「{self.kb_name}」没有返回 id。实际字段:{sorted(kb)}")
            logger.info("已连接 ima 知识库:%s", self.kb_name)  # 不记 kb_id,它只在程序内部使用
        return self._kb_id

    def check_connection(self) -> str:
        """供界面显示连接状态。返回知识库名称;失败时抛 ImaError。"""
        self.kb_id  # noqa: B018  触发一次查找
        return self.kb_name

    def _children(self, folder_id: str | None) -> list[dict]:
        key = ("ls", folder_id or "root")
        if key not in self._cache:
            self._cache[key] = self.client.list_entries(self.kb_id, folder_id)
        return list(self._cache[key])  # type: ignore[arg-type]

    def _find_child_folder(self, parent_id: str | None, name: str) -> dict | None:
        want = normalize(name)
        for e in self._children(parent_id):
            if ima_api.is_folder(e) and normalize(ima_api.entry_title(e)) == want:
                return e
        return None

    def _top_folder(self, name: str, depth: int = 2) -> dict | None:
        """在根层找顶级目录,必要时穿透外层包裹文件夹。

        实测:导入 ima 后根层常只有一个与知识库同名的文件夹,P1~P8 在它下面
        一层。本地副本里 P1~P8 直接位于根层。两种都要能找到。
        """
        hit = self._find_child_folder(None, name)
        if hit is not None:
            return hit
        node: str | None = None
        for _ in range(depth):
            folders = [e for e in self._children(node) if ima_api.is_folder(e)]
            if len(folders) != 1:  # 只穿透单一包裹层,避免误跳进某个兄弟目录
                return None
            node = ima_api.entry_id(folders[0])
            hit = self._find_child_folder(node, name)
            if hit is not None:
                return hit
        return None

    def _walk_folders(self, parent_id: str | None, depth: int = 3) -> list[tuple[dict, str]]:
        """递归列出子孙文件夹,返回 [(文件夹条目, 父ID)]。深度有限,避免遍历整库。"""
        out: list[tuple[dict, str]] = []
        if depth <= 0:
            return out
        for e in self._children(parent_id):
            if ima_api.is_folder(e):
                out.append((e, parent_id or self.kb_id))
                out += self._walk_folders(ima_api.entry_id(e), depth - 1)
        return out

    def _model_folder_id(self, model: str) -> str:
        """定位型号目录。先按 dir 配置逐级进入,失败再在 P1 下按名称搜。"""
        key = ("mf", model)
        if key in self._cache:
            return self._cache[key]  # type: ignore[return-value]
        meta = self.index.require(model)
        p1 = self._top_folder(P1)
        if not p1:
            raise ImaError(f"知识库里找不到目录「{P1}」。请确认已加入正确的共享知识库。")
        node_id = ima_api.entry_id(p1)
        # data/model_aliases.yaml 的 dir 形如 "02-MateBook-Windows/MateBook D 14"
        for part in str(meta["dir"]).split("/"):
            child = self._find_child_folder(node_id, part)
            if child is None:
                node_id = ""
                break
            node_id = ima_api.entry_id(child)
        if not node_id:  # 目录层级与本地副本不一致时,退化为在 P1 下搜同名文件夹
            targets = {normalize(str(meta["dir"]).split("/")[-1]), normalize(model), normalize(meta["official"])}
            for folder, _ in self._walk_folders(ima_api.entry_id(p1)):
                if normalize(ima_api.entry_title(folder)) in targets:
                    node_id = ima_api.entry_id(folder)
                    break
        if not node_id:
            raise ImaError(f"知识库里找不到型号目录:{model}(期望路径 {P1}/{meta['dir']})")
        self._cache[key] = node_id
        return node_id

    def _entry_text(self, model: str, keyword: str) -> tuple[str, str]:
        """读型号目录下某个条目的原文。返回 (文本, 条目标题)。找不到返回 ("", "")。"""
        key = ("txt", model, keyword)
        if key in self._cache:
            return self._cache[key]  # type: ignore[return-value]
        folder_id = self._model_folder_id(model)
        hit = next((e for e in self._children(folder_id) if not ima_api.is_folder(e) and _entry_matches(ima_api.entry_title(e), keyword)), None)
        if hit is None:  # 目录里没有,再用搜索兜一次(标题可能被改成 article.md 之类)
            meta = self.index.require(model)
            for r in self.client.search(self.kb_id, f"{meta['official']} {keyword}"):
                if _entry_matches(ima_api.entry_title(r), keyword):
                    hit = r
                    break
        if hit is None:
            self._cache[key] = ("", "")
            return "", ""
        title = ima_api.entry_title(hit)
        text = self.client.fetch_text(ima_api.entry_id(hit))
        self._cache[key] = (text, title)
        return text, title

    # ---------- Retriever 接口 ----------
    def list_models(self) -> list[str]:
        return self.index.list_models()

    def find_models(self, query: str) -> ModelMatch:
        return self.index.find(query)

    def get_facts(self, model: str) -> list[Fact]:
        key = ("facts", model)
        if key in self._cache:
            return list(self._cache[key])  # type: ignore[arg-type]
        text, title = self._entry_text(model, ENTRY_FACTS)
        if not text:
            raise ImaError(f"知识库里没有「{ENTRY_FACTS}」:{model}")
        meta = self.index.require(model)
        source_path = f"ima://{self.kb_name}/{P1}/{meta['dir']}/{title}"
        facts = P.parse_product_facts(text, model, title, source_path)
        selling, _ = self._entry_text(model, ENTRY_SELLING)
        P.flag_dimension_labels(facts, selling)  # 尺寸标签错位的交叉校验,与本地一致
        self._cache[key] = facts
        return list(facts)

    def get_selling_points(self, model: str) -> dict:
        key = ("sell", model)
        if key in self._cache:
            return dict(self._cache[key])  # type: ignore[arg-type]
        text, title = self._entry_text(model, ENTRY_SELLING)
        if not text:
            raise ImaError(f"知识库里没有「{ENTRY_SELLING}」:{model}")
        meta = self.index.require(model)
        sp = P.parse_selling_points(text)
        sp["source_title"] = title
        sp["source_path"] = f"ima://{self.kb_name}/{P1}/{meta['dir']}/{title}"
        self._cache[key] = sp
        return dict(sp)

    def get_images(self, model: str) -> list[ImageRef]:
        """图片索引登记的图,与型号目录下真实存在的图片条目做交集。

        与本地的差别:ima 下 file_path 是媒体 ID(取链接要再调 get_media_info),
        不是本地路径。界面展示与导出都应通过 image_url() 获取临时链接。
        """
        key = ("img", model)
        if key in self._cache:
            return list(self._cache[key])  # type: ignore[arg-type]
        folder_id = self._model_folder_id(model)

        def images_in(parent_id: str) -> dict[str, str]:
            """某一层里真实存在的图片条目:文件名 -> media_id。"""
            found: dict[str, str] = {}
            for e in self._children(parent_id):
                title = ima_api.entry_title(e)
                if not ima_api.is_folder(e) and title.lower().endswith(_IMG_EXT):
                    found.setdefault(title, ima_api.entry_id(e))
            return found

        def index_rows_in(parent_id: str) -> list[dict]:
            """读某一层自己的图片索引.csv。"""
            hit = next(
                (
                    e
                    for e in self._children(parent_id)
                    if not ima_api.is_folder(e) and _entry_matches(ima_api.entry_title(e), ENTRY_IMAGE_INDEX)
                ),
                None,
            )
            if hit is None:
                return []
            return _rows_from_csv_text(self.client.fetch_text(ima_api.entry_id(hit)))

        # 与本地一致:官网图走 images/图片索引.csv,商城款式图走 商城款式图片/图片索引.csv
        # (后者 7 列、无产品型号列,靠"仅限本型号目录"保证型号正确)
        sources: list[tuple[str, dict[str, str], list[dict], str]] = []
        index_text, index_title = self._entry_text(model, ENTRY_IMAGE_INDEX)
        官网 = self._find_child_folder(folder_id, "images")
        if 官网 is not None and index_text:
            sources.append(
                (
                    "images",
                    images_in(ima_api.entry_id(官网)),
                    _rows_from_csv_text(index_text),
                    f"ima 知识库图片({index_title or ENTRY_IMAGE_INDEX})",
                )
            )
        商城 = self._find_child_folder(folder_id, "商城款式图片")
        if 商城 is not None:
            mall_id = ima_api.entry_id(商城)
            sources.append(
                (
                    "商城款式图片",
                    images_in(mall_id),
                    index_rows_in(mall_id),
                    "华为商城款式图片(商品页,仅限本型号目录)",
                )
            )

        out: list[ImageRef] = []
        seen: set[str] = set()
        for _sub, available, rows, source_label in sources:
            for row in rows:
                name = row.get("文件名", "")
                if not name or name not in available:  # 索引登记但库里没有的,不输出
                    continue
                if row.get("产品型号") and row["产品型号"] != model:  # 型号必须一致
                    continue
                if name in seen:
                    continue
                seen.add(name)
                caption = row.get("官网图片说明") or row.get("画面说明") or P.topic_from_filename(name)
                out.append(
                    ImageRef(
                        filename=name,
                        model=model,
                        source=source_label,
                        caption=caption,
                        suggested_position=P.suggest_position(caption),
                        file_path=available[name],  # ima 下存 media_id,取链接用 image_url()
                        source_page=row.get("来源页面") or row.get("商品页URL", ""),
                    )
                )
        self._cache[key] = out
        return list(out)

    def image_url(self, image: ImageRef) -> str:
        """取图片的临时访问链接。file_path 在 ima 下是 media_id。"""
        url, _ = self.client.media_url(image.file_path)
        return url

    def get_price_records(self, model: str) -> list[dict]:
        """价格快照。空金额保持 None,绝不转 0;价格类型必须随数字一起展示。"""
        self.index.require(model)
        key = ("price",)
        if key not in self._cache:
            text = ""
            p1 = self._top_folder(P1)
            if p1:
                for folder, _ in self._walk_folders(ima_api.entry_id(p1), depth=2):
                    if "价格快照" in ima_api.entry_title(folder):
                        for e in self._children(ima_api.entry_id(folder)):
                            if not ima_api.is_folder(e) and _entry_matches(ima_api.entry_title(e), ENTRY_PRICE):
                                text = self.client.fetch_text(ima_api.entry_id(e))
                                break
                    if text:
                        break
            self._cache[key] = _rows_from_csv_text(text) if text else []
        names = set(self.index.require(model).get("price_names", []))
        out = []
        for row in self._cache[key]:  # type: ignore[union-attr]
            if row.get("规范产品名称") in names:
                rec = dict(row)
                rec["amount"] = _amount(row.get("页面金额（元）", ""))
                rec["reference_amount"] = _amount(row.get("参考或划线金额（元）", ""))
                rec["model"] = model
                out.append(rec)
        return out


def _amount(raw: str):
    raw = (raw or "").strip().replace(",", "").replace("，", "")
    if not raw:
        return None  # 空金额不是 0
    try:
        return float(raw)
    except ValueError:
        return None
