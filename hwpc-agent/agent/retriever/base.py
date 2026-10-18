"""Retriever 抽象接口。LocalRetriever 与 ImaRetriever 都实现它,上层只依赖本接口。"""
from __future__ import annotations

from abc import ABC, abstractmethod

from agent.contracts import Fact, ImageRef, ModelMatch


class Retriever(ABC):
    @abstractmethod
    def find_models(self, query: str) -> ModelMatch:
        """把用户输入解析为规范型号。命中易混淆对且信息不足时返回多候选并置 need_clarify。"""

    @abstractmethod
    def get_facts(self, model: str) -> list[Fact]:
        """返回该型号全部事实,每条带来源;多配置各自独立,不合并。"""

    @abstractmethod
    def get_selling_points(self, model: str) -> dict:
        """返回 {"positioning","angles","must_ask","compliance_examples"},
        angles 每项含 可用结论 / 支撑事实 / 表达边界。"""

    @abstractmethod
    def get_images(self, model: str) -> list[ImageRef]:
        """返回该型号图片,文件必须真实存在且型号一致,不含商城通用图。"""

    @abstractmethod
    def get_price_records(self, model: str) -> list[dict]:
        """返回价格记录原样字段;空金额为 None,不转 0。"""
