"""Built-in vs external-library boundary rule (structure spec, Requirement 16, task 7.4).

Offline and deterministic. No external-library type may be exposed outside its owning
Component: external types become Skye types at one boundary point, and both implementations
sit behind the same Port returning identical Skye types.

Static (AST) checks over src/skye:
  * provider SDKs (openai, anthropic, vertexai, google.cloud.aiplatform, cohere) are imported
    nowhere in src/skye (Requirement 20); boto3/botocore only by the DynamoDB store backend,
    and only inside a function (lazy);
  * `fastmcp`/`mcp` only by the `tools` MCP files, never at module level;
  * `tools/mcp_boundary.py` imports no third-party library at all;
  * no public function/method annotation names an external-library type.
Runtime check: the `models` public Port method `complete()` (vendor call mocked) and its single
boundary helper `_transform_response`, plus the MCP boundary conversions (fed plain dicts and a
fastmcp-shaped object), all return Skye types only. The same MCP check on a live fake server,
for both clients, is tests/differential/test_boundary_leak.py.
"""

from __future__ import annotations

import ast
import dataclasses
import re
import sys
from unittest.mock import AsyncMock, Mock

import pytest

from tests.budget.measure import ROOT

SRC = ROOT / "src" / "skye"

# external top-level module -> src-relative path prefixes of the owning Component's files
SDK_OWNERS: dict[str, tuple[str, ...]] = {
    # Model providers have no SDK owner: each has one built-in stdlib REST adapter (Requirement 20),
    # so a vendor SDK import anywhere under src/skye is a violation.
    "openai": (),
    "anthropic": (),
    "vertexai": (),
    "google": (),
    "cohere": (),
    # boto3 drives two store backends (a store, not a model provider): DynamoDB and the RDS Data API driver of
    # PostgreSQL (decision D100).
    "boto3": ("store/plugins/dynamodb/backend.py", "store/plugins/postgres/backend.py"),
    "botocore": ("store/plugins/dynamodb/backend.py", "store/plugins/postgres/backend.py"),
    "fastmcp": ("tools/engines/fastmcp/client.py",),
    "mcp": ("tools/engines/fastmcp/client.py",),
}
# Import helpers that take a module name as the first string argument.
IMPORT_CALLS = {"import_module", "missing_extra"}
EXTERNAL = set(SDK_OWNERS)
LIBS_RE = re.compile(r"\b(openai|anthropic|boto3|botocore|vertexai|aiplatform|cohere|fastmcp|mcp\.types|mcp)\b")


def _files():
    for p in sorted(SRC.rglob("*.py")):
        rel = p.relative_to(SRC).as_posix()
        if rel.startswith("agents/"):
            continue
        yield rel, ast.parse(p.read_text(encoding="utf-8"), filename=rel)


def _external_imports(tree: ast.AST):
    """Yield (top-level module, lineno, in_function) for static imports and import-helper calls."""
    def walk(node: ast.AST, in_fn: bool):
        for child in ast.iter_child_nodes(node):
            fn = in_fn or isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            if isinstance(child, ast.Import):
                for a in child.names:
                    yield a.name.split(".")[0], child.lineno, in_fn
            elif isinstance(child, ast.ImportFrom) and child.level == 0 and child.module:
                yield child.module.split(".")[0], child.lineno, in_fn
            elif isinstance(child, ast.Call):
                f = child.func
                name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
                if name in IMPORT_CALLS and child.args and isinstance(child.args[0], ast.Constant) \
                        and isinstance(child.args[0].value, str):
                    yield child.args[0].value.split(".")[0], child.lineno, in_fn
            yield from walk(child, fn)
    yield from walk(tree, False)


def test_external_libraries_imported_only_by_owning_component():
    bad = []
    for rel, tree in _files():
        for mod, line, _ in _external_imports(tree):
            if mod not in EXTERNAL:
                continue
            allowed = set(SDK_OWNERS[mod])
            if rel not in allowed:
                bad.append(f"'{mod}' imported outside its owning Component files: src/skye/{rel}:{line}")
    assert not bad, "\n".join(bad)


def test_external_imports_are_lazy():
    """Never at module level: `import skye` must not load a vendor SDK (Requirement 20)."""
    bad = [f"module-level import of '{mod}': src/skye/{rel}:{line}"
           for rel, tree in _files() for mod, line, in_fn in _external_imports(tree)
           if mod in EXTERNAL and not in_fn]
    assert not bad, "\n".join(bad)


def test_mcp_boundary_has_no_third_party_import():
    tree = ast.parse((SRC / "tools" / "mcp_boundary.py").read_text(encoding="utf-8"))
    stdlib = sys.stdlib_module_names
    bad = [f"{m}:{ln}" for m, ln, _ in _external_imports(tree) if m not in stdlib and m != "skye"]
    for node in ast.walk(tree):  # also every plain import
        if isinstance(node, ast.Import):
            bad += [a.name for a in node.names if a.name.split(".")[0] not in stdlib | {"skye"}]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module \
                and node.module.split(".")[0] not in stdlib | {"skye", "__future__"}:
            bad.append(node.module)
    assert not bad, f"tools/mcp_boundary.py must import no third-party library: {sorted(set(bad))}"


def _public_annotations():
    for rel, tree in _files():
        if not rel.startswith(("models/", "tools/")):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
                anns = [a.annotation for a in node.args.args + node.args.kwonlyargs if a.annotation]
                anns.append(node.returns)
                for a in anns:
                    if a is not None:
                        yield rel, node.lineno, node.name, ast.unparse(a)


def test_public_annotations_name_no_external_type():
    bad = [f"src/skye/{rel}:{ln} {name}() annotation '{text}'"
           for rel, ln, name, text in _public_annotations() if LIBS_RE.search(text)]
    assert not bad, "\n".join(bad)


def _foreign_types(value, seen=None, path="result") -> list[str]:
    """Types in the value tree that are neither Skye nor plain data (e.g. an SDK or a Mock)."""
    seen = seen if seen is not None else set()
    if id(value) in seen:
        return []
    seen.add(id(value))
    mod = type(value).__module__
    if mod.startswith("skye") or mod in {"builtins", "datetime", "enum", "decimal", "uuid"}:
        out: list[str] = []
        if isinstance(value, dict):
            items = list(value.items())
        elif isinstance(value, (list, tuple, set)):
            items = list(enumerate(value))
        elif hasattr(value, "model_dump") or dataclasses.is_dataclass(value):
            items = list(vars(value).items())
        else:
            items = []
        for k, v in items:
            out += _foreign_types(v, seen, f"{path}.{k}")
        return out
    return [f"{path}: {type(value).__module__}.{type(value).__qualname__}"]


def _sdk_shaped_response():
    """An SDK-shaped completion response (a Mock, standing in for an openai object)."""
    resp = Mock(id="c1", model="gpt-4", created=1, system_fingerprint="fp")
    choice = Mock(finish_reason="stop")
    choice.message = Mock(content="hi", tool_calls=None, parsed=None)
    resp.choices = [choice]
    resp.usage = Mock(prompt_tokens=1, completion_tokens=2, total_tokens=3)
    return resp


def test_provider_response_is_skye_types_only():
    """The single boundary point (`_transform_response`) converts an SDK object to a Skye type."""
    from skye.models.plugins.openai.provider import OpenAIProvider

    result = OpenAIProvider(api_key="sk-test")._transform_response(_sdk_shaped_response())
    assert type(result).__module__.startswith("skye")
    assert not _foreign_types(result)


def test_models_public_port_returns_skye_types_only():
    """The `models` public Port method `complete()` returns Skye types, never an SDK object.

    Symmetric with the `tools` runtime check: the only thing mocked is the vendor call
    (`_acall_provider`), so the real boundary conversion runs end-to-end on the public API.
    Guards Requirement 16 for `models` (REST vs SDK) the same way the MCP checks guard `tools`.
    """
    from skye.base.completion import CompleteRequest
    from skye.base.messages import UserMessage
    from skye.models.plugins.openai.provider import OpenAIProvider

    provider = OpenAIProvider(api_key="sk-test")
    provider._acall_provider = AsyncMock(return_value=_sdk_shaped_response())  # type: ignore[method-assign]
    request = CompleteRequest(messages=[UserMessage(content="hi")], model="gpt-4")
    result = provider.complete(request)
    assert type(result).__module__.startswith("skye")
    assert not _foreign_types(result)


class _FastMCPShaped:
    """Stand-in for an `mcp.types` object (pydantic-like), as fastmcp hands them to the boundary."""
    __module__ = "mcp.types"

    def __init__(self, d):
        self._d = d

    def model_dump(self, **_):
        return self._d


@pytest.mark.parametrize("wrap", [lambda d: d, _FastMCPShaped])
def test_mcp_boundary_returns_skye_types_for_dict_and_library_objects(wrap):
    from skye.tools import mcp_boundary as b

    tool = wrap({"name": "add", "description": "d", "inputSchema": {"type": "object", "properties": {}}})
    prompt = wrap({"name": "greet", "arguments": [{"name": "who", "required": True}]})
    resource = wrap({"uri": "file:///a", "name": "a", "mimeType": "text/plain"})
    for out in (b.to_tool_schema(tool), b.to_prompt(prompt), b.to_resource(resource)):
        assert type(out).__module__.startswith("skye"), type(out)
        assert not _foreign_types(out)
