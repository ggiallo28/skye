"""Run every example offline against a fake network (see fake_network.py).

An example that no longer matches the library fails here: a wrong import, a renamed argument, a removed method. Provider keys are
dummy values and every HTTP call is answered by the fake, so nothing leaves the machine.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

import pytest

from tests.budget.measure import ROOT, load_budgets
from tests.examples.fake_network import patched
from tests.unit.plugins.registrar_state import restored_default_registrar

EXAMPLES = ROOT / "examples"
SCRIPTS = sorted(p for p in EXAMPLES.rglob("*.py") if p.name != "__init__.py" and "__pycache__" not in p.parts)

DUMMY_ENV = {
    "OPENAI_API_KEY": "sk-test",
    "ANTHROPIC_API_KEY": "sk-ant-test",
    "AZURE_OPENAI_API_KEY": "az-test",
    "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com",
    "COHERE_API_KEY": "co-test",
    "GOOGLE_API_KEY": "g-test",
    "AWS_ACCESS_KEY_ID": "AKIATEST",
    "AWS_SECRET_ACCESS_KEY": "secret",
    "AWS_REGION": "us-east-1",
    "AWS_DEFAULT_REGION": "us-east-1",
}


def _id(path: Path) -> str:
    return str(path.relative_to(EXAMPLES))


# The plugins example is written against the planned API (plugins:1.1) and fails until the discovery task (plugins:4.5, `skye.use`)
# is done. strict: when it starts to pass, the test fails until this mark is removed, so the mark cannot be forgotten.
EXPECTED_TO_FAIL = {
    "plugins": "waits for plugins:4.5 (skye.use and the registrar); remove this entry when that task is done",
    # A single script is keyed by its path. These two are written against the planned hook API of the agents spec.
    "agents/hooks.py": "waits for the hooks of the agents spec (3-runtime-agents); remove this entry when they exist",
    "agents/hooks_memory.py": "waits for the hooks of the agents spec (3-runtime-agents); remove this entry when they exist",
}
NOT_EXPECTED_TO_FAIL: set[str] = {  # scripts of those folders that already pass (they only need `skye.Plugins`, task 14.3)
    "plugins/template_filter.py",
    "plugins/template_filter_text.py",
    "plugins/tokenizer_provider.py",  # task 15.1: `plugins.provider` with a profile (it needs the kind `provider`)
    "plugins/model_provider.py",  # task 15.2: `plugins.provider` for a model provider (the old kinds are gone)
    "plugins/embedding_provider.py",  # task 15.2: `@plugins.provider` for an embedding provider
    "plugins/decision_model.py",  # task 15.3: `skye.provider(name, provider_type="decision")`
    "plugins/tokenizer.py",  # task 17.1: `plugins.profile` merges a tokenizer into the profile of `openai`
    "plugins/agent_type.py",  # task 16.1: `skye.agent` builds what `plugins.agent` registered
    "plugins/credential_source.py",  # task 16.1: `skye.credential_source` builds what `plugins.credential_source` registered
    "plugins/mcp_client.py",  # task 16.1: `skye.mcp_client` builds what `plugins.mcp_client` registered
    "plugins/routing_strategy.py",  # task 16.1: `skye.routing_strategy` builds what `plugins.routing_strategy` registered
    "plugins/store_backend.py",  # task 16.1: `skye.backend` builds what `plugins.backend` registered
    "plugins/custom_toolkit.py",  # task 18.4: `skye.Toolkit` and `skye.toolkit` build what `plugins.toolkit` registered
}


def with_expected_failures(scripts):
    """The scripts as test parameters, the folders in EXPECTED_TO_FAIL marked as strict expected failures."""
    params = []
    for script in scripts:
        reason = EXPECTED_TO_FAIL.get(_id(script)) or EXPECTED_TO_FAIL.get(script.relative_to(EXAMPLES).parts[0])
        if _id(script) in NOT_EXPECTED_TO_FAIL:
            reason = None
        marks = [pytest.mark.xfail(strict=True, reason=reason)] if reason else []
        params.append(pytest.param(script, marks=marks, id=_id(script)))
    return params


@pytest.mark.parametrize("script", SCRIPTS, ids=_id)
def test_example_compiles(script):
    compile(script.read_text(encoding="utf-8"), str(script), "exec")


# Most examples catch their errors and print them, so an example can drift and still exit cleanly. These markers mean "the example
# failed and said so": a failed call, a traceback, an exception printed by the library. `Expected` marks an error that an example
# provokes on purpose to show how it is handled.
FAILURE_MARKERS = ("❌", "✗", "Traceback", "ProviderError:", "ConfigurationError:", "ValidationError:", "AttributeError", "TypeError", "KeyError")


def _optional_libraries() -> set[str]:
    """The libraries that `import skye` must not import (provider SDKs, optional dependencies): other tests assert they are absent."""
    return set(load_budgets()["load"]["forbidden_at_import"])


def run_offline(script, monkeypatch, capsys) -> str:
    for key, value in DUMMY_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(script.parent)
    monkeypatch.syspath_prepend(str(script.parent))
    before = set(sys.modules)
    try:
        # An example may register a provider of its own (`custom_providers.py`): put the default registrar back as it was.
        with restored_default_registrar(), patched():
            runpy.run_path(str(script), run_name="__main__")
    finally:
        # An example may import an optional library (boto3 for DynamoDB, ...): do not leave it loaded for the tests that follow.
        for name in set(sys.modules) - before:
            if name.split(".")[0] in _optional_libraries():
                del sys.modules[name]
    captured = capsys.readouterr()
    return captured.out + captured.err


@pytest.mark.parametrize("script", with_expected_failures(SCRIPTS))
def test_example_runs_offline(script, monkeypatch, capsys):
    """The example runs to the end against the fake network and does not print a failure."""
    output = run_offline(script, monkeypatch, capsys)
    failures = [
        line.strip()[:140]
        for line in output.splitlines()
        if any(marker in line for marker in FAILURE_MARKERS) and "Expected" not in line
    ]
    assert not failures, f"{_id(script)} printed a failure: {failures[:3]}"


def test_the_failure_markers_catch_a_swallowed_error(tmp_path, monkeypatch, capsys):
    """An example that catches an error and prints it is reported: this is how drift from the library shows up."""
    script = tmp_path / "swallows.py"
    script.write_text('try:\n    {}["x"]\nexcept Exception as e:\n    print(f"❌ Error: {e}")\n', encoding="utf-8")
    output = run_offline(script, monkeypatch, capsys)
    assert any(marker in output for marker in FAILURE_MARKERS)
