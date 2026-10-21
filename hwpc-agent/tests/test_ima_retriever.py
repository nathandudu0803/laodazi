"""ImaRetriever 与 ima_api 的测试。全部使用假客户端:不联网、不需要凭证。

重点覆盖:
  - 只读白名单:写接口被拒绝
  - 凭证不出现在 repr / 异常文本里
  - 搜索为空时回退到目录浏览(手册明确要求)
  - 图片:索引登记但库里不存在的不输出;型号不一致的不输出
  - 价格:空金额为 None,不转 0
  - ima 与本地产出同构的 Fact(同一套解析器)
"""
from __future__ import annotations

import pytest

from agent.retriever import ima_api
from agent.retriever.ima import ImaRetriever
from agent.retriever.ima_api import ImaClient, ImaCredentials, ImaError
from agent.retriever.model_index import ModelIndex

MODEL = "HUAWEI MateBook D 14 2024"

FACTS_MD = """# HUAWEI MateBook D 14 2024 - 产品事实

## 屏幕

尺寸

14 英寸

## 电池

容量

56 Wh
"""

SELLING_MD = """# HUAWEI MateBook D 14 2024｜卖点与限制

## 一句话定位

适合预算和接口实用性优先的 14 英寸办公用户。

## 六个沟通角度

### 1. 型号身份卡

**可用结论**

14 英寸 16:10 IPS 机型。
"""

IMAGE_CSV = "﻿文件名,产品型号,来源页面,原始图片URL,官网图片说明,宽度,高度,建议用途\n" \
            "a.png,HUAWEI MateBook D 14 2024,https://x,https://y,屏幕展示,100,100,按画面含义使用\n" \
            "missing.png,HUAWEI MateBook D 14 2024,https://x,https://y,不存在的图,100,100,按画面含义使用\n" \
            "other.png,HUAWEI MateBook D 16 2024,https://x,https://y,别的型号,100,100,按画面含义使用\n"

PRICE_CSV = "﻿记录ID,规范产品名称,价格类型,页面金额（元）,参考或划线金额（元）,条件摘要\n" \
            "PRICE-1,HUAWEI MateBook D 14 2024,官方商城页面价,4999,5299,页面含优惠券\n" \
            "PRICE-2,HUAWEI MateBook D 14 2024,官方询价,,,需联系销售\n" \
            "PRICE-9,HUAWEI MateBook D 16 2024,官方商城页面价,5999,,\n"

# 商城款式图片目录自带的索引:7 列,没有产品型号列,靠"仅限本型号目录"保证型号
MALL_CSV = "﻿文件名,商品页URL,原始图片URL,画面说明,宽度,高度,建议用途\n" \
           "v1.png,https://vmall,https://y,樱粉金外观,100,100,按画面含义使用\n" \
           "v_missing.png,https://vmall,https://y,库里不存在,100,100,按画面含义使用\n"


def folder(fid: str, title: str) -> dict:
    """按真实接口形态构造文件夹条目:只有 media_id,靠 media_type 99 区分。"""
    return {"media_id": fid, "title": title, "media_type": ima_api.FOLDER_MEDIA_TYPE}


def doc(mid: str, title: str) -> dict:
    return {"media_id": mid, "title": title, "media_type": 7}


class FakeClient:
    """伪造知识库树。结构按真实接口实测形态:
    条目统一只有 media_id,文件夹的 media_type 为 99、media_id 带 folder_ 前缀;
    且根层有一个与知识库同名的包裹文件夹,P1 在它下面一层。
    """

    def __init__(self, *, search_returns=None, with_image_dir=True, wrapped=True, with_mall=False):
        self.calls: list[tuple[str, dict]] = []
        self._search_returns = search_returns  # None 表示搜索命中为空
        p1_children = [
            folder("folder_win", "02-MateBook-Windows"),
            folder("folder_price", "08-官方公开价格快照"),
        ]
        d14_children = [
            doc("m_facts", "产品事实.md"),
            doc("m_sell", "卖点与限制.md"),
            doc("m_idx", "图片索引.csv"),
        ]
        self.tree = {
            "folder_p1": p1_children,
            "folder_win": [folder("folder_d14", "MateBook D 14")],
            "folder_d14": d14_children,
            "folder_price": [doc("m_price", "官方价格快照.csv")],
            "folder_img": [{"media_id": "m_a", "title": "a.png", "media_type": 9}],
        }
        # 真实库:根层只有一个同名包裹文件夹;本地副本:P1 直接在根层
        if wrapped:
            self.tree["root"] = [folder("folder_wrap", "测试知识库")]
            self.tree["folder_wrap"] = [folder("folder_p1", "P1-产品参数库")]
        else:
            self.tree["root"] = [folder("folder_p1", "P1-产品参数库")]
        if with_image_dir:
            self.tree["folder_d14"] = d14_children + [folder("folder_img", "images")]
        self.texts = {"m_facts": FACTS_MD, "m_sell": SELLING_MD, "m_idx": IMAGE_CSV, "m_price": PRICE_CSV}
        if with_mall:
            # 商城款式图片目录自带一份 7 列、无产品型号列的索引
            self.tree["folder_d14"] = self.tree["folder_d14"] + [folder("folder_mall", "商城款式图片")]
            self.tree["folder_mall"] = [
                doc("m_mall_idx", "图片索引.csv"),
                {"media_id": "m_v1", "title": "v1.png", "media_type": 9},
            ]
            self.texts["m_mall_idx"] = MALL_CSV

    def find_knowledge_base(self, name):
        self.calls.append(("find_kb", {"name": name}))
        # 用手册实测的字段名 kb_id / kb_name,不是 api.md 里写的 id / name
        return {"kb_id": "kb_1", "kb_name": name}

    def list_entries(self, kb_id, folder_id=None):
        self.calls.append(("list", {"folder_id": folder_id}))
        return list(self.tree.get(folder_id or "root", []))

    def search(self, kb_id, query):
        self.calls.append(("search", {"query": query}))
        return list(self._search_returns or [])

    def fetch_text(self, media_id):
        self.calls.append(("fetch", {"media_id": media_id}))
        if media_id not in self.texts:
            raise ImaError(f"没有原文:{media_id}")
        return self.texts[media_id]

    def media_url(self, media_id):
        self.calls.append(("media_url", {"media_id": media_id}))
        return f"https://ima.example/{media_id}", {}


def retriever(**kw) -> ImaRetriever:
    return ImaRetriever(client=FakeClient(**kw), kb_name="测试知识库")


# ---------- 只读与凭证 ----------
def test_write_endpoints_refused():
    client = ImaClient(ImaCredentials(client_id="cid", api_key="key"))
    for path in ("add_knowledge", "create_media", "import_urls", "openapi/wiki/v1/add_knowledge"):
        with pytest.raises(ImaError, match="只读"):
            client.call(path, {})
    client.close()


def test_kb_field_names_tolerate_both_variants():
    """api.md 写 id/name,手册实测是 kb_id/kb_name。两种都要能取到。"""
    assert ima_api.kb_id_of({"kb_id": "k1"}) == "k1"
    assert ima_api.kb_id_of({"id": "k1"}) == "k1"
    assert ima_api.kb_name_of({"kb_name": "库"}) == "库"
    assert ima_api.kb_name_of({"name": "库"}) == "库"
    assert ima_api.kb_id_of({}) == ""


def test_missing_kb_id_lists_actual_fields():
    """字段再变时,报错要带上实际字段名,便于定位。"""
    r = retriever()
    r.client.find_knowledge_base = lambda name: {"unexpected": "x"}
    with pytest.raises(ImaError, match="unexpected"):
        r.check_connection()


def test_read_whitelist_covers_four_required_apis():
    assert {"search_knowledge_base", "get_knowledge_list", "search_knowledge", "get_media_info"} <= ima_api.READ_ONLY_PATHS


def test_credentials_not_leaked_in_repr_or_errors(monkeypatch):
    creds = ImaCredentials(client_id="CID-secret-123456", api_key="KEY-secret-abcdef")
    assert "secret" not in repr(creds)
    monkeypatch.setenv("IMA_OPENAPI_APIKEY", "KEY-secret-abcdef")
    assert "secret" not in ima_api._redact("fail with KEY-secret-abcdef", creds)


def test_missing_credentials_message_is_actionable(monkeypatch):
    for name in ("IMA_OPENAPI_CLIENTID", "IMA_OPENAPI_APIKEY", "IMA_CLIENT_ID", "IMA_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ima_api.ImaAuthError, match="agent-interface"):
        ImaCredentials.from_env()


def test_base_url_is_fixed_not_from_env(monkeypatch):
    """base_url 不从环境变量读,避免凭证被指向其他主机。"""
    monkeypatch.setenv("IMA_BASE_URL", "https://evil.example")
    client = ImaClient(ImaCredentials(client_id="c", api_key="k"))
    assert str(client._client.base_url).rstrip("/") == ima_api.BASE_URL
    client.close()


# ---------- 事实 ----------
def test_facts_parsed_with_ima_source_path():
    facts = retriever().get_facts(MODEL)
    assert facts and all(f.model == MODEL for f in facts)
    assert {f.field for f in facts} >= {"屏幕.尺寸", "电池.容量"}
    assert all(f.source_path.startswith("ima://") for f in facts)
    assert all(f.fact_id for f in facts)


def test_selling_points_have_source():
    sp = retriever().get_selling_points(MODEL)
    assert sp["positioning"] and sp["source_path"].startswith("ima://")


def test_missing_entry_raises_not_silently_empty():
    r = retriever()
    r.client.texts.pop("m_facts")
    r.client.tree["folder_d14"] = [e for e in r.client.tree["folder_d14"] if e.get("media_id") != "m_facts"]
    with pytest.raises(ImaError, match="产品事实"):
        r.get_facts(MODEL)


# ---------- 搜索为空的回退 ----------
def test_empty_search_falls_back_to_browsing():
    """手册:搜索为空不等于无权限,必须回退到目录浏览。"""
    r = retriever()  # FakeClient 默认 search 返回空
    facts = r.get_facts(MODEL)
    assert facts, "搜索为空时应通过逐级浏览取到资料"
    assert any(c[0] == "list" for c in r.client.calls)


def test_folder_lookup_falls_back_to_name_search_when_path_differs():
    r = retriever()
    r.client.tree["folder_win"] = []  # 目录层级与本地副本不一致
    r.client.tree["folder_p1"] = r.client.tree["folder_p1"] + [folder("folder_d14", "MateBook D 14")]
    assert r.get_facts(MODEL), "按配置路径找不到时应在 P1 下按名称搜索"


# ---------- 真实接口形态(2026-10-21 用真实凭证实测) ----------
def test_is_folder_recognizes_real_shape():
    """真实接口里条目只有 media_id,文件夹靠 media_type 99 / folder_ 前缀区分。"""
    assert ima_api.is_folder({"media_id": "folder_1", "title": "P1", "media_type": 99})
    assert ima_api.is_folder({"media_id": "folder_1", "title": "P1"})  # 仅靠前缀
    assert not ima_api.is_folder({"media_id": "markdown_x", "title": "a.md", "media_type": 7})
    assert ima_api.is_folder({"folder_id": "f1", "name": "P1"})  # api.md 文档形态仍兼容


def test_entry_id_prefers_media_id_for_folders():
    """文件夹的 media_id(形如 folder_123)才是可回传的 folder_id。"""
    assert ima_api.entry_id({"media_id": "folder_7", "title": "P1", "media_type": 99}) == "folder_7"


def test_finds_p1_through_same_named_wrapper_folder():
    """导入 ima 后根层只有一个同名包裹文件夹,P1 在它下面一层。"""
    assert retriever(wrapped=True).get_facts(MODEL), "应穿透包裹层找到 P1"


def test_finds_p1_at_root_without_wrapper():
    """本地副本形态:P1 直接在根层,也要能找到。"""
    assert retriever(wrapped=False).get_facts(MODEL)


def test_wrapper_penetration_skips_when_root_is_ambiguous():
    """根层有多个文件夹时不猜,避免误跳进某个兄弟目录。"""
    r = retriever(wrapped=True)
    r.client.tree["root"] = r.client.tree["root"] + [folder("folder_other", "另一个库")]
    with pytest.raises(ImaError, match="P1-产品参数库"):
        r.get_facts(MODEL)


def test_quota_error_is_typed_and_actionable():
    """当日取原文配额用尽(code=220021)要给出可操作提示,不能显示成找不到资料。"""
    assert issubclass(ima_api.ImaQuotaError, ImaError)
    creds = ImaCredentials(client_id="cid", api_key="key")
    client = ImaClient(creds)

    class R:
        status_code = 200

        @staticmethod
        def json():
            return {"code": ima_api.QUOTA_EXCEEDED_CODE, "msg": "资料获取次数已达上限，请明天再尝试"}

    client._client = type("C", (), {"post": lambda self, *a, **k: R()})()
    with pytest.raises(ima_api.ImaQuotaError, match="明天再试"):
        client.call("search_knowledge_base", {})


# ---------- 图片 ----------
def test_mall_images_use_their_own_index():
    """商城款式图片目录自带索引(7 列无型号列),两个来源都要收。"""
    imgs = retriever(with_mall=True).get_images(MODEL)
    names = [i.filename for i in imgs]
    assert names == ["a.png", "v1.png"], f"官网图与商城图都应输出,实际 {names}"
    mall = next(i for i in imgs if i.filename == "v1.png")
    assert mall.caption == "樱粉金外观", "商城索引用画面说明列"
    assert mall.model == MODEL
    assert "商城" in mall.source
    assert "v_missing.png" not in names, "索引登记但库里不存在的不输出"


def test_images_only_existing_and_same_model():
    imgs = retriever().get_images(MODEL)
    names = [i.filename for i in imgs]
    assert names == ["a.png"], "索引登记但库里不存在的、以及型号不一致的都不应输出"
    assert all(i.model == MODEL for i in imgs)
    assert imgs[0].file_path == "m_a" and imgs[0].caption == "屏幕展示"
    assert imgs[0].suggested_position


def test_image_url_resolved_via_media_info():
    r = retriever()
    img = r.get_images(MODEL)[0]
    assert r.image_url(img) == "https://ima.example/m_a"


def test_no_images_when_image_dir_absent():
    assert retriever(with_image_dir=False).get_images(MODEL) == []


# ---------- 价格 ----------
def test_price_empty_amount_is_none_not_zero():
    recs = retriever().get_price_records(MODEL)
    assert [r["记录ID"] for r in recs] == ["PRICE-1", "PRICE-2"], "其他型号的价格不应混入"
    assert recs[0]["amount"] == 4999.0 and recs[0]["reference_amount"] == 5299.0
    assert recs[1]["amount"] is None and recs[1]["reference_amount"] is None
    assert recs[1]["价格类型"] == "官方询价"


# ---------- 型号解析(与本地共用) ----------
def test_model_resolution_shared_with_local():
    r = retriever()
    assert r.find_models("D14").candidates == [MODEL]
    assert r.find_models("D系列").need_clarify
    assert r.find_models("想买轻薄本").need_clarify
    assert len(r.list_models()) == 10


def test_unknown_model_rejected():
    with pytest.raises(KeyError):
        retriever().get_facts("不存在的型号")


def test_model_index_matches_local_behaviour():
    idx = ModelIndex()
    assert idx.find("MateBook 14").need_clarify  # 泛称必须追问
    assert idx.find("HUAWEI MateBook D 14 2024").candidates == [MODEL]
    assert idx.find("D14和D16").need_clarify
