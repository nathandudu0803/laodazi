"""A 的 LocalRetriever 测试(最小集;D 之后可扩展)。"""
from pathlib import Path

import pytest

from agent.retriever.local import LocalRetriever

KB = Path(__file__).resolve().parents[2] / "华为PC全板块深度知识库_v7"
pytestmark = pytest.mark.skipif(not KB.exists(), reason="本地知识库副本不存在")


@pytest.fixture(scope="module")
def r():
    return LocalRetriever(KB)


def test_all_ten_models_have_facts_and_images(r):
    models = r.list_models()
    assert len(models) == 10
    for m in models:
        facts = r.get_facts(m)
        assert len(facts) > 20, m
        assert all(f.source_title and f.source_path and f.fact_id for f in facts), m
        imgs = r.get_images(m)
        assert imgs, m
        for i in imgs:
            assert Path(i.file_path).is_file() and i.model == m and i.caption and i.source


def test_fact_ids_unique(r):
    for m in r.list_models():
        ids = [f.fact_id for f in r.get_facts(m)]
        assert len(ids) == len(set(ids)), m


@pytest.mark.parametrize("model", [
    "HUAWEI MateBook D 14 2024", "HUAWEI MateBook D 16 2024",
    "HUAWEI MateBook D 16 SE 版 2024", "HUAWEI MateBook X Pro 酷睿 Ultra 微绒典藏版",
])
def test_dimension_label_flagged(r, model):
    dims = [f for f in r.get_facts(model) if f.field in ("尺寸与重量.长度", "尺寸与重量.宽度", "尺寸与重量.厚度")]
    assert len(dims) == 3 and all(f.review_status == "pending_review" and f.review_note for f in dims)
    assert next(f for f in dims if f.field.endswith("长度")).value  # 原值保留,不自行更正


def test_normal_dimensions_not_flagged(r):
    for m in ("HUAWEI MateBook GT 14", "HUAWEI MateBook Pro", "HUAWEI MateBook 14 酷睿 Ultra"):
        assert all(f.review_status == "ok" for f in r.get_facts(m)), m


def test_multi_config_not_merged(r):
    w = [f.value for f in r.get_facts("HUAWEI MateBook D 16 2024") if f.field == "尺寸与重量.重量"]
    assert len(w) == 2 and any("56 Wh" in v for v in w) and any("70 Wh" in v for v in w)
    ps = [f for f in r.get_facts("HUAWEI MateBook Pro S") if f.field == "尺寸与重量.重量"]
    assert {f.qualifier: f.value for f in ps} == {
        "标准屏版": "798 g", "防窥屏版": "798 g", "柔光屏版": "805 g", "典藏版": "825 g"}
    br = [f for f in r.get_facts("HUAWEI MateBook 14（鸿蒙版）") if f.field == "屏幕.亮度"]
    assert {f.qualifier for f in br} == {"标准版", "柔光版"}


def test_gt_keeps_both_thickness(r):
    h = [f for f in r.get_facts("HUAWEI MateBook GT 14") if f.field == "尺寸与重量.高度"]
    assert h and h[0].value == "15.3 mm" and "18.4" in h[0].footnote


def test_web_noise_filtered(r):
    for m in r.list_models():
        assert not any("即将离开" in f.value or "继续访问" in f.value for f in r.get_facts(m)), m


def test_selling_points_skeleton(r):
    sp = r.get_selling_points("HUAWEI MateBook D 16 2024")
    assert sp["positioning"] and len(sp["angles"]) == 6 and sp["must_ask"]
    assert all(a["conclusion"] and a["boundaries"] for a in sp["angles"])


def test_mall_images_only_for_mh14(r):
    mh14 = r.get_images("HUAWEI MateBook 14（鸿蒙版）")
    assert sum(1 for i in mh14 if i.filename.startswith("vmall_")) == 15
    for m in r.list_models():
        if m != "HUAWEI MateBook 14（鸿蒙版）":
            assert not any(i.filename.startswith("vmall_") for i in r.get_images(m))


def test_price_empty_is_none_not_zero(r):
    recs = r.get_price_records("HUAWEI MateBook D 16 2024")
    assert recs
    for rec in recs:
        assert rec["amount"] is None or rec["amount"] > 0
        assert rec["官方URL"]
    assert any(rec["amount"] is None for rec in recs)
    with_amount = [x for m in r.list_models() for x in r.get_price_records(m) if x["amount"] is not None]
    assert with_amount


@pytest.mark.parametrize("query,expected", [
    ("D14", ["HUAWEI MateBook D 14 2024"]),
    ("华为 MateBook D 16 SE", ["HUAWEI MateBook D 16 SE 版 2024"]),
    ("非凡大师", ["HUAWEI MateBook Fold 非凡大师"]),
    ("GT14", ["HUAWEI MateBook GT 14"]),
    ("MateBook Pro S", ["HUAWEI MateBook Pro S"]),
    ("HUAWEI MateBook Pro", ["HUAWEI MateBook Pro"]),
    ("MateBook 14 鸿蒙版", ["HUAWEI MateBook 14（鸿蒙版）"]),
    ("MateBook 14 酷睿 Ultra", ["HUAWEI MateBook 14 酷睿 Ultra"]),
    ("X Pro", ["HUAWEI MateBook X Pro 酷睿 Ultra 微绒典藏版"]),
])
def test_find_models_exact(r, query, expected):
    m = r.find_models(query)
    assert m.candidates == expected and not m.need_clarify


@pytest.mark.parametrize("query,must_include", [
    ("D系列", {"HUAWEI MateBook D 14 2024", "HUAWEI MateBook D 16 2024"}),
    ("D 16", {"HUAWEI MateBook D 16 2024", "HUAWEI MateBook D 16 SE 版 2024"}),
    ("Pro", {"HUAWEI MateBook Pro", "HUAWEI MateBook Pro S"}),
    ("MateBook 14", {"HUAWEI MateBook 14（鸿蒙版）", "HUAWEI MateBook 14 酷睿 Ultra"}),
])
def test_find_models_ambiguous_asks(r, query, must_include):
    m = r.find_models(query)
    assert m.need_clarify and must_include <= set(m.candidates) and m.clarify_hint


def test_find_models_unknown(r):
    m = r.find_models("我想买一台轻薄本")
    assert m.need_clarify and not m.candidates


def test_unknown_model_raises(r):
    with pytest.raises(KeyError):
        r.get_facts("不存在的型号")
