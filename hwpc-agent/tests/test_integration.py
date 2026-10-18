"""A:真实 B、C 模块接入 pipeline 的联调测试(大模型用本地替身,不联网)。"""
import os
from pathlib import Path

import pytest

from agent import compose as compose_mod
from agent.contracts import TaskInput
from agent.pipeline import Steps, real_steps, run
from agent.retriever.local import LocalRetriever

_ROOT = Path(__file__).resolve().parents[1]
KB = Path(os.environ.get("LOCAL_KB_ROOT") or _ROOT.parent / "华为PC全板块深度知识库_v7")
pytestmark = pytest.mark.skipif(not KB.exists(), reason="本地知识库副本不存在")


def fake_llm_compose(r):
    """用 facts 里真实的值拼一个草稿,模拟模型只引用已有事实。"""
    def step(task, scene, plan, sel, images):
        def fake_chat(messages, **kw):
            f = sel.usable[0]
            return {"title": "测试标题", "lead": "导语", "body": f"{f.field}:{f.value}",
                    "used_fact_ids": [f.fact_id], "image_plan": [], "call_to_action": "到店体验", "tags": ["华为"]}
        return compose_mod.compose_draft(task, scene, plan, sel, images, chat_json=fake_chat)
    return step


def test_real_steps_end_to_end():
    r = LocalRetriever(KB)
    st = real_steps(r)
    st.compose = fake_llm_compose(r)
    res = run(TaskInput(product="D14", audience="大学新生", scene="宿舍写论文", platform="小红书"), r, st)
    assert res.status in ("ok", "blocked"), res.trace
    assert res.facts and res.draft is not None
    assert "桩" not in res.draft.title


def test_real_steps_missing_llm_does_not_export(monkeypatch):
    for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(k, raising=False)
    r = LocalRetriever(KB)
    res = run(TaskInput(product="D14", audience="大学新生", scene="宿舍写论文", platform="小红书"), r, real_steps(r))
    assert res.status == "blocked" and "生成失败" in res.report.block_reason and res.exported is None
