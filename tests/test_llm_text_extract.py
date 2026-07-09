"""Regression: newer Claude models emit a leading ThinkingBlock, so the Anthropic response
text must be pulled from the text block(s), not content[0]. The old code AttributeError'd on
ThinkingBlock.text and silently fell back to Gemini (then hit Gemini's quota)."""

from __future__ import annotations

import types

import pytest

from ai_operator.content.llm_client import LLMError, _extract_text


def _block(kind: str, **kw):
    return types.SimpleNamespace(type=kind, **kw)


def test_extract_text_skips_leading_thinking_block():
    resp = types.SimpleNamespace(content=[
        _block("thinking", thinking="let me reason..."),
        _block("text", text='{"ok": true}'),
    ])
    assert _extract_text(resp) == '{"ok": true}'


def test_extract_text_joins_multiple_text_blocks():
    resp = types.SimpleNamespace(content=[_block("text", text="a"), _block("text", text="b")])
    assert _extract_text(resp) == "ab"


def test_extract_text_plain_response():
    resp = types.SimpleNamespace(content=[_block("text", text="hello")])
    assert _extract_text(resp) == "hello"


def test_extract_text_raises_when_no_text_block():
    resp = types.SimpleNamespace(content=[_block("thinking", thinking="...")])
    with pytest.raises(LLMError):
        _extract_text(resp)
