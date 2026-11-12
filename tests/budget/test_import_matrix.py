"""Import-direction checks over src/skye: Layer ceiling, allowed sets, orchestrator isolation.

Pure static analysis with `ast`: no network, no install, same result for the same tree.
Spec: .kiro/steering/11-design.md (allowed imports); history in .kiro/specs/0-base-structure/design.md (Allowed_Imports_Matrix), Requirements 2.3, 2.5, 2.6,
2.7, 12.3, 12.6, 12.8, 12.9.

Every top-level name below skye is mapped to its Component before the matrix is applied.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "skye"

LAYERS = {"base": 0, "adapters": 1, "services": 2, "runtime": 3}
COMPONENT_LAYER = {
    "base": "base",
    "auth": "base",
    "models": "adapters",
    "store": "adapters",
    "router": "services",
    "tools": "services",
    "prompts": "services",
    "memory": "services",
    "guard": "services",
    "observe": "services",
    "policy": "services",
    "gateway": "runtime",
    "agents": "runtime",
    "teams": "runtime",
    "flows": "runtime",
}

# Maximum set each Component may import (required + optional entries of the design table).
ALLOWED: dict[str, set[str]] = {
    "base": set(),
    # auth does I/O and needs `rsa`; the Layer-0 Components may import only `base`.
    "auth": {"base"},
    "models": {"base", "auth"},
    "store": {"base", "auth"},
    "router": {"base", "models", "store"},
    # The MCP prompt facet uses the message types and Port in base, not the prompts component.
    "tools": {"base", "auth"},
    "prompts": {"base"},
    "memory": {"base", "store", "auth"},
    "guard": {"base", "models"},
    "observe": {"base"},
    "policy": {"base", "models"},
    # The runtime receives the optional services (policy, guard, observe, memory) through
    # base Ports and hooks, never by import.
    "gateway": {"base", "tools", "models", "auth"},
    "agents": {"base", "models"},
    "teams": {"base"},
    "flows": {"base"},
}
OPTIONAL_SERVICES = {"policy", "guard", "observe", "memory"}
RUNTIME = {"gateway", "agents", "teams", "flows"}
ORCHESTRATORS = {"agents", "teams", "flows"}

# Top-level modules that are not Components: they belong to the Layer 0 foundation.
# `utils` is a stdlib-only helper package that lives alongside `base` in Layer 0.
# The public facades (`skye.messages`, `skye.interfaces`, ...) only re-export `base` (decision D34).
NON_COMPONENT_TO_COMPONENT = {
    "utils": "base",
    "messages": "base",
    "completion": "base",
    "exceptions": "base",
    "config": "base",
    "data": "base",
    "dsl": "base",
    "interfaces": "base",
    "plugins": "base",
}


def component_of(parts: tuple[str, ...]) -> str | None:
    """Component owning a module path below skye (('models', 'base') -> 'models')."""
    if not parts:
        return None
    head = parts[0]
    if head in COMPONENT_LAYER:
        return head
    return NON_COMPONENT_TO_COMPONENT.get(head)


def _module_parts(path: Path) -> tuple[str, ...]:
    rel = path.relative_to(SRC).with_suffix("")
    parts = rel.parts
    return parts[:-1] if parts[-1] == "__init__" else parts


def _imports(path: Path) -> list[tuple[str, ...]]:
    """Every skye-internal import in the file, as a path below skye."""
    package = _module_parts(path)
    if path.name != "__init__.py":
        package = package[:-1]
    found: list[tuple[str, ...]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                p = alias.name.split(".")
                if p[0] == "skye":
                    found.append(tuple(p[1:]))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)] if node.level > 1 else package
                mod = tuple(node.module.split(".")) if node.module else ()
                target = tuple(base) + mod
            elif node.module and node.module.split(".")[0] == "skye":
                target = tuple(node.module.split(".")[1:])
            else:
                continue
            if target:
                found.append(target)
            else:  # `from skye import x, y`: each name may be a Component
                found.extend((a.name,) for a in node.names)
    return found


def _label(component: str) -> str:
    return f"{component} (Layer {LAYERS[COMPONENT_LAYER[component]]} {COMPONENT_LAYER[component]})"


def collect_violations() -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for path in sorted(SRC.rglob("*.py")):
        parts = _module_parts(path)
        importer = component_of(parts)
        if importer is None:  # skye/__init__.py: the public façade, not a Component
            continue
        for target in _imports(path):
            imported = component_of(target)
            if imported is None or imported == importer:
                continue
            where = f"{path.relative_to(SRC.parent.parent)}"
            who = f"{_label(importer)} imports {_label(imported)} [{where}]"
            kinds = []
            if LAYERS[COMPONENT_LAYER[imported]] > LAYERS[COMPONENT_LAYER[importer]]:
                kinds.append("upward import")
            if imported not in ALLOWED[importer]:
                kinds.append("out-of-set import")
            if importer in ORCHESTRATORS and imported in ORCHESTRATORS:
                kinds.append("orchestrator cross-import")
            for kind in kinds:
                out.append(
                    {
                        "message": f"{kind}: {who}",
                        "key_importer": parts[0],
                        "key_imported": target[0],
                    }
                )
    return out


def test_matrix_is_well_formed() -> None:
    assert set(ALLOWED) == set(COMPONENT_LAYER)
    for comp, allowed in ALLOWED.items():
        assert comp not in allowed
        assert allowed <= set(COMPONENT_LAYER)
    assert not (ALLOWED["teams"] | ALLOWED["flows"]) & ({"models"} | ORCHESTRATORS)
    # Layer 0 Components import only `base`: the single same-Layer import allowed.
    layer0 = {c for c, layer in COMPONENT_LAYER.items() if layer == "base"}
    for comp in layer0 - {"base"}:
        assert ALLOWED[comp] == {"base"}
    for comp, allowed in ALLOWED.items():
        same = {a for a in allowed if COMPONENT_LAYER[a] == COMPONENT_LAYER[comp]}
        assert same <= {"base"}, f"{comp} may not import same-Layer peers {same}"


def test_policy_is_a_service_and_runtime_never_imports_optional_services() -> None:
    assert COMPONENT_LAYER["policy"] == "services"
    assert {c for c, layer in COMPONENT_LAYER.items() if layer == "services"} == {
        "router", "tools", "prompts", "memory", "guard", "observe", "policy",
    }
    assert {c for c, layer in COMPONENT_LAYER.items() if layer == "runtime"} == RUNTIME
    for comp in RUNTIME:
        assert not ALLOWED[comp] & OPTIONAL_SERVICES, comp


def test_tools_does_not_import_prompts() -> None:
    assert "prompts" not in ALLOWED["tools"]
    assert ALLOWED["tools"] <= {"base", "auth"}


def test_every_module_resolves_to_a_component() -> None:
    unmapped = [
        str(p.relative_to(SRC))
        for p in SRC.rglob("*.py")
        if len(_module_parts(p)) > 0 and component_of(_module_parts(p)) is None
    ]
    assert not unmapped, f"Modules under src/skye owned by no Component: {unmapped}"


def test_no_import_violates_the_matrix() -> None:
    violations = [v["message"] for v in collect_violations()]
    assert not violations, "Import-matrix violations:\n  " + "\n  ".join(violations)
