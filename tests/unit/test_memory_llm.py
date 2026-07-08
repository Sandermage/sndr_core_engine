# SPDX-License-Identifier: Apache-2.0
"""The OpenAI-compatible completion seam for the memory engine's batch steps."""
from __future__ import annotations

import io
import json

from sndr.memory import llm as llm_mod


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen(captured):
    def _open(req, timeout=None):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.headers)
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _Resp(json.dumps(
            {"choices": [{"message": {"content": "an insight"}}]}
        ).encode("utf-8"))
    return _open


def test_llm_posts_chat_completion(monkeypatch):
    captured = {}
    monkeypatch.setattr(llm_mod.urllib.request, "urlopen", _fake_urlopen(captured))
    fn = llm_mod.make_openai_llm("http://engine:8000", api_key="k", model="qwen")
    out = fn("say hi")
    assert out == "an insight"
    assert captured["url"] == "http://engine:8000/v1/chat/completions"
    assert captured["body"]["model"] == "qwen"
    assert captured["body"]["messages"][0]["content"] == "say hi"
    # thinking disabled so the insight isn't a reasoning dump
    assert captured["body"]["chat_template_kwargs"]["enable_thinking"] is False


def test_llm_appends_v1_once(monkeypatch):
    captured = {}
    monkeypatch.setattr(llm_mod.urllib.request, "urlopen", _fake_urlopen(captured))
    # base already ending in /v1 must not double it
    fn = llm_mod.make_openai_llm("http://engine:8000/v1")
    fn("x")
    assert captured["url"] == "http://engine:8000/v1/chat/completions"


def test_llm_degrades_to_empty_on_error(monkeypatch):
    def _boom(req, timeout=None):
        raise OSError("connection refused")
    monkeypatch.setattr(llm_mod.urllib.request, "urlopen", _boom)
    fn = llm_mod.make_openai_llm("http://engine:8000")
    assert fn("x") == ""
