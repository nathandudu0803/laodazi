"""型号索引:把用户输入的自由文本解析为规范型号。

从 LocalRetriever 里抽出来的共享实现,因为 ImaRetriever 需要同一套别名与易混淆判断。
数据源是 data/model_aliases.yaml(A 维护)。
local.py 目前仍是自带的同逻辑实现,A 可以改成引用本模块,届时删掉那一份即可。

规则:
  - 匹配前统一:转小写,去空格与标点,去掉 "huawei" / "华为" 这类品牌词。
  - 带品牌词的完整官方名精确命中,视为用户已明确指定,不再追问。
  - 其余情况收集所有命中区间,长匹配优先、区间不重叠,查询里提到的每个型号都保留。
  - 命中泛称(如 "D系列")或命中多个型号时,必须追问,不得自行二选一。
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from agent.contracts import ModelMatch

_DEFAULT_ALIASES = Path(__file__).resolve().parents[2] / "data" / "model_aliases.yaml"
_PUNCT = re.compile(r"[\s\-_（）()【】\[\]·,，.。/\\]+")


def normalize(text: str, strip_brand: bool = True) -> str:
    t = (text or "").lower()
    if strip_brand:
        t = t.replace("huawei", "").replace("华为", "")
    return _PUNCT.sub("", t)


class ModelIndex:
    """型号注册表。只做名称解析,不碰知识库内容。"""

    def __init__(self, aliases_file: Path | None = None):
        with open(aliases_file or _DEFAULT_ALIASES, encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh)
        self.models: dict[str, dict] = {m["canonical"]: m for m in cfg["models"]}
        self._ambiguous: dict[str, list[str]] = cfg.get("ambiguous_aliases", {})
        self._pairs: list[dict] = cfg.get("confusable_pairs", [])
        # (规范化文本, 类型, 型号列表)
        self._index: list[tuple[str, str, list[str]]] = []
        for canon, m in self.models.items():
            for name in [canon, m["official"], *m.get("aliases", [])]:
                self._index.append((normalize(name), "alias", [canon]))
        for key, ms in self._ambiguous.items():
            self._index.append((normalize(key), "ambiguous", list(ms)))

    def list_models(self) -> list[str]:
        return list(self.models)

    def require(self, model: str) -> dict:
        if model not in self.models:
            raise KeyError(f"未知规范型号: {model}。请先用 find_models 解析")
        return self.models[model]

    def _pair_hint(self, models: list[str]) -> str:
        s = set(models)
        hints = [p["distinguish"] for p in self._pairs if len(set(p["models"]) & s) >= 2]
        names = "、".join(models)
        return f"请确认具体型号:{names}。区分依据:" + ";".join(hints) if hints else f"请确认具体型号:{names}"

    def find(self, query: str) -> ModelMatch:
        q_full = normalize(query, strip_brand=False)
        for canon, m in self.models.items():
            if q_full and q_full in {normalize(canon, strip_brand=False), normalize(m["official"], strip_brand=False)}:
                return ModelMatch(candidates=[canon])
        q = normalize(query)
        if not q:
            return ModelMatch(need_clarify=True, clarify_hint="未提供型号,请说明具体产品型号")
        spans: list[tuple[int, int, str, list[str]]] = []
        for key, kind, ms in self._index:
            if not key:
                continue
            start = q.find(key)
            while start != -1:
                spans.append((start, start + len(key), kind, ms))
                start = q.find(key, start + 1)
        if not spans:
            return ModelMatch(need_clarify=True, clarify_hint="未能识别型号,请提供具体型号,例如 MateBook D 14")
        spans.sort(key=lambda s: (-(s[1] - s[0]), s[0]))  # 长匹配优先
        taken: list[tuple[int, int]] = []
        chosen: list[tuple[int, int, str, list[str]]] = []
        for sp in spans:
            if all(sp[1] <= a or sp[0] >= b for a, b in taken):
                taken.append((sp[0], sp[1]))
                chosen.append(sp)
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
