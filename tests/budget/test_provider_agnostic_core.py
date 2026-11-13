"""The core stays provider-agnostic (Requirement 9.10): all provider-specific logic lives in the adapter of that provider.

Deterministic, offline, static: parses the source of `base`, `router` and `tools` (the router, the tools and the completion models)
and fails when it finds something that belongs to one provider: its host name, a key of its wire format, one of its adapter classes or
a module of `models/plugins`. The adapters of `models` must not import each other either: adding a provider changes nothing outside its
own folder (D110). This replaces the old script `scripts/validate_provider_architecture.py`, which no one ran.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.budget.measure import ROOT

SRC = ROOT / "src" / "skye"
CORE = ("base", "router", "tools")

PROVIDER_HOSTS = ("openai.com", "anthropic.com", "amazonaws.com", "googleapis.com", "azure.com", "cohere.ai", "cohere.com")
# Keys that only a provider's wire format has. `tool_calls`/`function_call` are the OpenAI data shape that the library accepts
# on purpose (Requirement 9.6), so `base/openai_shape.py` is the one allowed home of them.
WIRE_KEYS = {
    "tool_calls", "function_call", "stop_reason", "stopreason", "inputtokens", "outputtokens",
    "tool_use", "tooluse", "generationconfig", "anthropic_version", "usagemetadata", "candidates",
}
PROVIDER_CLASSES = ("openaiprovider", "anthropicprovider", "bedrockprovider", "googleprovider", "azureopenaiprovider", "cohereprovider")
ALLOWED_WIRE_KEYS = {"base/openai_shape.py": {"tool_calls", "function_call"}}

# Adapter modules of `models`: the folders of `models/plugins` (one per provider, D110) and the two wire-format bases of `models/utilities`. An adapter may use
# the modules of its own provider family (Google embeddings reuse the Google adapter, Azure builds on the OpenAI-compatible base) and nothing of another
# provider. The vendor `__init__.py` files are part of their folder; `models/plugins/__init__.py` belongs to no provider.
ADAPTER_DIRS = ("models/plugins", "models/utilities/openai_compatible", "models/utilities/anthropic_compatible")
FAMILY_OF_FOLDER = {
    "openai": "openai", "azure": "openai", "anthropic": "anthropic", "bedrock": "bedrock", "google": "google", "cohere": "cohere", "typesafe": "typesafe",
}
FAMILY_OF_BASE = {"openai_compatible": "openai", "anthropic_compatible": "anthropic"}
ADAPTER_IMPORT_PREFIXES = ("skye.models.plugins", "skye.models.utilities.openai_compatible", "skye.models.utilities.anthropic_compatible")


def family_of_module(module: str) -> str | None:
    """The provider family of a dotted module path of `models`, or `None` when it belongs to no provider."""
    parts = module.split(".")
    if module.startswith("skye.models.plugins.") and len(parts) > 3:
        return FAMILY_OF_FOLDER.get(parts[3])
    if module.startswith("skye.models.utilities.") and len(parts) > 3:
        return FAMILY_OF_BASE.get(parts[3])
    return None


def family_of_path(rel: str) -> str | None:
    """The provider family of a source file given its path below `skye`."""
    parts = Path(rel).parts
    if parts[:2] == ("models", "plugins") and len(parts) > 3:
        return FAMILY_OF_FOLDER.get(parts[2])
    if parts[:2] == ("models", "utilities") and len(parts) > 3:
        return FAMILY_OF_BASE.get(parts[2])
    return None


def core_violations(source: str, relpath: str) -> list[str]:
    """What in this source of the core belongs to one provider."""
    found: list[str] = []
    allowed = ALLOWED_WIRE_KEYS.get(relpath, set())
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) < 300:
            value = node.value.lower()
            found += [f"host {host!r}" for host in PROVIDER_HOSTS if host in value]
            if value in WIRE_KEYS and value not in allowed:
                found.append(f"wire key {node.value!r}")
        names: list[str] = []
        if isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
        elif isinstance(node, ast.ImportFrom):
            names += [node.module or ""] + [a.name for a in node.names]
        elif isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        for name in names:
            low = name.lower()
            found += [f"provider class {name!r}" for cls in PROVIDER_CLASSES if cls in low]
            if any(low.startswith(prefix) for prefix in ADAPTER_IMPORT_PREFIXES):
                found.append(f"import of the adapters {name!r}")
    return found


def adapter_cross_imports(source: str, own: str | None) -> list[str]:
    """Adapter modules of another provider family that this adapter imports (an adapter knows its own provider only); `own` is its family."""
    mine = own
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        modules: list[str] = []
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
            modules += [f"{node.module}.{a.name}" for a in node.names]
        elif isinstance(node, ast.Import):
            modules += [a.name for a in node.names]
        for module in modules:
            other = family_of_module(module)
            if other is not None and other != mine:
                found.append(module)
    return sorted(set(found))


def _sources(dirs: tuple[str, ...]) -> list[tuple[Path, str]]:
    return [
        (p, str(p.relative_to(SRC)))
        for d in dirs
        for p in sorted((SRC / d).rglob("*.py"))
        if "__pycache__" not in p.parts
    ]


def test_the_core_has_nothing_that_belongs_to_one_provider():
    bad = []
    for path, rel in _sources(CORE):
        for violation in sorted(set(core_violations(path.read_text(encoding="utf-8"), rel))):
            bad.append(f"{rel}: {violation}")
    assert not bad, "provider-specific code in the core (move it into the adapter of that provider): " + "; ".join(bad)


def test_the_adapters_do_not_import_each_other():
    bad = []
    for path, rel in _sources(ADAPTER_DIRS):
        own = family_of_path(rel)
        if own is None:  # models/plugins/__init__.py belongs to no provider
            continue
        for module in adapter_cross_imports(path.read_text(encoding="utf-8"), own):
            bad.append(f"{rel} imports {module}")
    assert not bad, "an adapter imports another adapter (adding a provider must change only its own file): " + "; ".join(bad)


def test_the_detector_finds_what_it_must():
    """It reports each kind of provider-specific content, and accepts the allowed OpenAI data shape."""
    assert core_violations("URL = 'https://api.openai.com/v1'", "router/x.py")
    assert core_violations("body = {'stop_reason': 'end_turn'}", "router/x.py")
    assert core_violations("from skye.models.plugins.openai.provider import OpenAIProvider", "router/x.py")
    assert core_violations("x = BedrockProvider()", "tools/x.py")
    assert not core_violations("x = {'role': 'user'}", "router/x.py")
    assert not core_violations("call = {'tool_calls': []}", "base/openai_shape.py")
    assert core_violations("call = {'tool_calls': []}", "router/x.py")


def test_the_adapter_check_finds_a_cross_import():
    assert adapter_cross_imports("from skye.models.plugins.anthropic.provider import AnthropicProvider", "bedrock")
    assert not adapter_cross_imports("from skye.models.base import BaseModelProvider", "bedrock")
    assert not adapter_cross_imports("from skye.models.plugins.google.provider import GoogleProvider", "google")
