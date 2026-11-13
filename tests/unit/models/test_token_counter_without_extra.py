"""Token counting needs no extra: `import skye` loads no tokenizer, and counting falls back to the estimate (D25, D33)."""

from __future__ import annotations

import subprocess
import sys

from skye.base.messages import UserMessage
from skye.models.token_counter import TokenCounter


def test_import_skye_loads_no_tokenizer():
    code = "import sys, skye; sys.exit(1 if 'tiktoken' in sys.modules else 0)"
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


def test_counting_works_when_tiktoken_is_not_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "tiktoken", None)  # makes `import tiktoken` raise ImportError
    monkeypatch.setattr(TokenCounter, "_tokenizers", {})
    assert TokenCounter.count_tokens("a" * 40, "gpt-4") == 10
    assert TokenCounter.count_message_tokens([UserMessage(content="a" * 40)], "gpt-4") == 13


def test_the_counter_asks_for_the_tokens_extra(monkeypatch):
    asked: list[str | None] = []

    def fake_import(module_name, package_name=None, install_extra=None):
        asked.append(install_extra)
        raise ImportError(module_name)

    monkeypatch.setattr("skye.models.token_counter.LazyImporter.import_module", staticmethod(fake_import))
    monkeypatch.setattr(TokenCounter, "_tokenizers", {})
    TokenCounter.count_tokens("hello", "gpt-4")
    assert asked == ["tokens"]
