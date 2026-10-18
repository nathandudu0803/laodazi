"""A 的 pipeline / facts 测试(使用桩,B、C 模块就绪后由 D 扩展)。"""
import os
from pathlib import Path

import pytest

from agent.contracts import Report, TaskInput
from agent.pipeline import Steps, run
from agent.retriever.local import LocalRetriever

_AGENT_ROOT = Path(__file__).resolve().parents[1]
# 与 LocalRetriever 一致:优先读 LOCAL_KB_ROOT,相对路径以 hwpc-agent 为基准
KB = Path(os.environ.get("LOCAL_KB_ROOT") or _AGENT_ROOT.parent / "华为PC全板块深度知识库_v7")
if not KB.is_absolute():
    KB = (_AGENT_ROOT / KB).resolve()
pytestmark = pytest.mark.skipif(not KB.exists(), reason="本地知识库副本不存在")


@pytest.fixture(scope="module")
def r():
    return LocalRetriever(KB)


def task(**kw):
    base = dict(product="D14", audience="大学新生", scene="宿舍写论文", platform="小红书")
    base.update(kw)
    return TaskInput(**base)


def test_end_to_end_stub(r):
    res = run(task(), r)
    assert res.status == "ok" and res.exported and res.draft.used_fact_ids
    assert 3 <= len(res.draft.image_plan) <= 6 or len(res.images) < 3
    assert all(i.model == res.task.model for i in res.draft.image_plan)


def test_ambiguous_model_asks_not_generates(r):
    res = run(task(product="D系列"), r)
    assert res.status == "need_info" and res.questions and res.draft is None


def test_unknown_model_asks(r):
    res = run(task(product="想买轻薄本"), r)
    assert res.status == "need_info" and res.draft is None


def test_missing_audience_scene_asks(r):
    res = run(task(audience="", scene=""), r)
    assert res.status == "need_info" and len(res.questions) == 2 and res.draft is None


def test_missing_platform_asks(r):
    res = run(task(platform=""), r)
    assert res.status == "need_info" and res.draft is None


def test_pending_dimensions_never_usable(r):
    res = run(task(product="D16 SE", extra_requirements="强调轻薄 便携 尺寸"), r)
    assert res.status == "ok"
    assert not any(f.field.startswith("尺寸与重量.") and f.review_status != "ok" for f in res.selection.usable)
    assert {f.field for f in res.selection.pending} >= {"尺寸与重量.长度", "尺寸与重量.宽度", "尺寸与重量.厚度"}
    assert any("待复核" in c for c in res.report.to_confirm)


def test_unsupported_fact_blocks(r):
    def bad_compose(task, scene, plan, sel, images):
        d = Steps().compose(task, scene, plan, sel, images)
        d.used_fact_ids.append("F-fabricated")
        return d
    res = run(task(), r, Steps(compose=bad_compose))
    assert res.status == "blocked" and res.report.blocked and "无依据" in res.report.block_reason
    assert res.exported is None


def test_blocking_compliance_blocks(r):
    res = run(task(), r, Steps(compliance=lambda d: [{"blocking": True, "reason": "虚假承诺"}]))
    assert res.status == "blocked" and res.exported is None


def test_retrieval_failure_blocks(r):
    class Broken(LocalRetriever):
        def get_facts(self, model):
            raise RuntimeError("boom")
    res = run(task(), Broken(KB))
    assert res.status == "blocked" and "检索失败" in res.report.block_reason


def test_retriever_swappable(r):
    """上层只依赖 Retriever 接口:换一个实现,pipeline 不改。"""
    class Wrapped(LocalRetriever):
        pass
    assert run(task(), Wrapped(KB)).status == "ok"
