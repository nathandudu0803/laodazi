"""LocalRetriever(A):读取本地知识库副本,开发期使用。只读,不改任何知识库文件。

事实只走确定性结构化解析,不做向量/语义检索,不让大模型补事实。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

from agent.contracts import Fact, ImageRef, ModelMatch
from agent.retriever import local_parsers as P
from agent.retriever.base import Retriever

_ROOT_DIR = Path(__file__).resolve().parents[2]
_ALIASES_FILE = _ROOT_DIR / "data" / "model_aliases.yaml"
_P1 = "P1-产品参数库"
_PRICE_REL = f"{_P1}/08-官方公开价格快照/官方价格快照.csv"
_AMOUNT_COLS = ("页面金额（元）", "参考或划线金额（元）")


class KnowledgeBaseError(RuntimeError):
    """本地知识库路径或文件不可用。"""


def _norm(text: str, strip_brand: bool = True) -> str:
    t = text.lower()
    if strip_brand:
        t = t.replace("huawei", "").replace("华为", "")
    return re.sub(r"[\s\-_（）()【】\[\]·,，.。/\\]+", "", t)


def _amount(raw: str):
    raw = (raw or "").strip().replace(",", "").replace("，", "")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


class LocalRetriever(Retriever):
    def __init__(self, kb_root: str | os.PathLike | None = None, aliases_file: Path | None = None):
        root = kb_root or os.environ.get("LOCAL_KB_ROOT") or (_ROOT_DIR.parent / "华为PC全板块深度知识库_v7")
        root = Path(root)
        if not root.is_absolute():
            root = (_ROOT_DIR / root).resolve()
        if not (root / _P1).is_dir():
            raise KnowledgeBaseError(f"本地知识库不可用,找不到 {_P1}。请检查环境变量 LOCAL_KB_ROOT")
        self.root = root
        with open(aliases_file or _ALIASES_FILE, encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh)
        self._models: dict[str, dict] = {m["canonical"]: m for m in cfg["models"]}
        self._ambiguous: dict[str, list[str]] = cfg.get("ambiguous_aliases", {})
        self._pairs: list[dict] = cfg.get("confusable_pairs", [])
        self._cache: dict[tuple, object] = {}
        # (规范化文本, 类型, 型号列表)
        self._index: list[tuple[str, str, list[str]]] = []
        for canon, m in self._models.items():
            self._index.append((_norm(canon), "alias", [canon]))
            self._index.append((_norm(m["official"]), "alias", [canon]))
            for a in m.get("aliases", []):
                self._index.append((_norm(a), "alias", [canon]))
        for key, ms in self._ambiguous.items():
            self._index.append((_norm(key), "ambiguous", list(ms)))

    # ---- 型号解析 ----
    def list_models(self) -> list[str]:
        return list(self._models)

    def model_dir(self, model: str) -> Path:
        self._require(model)
        return self.root / _P1 / self._models[model]["dir"]

    def _require(self, model: str) -> None:
        if model not in self._models:
            raise KeyError(f"未知规范型号: {model}。请先用 find_models 解析")

    def _pair_hint(self, models: list[str]) -> str:
        s = set(models)
        hints = [p["distinguish"] for p in self._pairs if set(p["models"]) & s and len(set(p["models"]) & s) >= 2]
        names = "、".join(models)
        return f"请确认具体型号:{names}。区分依据:" + ";".join(hints) if hints else f"请确认具体型号:{names}"

    def find_models(self, query: str) -> ModelMatch:
        q_full = _norm(query, strip_brand=False)
        for canon in self._models:  # 带品牌词的完整官方名精确命中,视为明确指定
            if q_full == _norm(canon, strip_brand=False) or q_full == _norm(self._models[canon]["official"], strip_brand=False):
                return ModelMatch(candidates=[canon])
        q = _norm(query)
        if not q:
            return ModelMatch(need_clarify=True, clarify_hint="未提供型号,请说明具体产品型号")
        # 收集所有命中区间,长匹配优先、区间不重叠;查询里提到的每个型号都保留,不丢弃
        spans = []
        for k, kind, ms in self._index:
            if not k:
                continue
            start = q.find(k)
            while start != -1:
                spans.append((start, start + len(k), kind, ms))
                start = q.find(k, start + 1)
        if not spans:
            return ModelMatch(need_clarify=True, clarify_hint="未能识别型号,请提供具体型号,例如 MateBook D 14")
        spans.sort(key=lambda s: (-(s[1] - s[0]), s[0]))
        taken: list[tuple[int, int]] = []
        chosen = []
        for s in spans:
            if all(s[1] <= a or s[0] >= b for a, b in taken):
                taken.append((s[0], s[1]))
                chosen.append(s)
        chosen.sort(key=lambda s: s[0])
        cands: list[str] = []
        ambiguous = False
        for _, _, kind, ms in chosen:
            ambiguous = ambiguous or kind == "ambiguous"
            for m in ms:
                if m not in cands:
                    cands.append(m)
        if ambiguous or len(cands) > 1:
            return ModelMatch(candidates=cands, need_clarify=True, clarify_hint=self._pair_hint(cands))
        return ModelMatch(candidates=cands)

    # ---- 事实 ----
    def get_facts(self, model: str) -> list[Fact]:
        key = ("facts", model)
        if key not in self._cache:
            d = self.model_dir(model)
            facts_file, sell_file = d / "产品事实.md", d / "卖点与限制.md"
            if not facts_file.exists():
                raise KnowledgeBaseError(f"缺少 {facts_file.name}: {model}")
            rel = f"{_P1}/{self._models[model]['dir']}/产品事实.md"
            facts = P.parse_product_facts(P.read_text(facts_file), model, "产品事实.md", rel)
            P.flag_dimension_labels(facts, P.read_text(sell_file) if sell_file.exists() else "")
            self._cache[key] = facts
        return list(self._cache[key])

    def get_selling_points(self, model: str) -> dict:
        key = ("sell", model)
        if key not in self._cache:
            f = self.model_dir(model) / "卖点与限制.md"
            if not f.exists():
                raise KnowledgeBaseError(f"缺少 卖点与限制.md: {model}")
            sp = P.parse_selling_points(P.read_text(f))
            sp["source_title"] = "卖点与限制.md"
            sp["source_path"] = f"{_P1}/{self._models[model]['dir']}/卖点与限制.md"
            self._cache[key] = sp
        return dict(self._cache[key])

    # ---- 图片 ----
    def get_images(self, model: str) -> list[ImageRef]:
        key = ("img", model)
        if key in self._cache:
            return list(self._cache[key])
        d = self.model_dir(model)
        rel_dir = f"{_P1}/{self._models[model]['dir']}"
        out: list[ImageRef] = []
        idx = d / "图片索引.csv"
        if idx.exists():
            for row in P.read_csv_rows(idx):
                name = row.get("文件名", "")
                if row.get("产品型号") and row["产品型号"] != model:  # 型号必须与索引一致
                    continue
                path = d / "images" / name
                if not name or not path.is_file():
                    continue
                caption = row.get("官网图片说明") or P.topic_from_filename(name)
                out.append(ImageRef(
                    filename=name, model=model, source=f"华为官网产品页图片(P1 图片索引.csv)",
                    caption=caption, suggested_position=P.suggest_position(caption),
                    file_path=str(path), source_page=row.get("来源页面", ""),
                ))
        mall = d / "商城款式图片" / "图片索引.csv"  # 7 列、无型号列的商城款式表头
        if mall.exists():
            for row in P.read_csv_rows(mall):
                name = row.get("文件名", "")
                path = d / "商城款式图片" / name
                if not name or not path.is_file():
                    continue
                caption = row.get("画面说明") or P.topic_from_filename(name)
                out.append(ImageRef(
                    filename=name, model=model, source="华为商城款式图片(商品页,仅限本型号目录)",
                    caption=caption, suggested_position=P.suggest_position(caption),
                    file_path=str(path), source_page=row.get("商品页URL", ""),
                ))
        self._cache[key] = out
        return list(out)

    # ---- 价格 ----
    def _price_rows(self) -> list[dict]:
        if ("price",) not in self._cache:
            f = self.root / _PRICE_REL
            self._cache[("price",)] = P.read_csv_rows(f) if f.exists() else []
        return self._cache[("price",)]

    def get_price_records(self, model: str) -> list[dict]:
        self._require(model)
        names = set(self._models[model].get("price_names", []))
        out = []
        for row in self._price_rows():
            if row.get("规范产品名称") in names:
                rec = dict(row)  # 原样保留所有字段
                rec["amount"] = _amount(row.get("页面金额（元）", ""))  # 空保持 None,不转 0
                rec["reference_amount"] = _amount(row.get("参考或划线金额（元）", ""))
                rec["model"] = model
                out.append(rec)
        return out
