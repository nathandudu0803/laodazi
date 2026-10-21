"""界面填凭证的处理函数测试。不启动 Gradio、不联网、不需要真实凭证。

重点覆盖:
  - 凭证只进会话状态,不写 os.environ、不写模块级全局
  - 两个会话互不可见(公开部署时不能串号)
  - 状态条与提示文本不泄露凭证原值
  - 缺字段时给出可操作提示,不抛异常
"""
from __future__ import annotations

import os

import pytest

import app as app_mod
from agent.llm import LLMConfig
from agent.retriever.ima_api import ImaError

CID = "test-client-id-123456"
KEY = "test-api-key-abcdefghij"


class FakeRetriever:
    def __init__(self, name="伪知识库", fail=None):
        self._name = name
        self._fail = fail

    def check_connection(self):
        if self._fail:
            raise self._fail
        return self._name


# ---------- 大模型配置 ----------
def test_save_llm_config_keeps_key_in_session_only():
    msg, s = app_mod.save_llm_config("https://api.x.com/v1", KEY, "m-1", app_mod._blank_session())
    assert "已保存" in msg
    assert isinstance(s["llm"], LLMConfig)
    assert s["llm"].api_key == KEY
    assert KEY not in msg, "提示文本不得带出 API Key"
    assert os.environ.get("LLM_API_KEY") != KEY, "不得写入环境变量"


def test_save_llm_config_reports_missing_fields():
    msg, s = app_mod.save_llm_config("", "", "", app_mod._blank_session())
    assert s["llm"] is None
    for field in ("Base URL", "API Key", "模型名"):
        assert field in msg


def test_save_llm_config_does_not_call_the_model(monkeypatch):
    """保存配置不应真实调用,避免消耗额度。"""
    called = []
    monkeypatch.setattr("agent.llm.chat", lambda *a, **k: called.append(1))
    app_mod.save_llm_config("https://api.x.com/v1", KEY, "m-1", app_mod._blank_session())
    assert not called


def test_llm_config_repr_hides_key():
    assert KEY not in repr(LLMConfig(base_url="u", api_key=KEY, model="m"))


# ---------- ima 连接 ----------
def test_connect_stores_retriever_without_touching_env(monkeypatch):
    monkeypatch.setattr(app_mod, "ImaRetriever", lambda **kw: FakeRetriever("任德耀新建华为PC知识库"))
    msg, s = app_mod.connect_knowledge_base(CID, KEY, "", app_mod._blank_session())
    assert "已连接" in msg and "任德耀新建华为PC知识库" in msg
    assert s["retriever"] is not None
    assert CID not in msg and KEY not in msg
    assert os.environ.get("IMA_OPENAPI_APIKEY") != KEY, "不得写入环境变量"


def test_connect_passes_credentials_through(monkeypatch):
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return FakeRetriever()

    monkeypatch.setattr(app_mod, "ImaRetriever", fake)
    app_mod.connect_knowledge_base(CID, KEY, "我的库", app_mod._blank_session())
    assert seen["creds"].client_id == CID
    assert seen["creds"].api_key == KEY
    assert seen["kb_name"] == "我的库"


def test_blank_kb_name_falls_back_to_default(monkeypatch):
    seen = {}
    monkeypatch.setattr(app_mod, "ImaRetriever", lambda **kw: (seen.update(kw), FakeRetriever())[1])
    app_mod.connect_knowledge_base(CID, KEY, "   ", app_mod._blank_session())
    assert seen["kb_name"] is None, "留空应走默认名称,而不是传空字符串"


def test_connect_requires_both_fields():
    msg, s = app_mod.connect_knowledge_base("", KEY, "", app_mod._blank_session())
    assert "Client ID" in msg and s["retriever"] is None
    msg, s = app_mod.connect_knowledge_base(CID, "", "", app_mod._blank_session())
    assert "API Key" in msg and s["retriever"] is None


def test_connect_failure_shows_redacted_message(monkeypatch):
    monkeypatch.setattr(
        app_mod, "ImaRetriever", lambda **kw: FakeRetriever(fail=ImaError("凭证被拒绝(HTTP 403)"))
    )
    msg, s = app_mod.connect_knowledge_base(CID, KEY, "", app_mod._blank_session())
    assert "连接失败" in msg and s["retriever"] is None
    assert CID not in msg and KEY not in msg


def test_unknown_error_shows_type_only(monkeypatch):
    """未知异常只显示类型名,避免原文把凭证带出来。"""

    def boom(**kw):
        raise RuntimeError(f"url contains {KEY}")

    monkeypatch.setattr(app_mod, "ImaRetriever", boom)
    msg, s = app_mod.connect_knowledge_base(CID, KEY, "", app_mod._blank_session())
    assert "RuntimeError" in msg
    assert KEY not in msg, "异常原文不得泄露"
    assert s["retriever"] is None


# ---------- 会话隔离 ----------
def test_sessions_do_not_leak_into_each_other(monkeypatch):
    """公开部署时两个访客的凭证必须互不可见。"""
    monkeypatch.setattr(app_mod, "ImaRetriever", lambda **kw: FakeRetriever())
    _, a = app_mod.save_llm_config("https://a.com/v1", "key-aaaaaa", "m-a", app_mod._blank_session())
    _, b = app_mod.save_llm_config("https://b.com/v1", "key-bbbbbb", "m-b", app_mod._blank_session())
    assert a["llm"].api_key == "key-aaaaaa"
    assert b["llm"].api_key == "key-bbbbbb"
    assert a["llm"] is not b["llm"]


def test_handlers_do_not_mutate_the_input_session(monkeypatch):
    """返回新字典,避免 Gradio 的状态对象被就地改写。"""
    monkeypatch.setattr(app_mod, "ImaRetriever", lambda **kw: FakeRetriever())
    original = app_mod._blank_session()
    _, updated = app_mod.connect_knowledge_base(CID, KEY, "", original)
    assert original["retriever"] is None
    assert updated is not original


# ---------- 状态条 ----------
def test_status_bar_never_shows_credentials():
    _, s = app_mod.save_llm_config("https://api.x.com/v1", KEY, "m-1", app_mod._blank_session())
    s["source"] = "ima 知识库「我的库」"
    text = app_mod.current_status(s)
    assert "m-1" in text and "我的库" in text
    assert KEY not in text and CID not in text


def test_status_bar_handles_empty_session():
    assert "未连接" in app_mod.current_status(None)


# ---------- 未连接时不跑流程 ----------
def test_run_pipeline_requires_a_knowledge_base():
    out = app_mod.run_pipeline("D 14", "", "", "小红书", "", app_mod._blank_session())
    assert "请先" in out[0] and "连接" in out[0]


def test_run_pipeline_requires_product(monkeypatch):
    s = {"retriever": FakeRetriever(), "llm": None, "source": "本地副本"}
    out = app_mod.run_pipeline("", "", "", "小红书", "", s)
    assert "产品型号" in out[0]


def test_run_pipeline_passes_session_llm_config(monkeypatch):
    """界面填的配置必须传进 real_steps,否则等于没生效。"""
    seen = {}

    def fake_real_steps(retriever, llm_config=None, **kw):
        seen["cfg"] = llm_config
        raise RuntimeError("stop here")

    monkeypatch.setattr(app_mod.pipeline, "real_steps", fake_real_steps)
    cfg = LLMConfig(base_url="u", api_key=KEY, model="m")
    s = {"retriever": FakeRetriever(), "llm": cfg, "source": "本地副本"}
    app_mod.run_pipeline("D 14", "", "", "小红书", "", s)
    assert seen["cfg"] is cfg
