"""B 的模块测试:平台策略、场景解析、编排。不调用真实大模型,不访问网络。

覆盖手册的判断标准:
  - 换平台:结构 / 语气 / 图片数量 / 行动引导必须同时改变
  - 换场景:切入点必须改变
  - 信息不足:追问而不是生成
  - 模型编造清单外的图片或事实:被丢弃或暴露给核验,不被悄悄接受
"""
from pathlib import Path

import pytest

from agent import compose, platform_rules as pr, scene as sc
from agent.contracts import Fact, ImageRef, TaskInput
from agent.facts import FactSelection


def task(**kw):
    base = dict(product="D14", audience="大学新生", scene="开学季宿舍写论文", platform="小红书", model="HUAWEI MateBook D 14 2024")
    base.update(kw)
    return TaskInput(**base)


def facts(n=6):
    return [
        Fact(fact_id=f"F-{i}", model="HUAWEI MateBook D 14 2024", field=f, value=v, source_title="产品事实.md")
        for i, (f, v) in enumerate(
            [("屏幕.尺寸", "14 英寸"), ("屏幕.比例", "16:10"), ("电池.容量", "56 Wh"),
             ("接口.HDMI", "1 个"), ("尺寸与重量.重量", "约 1.39 kg"), ("操作系统.系统", "Windows 11")][:n]
        )
    ]


def images(model="HUAWEI MateBook D 14 2024"):
    return [
        ImageRef(filename=f"img_{i}.png", model=model, source="P1 图片索引", caption=f"画面{i}", suggested_position="正文")
        for i in range(6)
    ]


# ---------- 平台 ----------
@pytest.mark.parametrize("raw,canon", [("小红书", "小红书"), ("微信公众号", "公众号"), ("门店朋友圈", "朋友圈"), ("门店海报", "海报"), ("发小红书", "小红书")])
def test_platform_alias(raw, canon):
    assert pr.normalize_platform(raw) == canon


def test_unknown_platform_rejected():
    with pytest.raises(pr.UnknownPlatform):
        pr.normalize_platform("抖音")


def test_image_ranges_match_handbook():
    rng = {p: (pr.build_plan(task(platform=p)).image_count_min, pr.build_plan(task(platform=p)).image_count_max) for p in pr.PLATFORMS}
    assert rng == {"公众号": (2, 4), "小红书": (3, 6), "朋友圈": (1, 3), "海报": (1, 1)}


def test_switching_platform_changes_all_four_dimensions():
    plans = [pr.build_plan(task(platform=p)) for p in pr.PLATFORMS]
    assert len({tuple(p.structure) for p in plans}) == 4
    assert len({p.tone for p in plans}) == 4
    assert len({p.call_to_action for p in plans}) == 4
    assert len({(p.image_count_min, p.image_count_max) for p in plans}) == 4


# ---------- 场景 ----------
def test_scene_matches_library_and_stage_is_valid():
    s = sc.parse_scene(task())
    assert s.purchase_stage in sc.VALID_STAGES and not s.missing_info


def test_switching_scene_changes_angle():
    a = sc.build_context(sc.parse_scene(task()), task())
    b_task = task(audience="经常出差的职场人", scene="会议和差旅")
    b = sc.build_context(sc.parse_scene(b_task), b_task)
    assert a.key != b.key and a.angle != b.angle and a.fact_priority != b.fact_priority


def test_missing_info_asks_at_most_three():
    s = sc.parse_scene(task(audience="", scene=""))
    assert 1 <= len(s.missing_info) <= 3


def test_every_scene_has_independent_angle():
    lib = sc.load_library()["scenes"]
    assert len(lib) == 8 and len({v["angle"] for v in lib.values()}) == 8


def test_stage_values_in_library_match_contract():
    lib = sc.load_library()
    assert set(lib["stages"]) == set(sc.VALID_STAGES)
    assert all(v["default_stage"] in sc.VALID_STAGES for v in lib["scenes"].values())


# ---------- 提示词 ----------
def test_eight_prompt_modules_exist():
    text = compose.load_system_prompt()
    for kw in ("角色与任务", "场景理解", "平台规则", "知识库约束", "图片规则", "生成要求", "核验规则", "合规规则"):
        assert kw in text


# ---------- 编排 ----------
def fake_ok(messages, **kw):
    return {
        "strategy": {"切入点": "课程软件清单", "卖点顺序": "系统、接口、屏幕", "不写什么": "续航小时数、价格", "图片安排": "封面屏幕图"},
        "title_options": ["开学买电脑先别看跑分", "新生选本先核对软件", "课程软件清单对一遍"],
        "title": "开学买电脑先别看跑分",
        "lead": "",
        "body": "14 英寸 16:10 的屏幕,约 1.39 kg。",
        "call_to_action": "评论区告诉我你的专业软件",
        "tags": ["电脑选购", "开学季"],
        "image_plan": [{"filename": "img_0.png", "caption": "屏幕", "position": "封面"}],
        "used_fact_ids": ["F-0", "F-4"],
        "pending": [],
    }


def run_compose(fake, plat="小红书", imgs=None, fs=None):
    t = task(platform=plat)
    s = sc.parse_scene(t)
    return compose.compose_draft(t, s, pr.build_plan(t, s), FactSelection(usable=fs or facts()), imgs or images(), chat_json=fake)


def test_compose_returns_draft_with_strategy_and_fact_ids():
    d = run_compose(fake_ok)
    assert d.used_fact_ids == ["F-0", "F-4"] and d.strategy["切入点"] and len(d.title_options) == 3
    assert "内容策略说明" in compose.render_markdown(d)


def test_fabricated_image_is_dropped_not_substituted():
    def fake(m, **kw):
        r = fake_ok(m)
        r["image_plan"] = [{"filename": "not_in_list.png", "caption": "x", "position": "y"}]
        return r
    d = run_compose(fake)
    assert d.image_plan == [] and any("清单之外" in p for p in d.pending)


def test_unknown_fact_id_is_surfaced_for_verification():
    def fake(m, **kw):
        r = fake_ok(m)
        r["used_fact_ids"] = ["F-0", "F-fabricated"]
        return r
    d = run_compose(fake)
    assert "F-fabricated" in d.used_fact_ids and any("不存在的事实点" in p for p in d.pending)


def test_wrong_model_images_never_offered_to_model():
    seen = {}
    def fake(m, **kw):
        seen["prompt"] = m[1]["content"]
        return fake_ok(m)
    run_compose(fake, imgs=images("HUAWEI MateBook D 16 2024"))
    assert "img_0.png" not in seen["prompt"]


def test_pending_facts_are_not_given_to_model():
    bad = Fact(fact_id="F-bad", model="HUAWEI MateBook D 14 2024", field="尺寸与重量.长度", value="18 mm", review_status="pending_review")
    seen = {}
    def fake(m, **kw):
        seen["prompt"] = m[1]["content"]
        return fake_ok(m)
    t = task()
    s = sc.parse_scene(t)
    d = compose.compose_draft(t, s, pr.build_plan(t, s), FactSelection(usable=facts(), pending=[bad]), images(), chat_json=fake)
    assert "F-bad" not in seen["prompt"] and any("待复核" in p for p in d.pending)


def test_model_failure_raises_not_fabricates():
    def boom(m, **kw):
        raise RuntimeError("timeout")
    with pytest.raises(compose.ComposeError):
        run_compose(boom)


def test_insufficient_images_reported():
    d = run_compose(fake_ok, imgs=images()[:1])
    assert any("图片不足" in p for p in d.pending)
