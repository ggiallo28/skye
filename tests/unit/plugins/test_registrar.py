"""The registrar: each kind, duplicates, ``replace``, profiles, lazy text targets and a private
registrar (plugins:2.6)."""

from __future__ import annotations

import re
import sys
import textwrap
from dataclasses import dataclass

import pytest

from skye.base.exceptions import ConfigurationError
from skye.base.interfaces.plugin import RegistrarInterface
from skye.base.plugins import BUILTIN_PLUGINS, KINDS, Registrar, get_registrar
from skye.utils.validation import port_signature_mismatches

_TEXT_RE = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_][\w.]*$")


@dataclass(frozen=True)
class FakeProfile:
    """Stands in for ``ProviderProfile`` (plugins:3.1): the registrar only compares profiles."""

    name: str
    key: str = ""


def register(registrar: Registrar, kind: str, name: str, target: object, **kwargs: object) -> None:
    if kind == "provider":
        kwargs.setdefault(
            "function", "model"
        )  # an object whose methods say nothing needs the function
    getattr(registrar, kind)(name, target, **kwargs)


# -- the Port --


def test_the_registrar_conforms_to_its_port():
    assert port_signature_mismatches(Registrar, RegistrarInterface) == []
    assert isinstance(Registrar(), RegistrarInterface)


def test_the_kinds_are_the_nine_registrar_methods():
    # The nine final kinds (task 15.2): the three old provider kinds are the one kind `provider`.
    methods = {
        n for n, m in vars(RegistrarInterface).items() if not n.startswith("_") and callable(m)
    }
    assert methods == set(KINDS) | {
        "profile"
    }  # the nine kinds and the one call that merges a profile (task 17.1)
    assert set(KINDS) == {
        "provider",
        "backend",
        "credential_source",
        "routing_strategy",
        "mcp_client",
        "tokenizer",
        "template_filter",
        "agent",
        "toolkit",
    }
    assert len(KINDS) == 9
    for gone in ("model_provider", "embedding_provider", "decision_model"):
        assert gone not in KINDS and not hasattr(Registrar(), gone)


def test_a_plugin_registers_through_the_registrar():
    class Acme:
        name = "acme"

        def register(self, registrar: RegistrarInterface) -> None:
            registrar.backend("acme", dict)
            registrar.provider("acme", object, profile=FakeProfile("acme"), function="model")

    registrar = Registrar()
    plugin = Acme()
    plugin.register(registrar)
    assert registrar.get("backend", "acme") is dict
    assert registrar.get("provider", "acme", "model") is object


# -- each kind --


@pytest.mark.parametrize("kind", KINDS)
def test_each_kind_registers_and_looks_up(kind: str):
    registrar = Registrar()
    target = object()
    register(registrar, kind, "mine", target)
    assert registrar.get(kind, "mine") is target
    assert registrar.names(kind) == ["mine"]
    assert registrar.has(kind, "mine")


@pytest.mark.parametrize("kind", KINDS)
def test_kinds_do_not_share_names(kind: str):
    registrar = Registrar()
    register(registrar, kind, "mine", object())
    others = [k for k in KINDS if k != kind]
    assert all(registrar.names(k) == [] for k in others)


def test_names_are_sorted():
    registrar = Registrar()
    for name in ("b", "c", "a"):
        registrar.agent(name, object())
    assert registrar.names("agent") == ["a", "b", "c"]


def test_an_unknown_name_lists_the_names_of_the_kind():
    registrar = Registrar()
    registrar.backend("memory", dict)
    with pytest.raises(ConfigurationError) as caught:
        registrar.get("backend", "nope")
    assert caught.value.details == {"kind": "backend", "name": "nope", "known": ["memory"]}
    assert "memory" in str(caught.value)


def test_an_unknown_kind_is_an_error_that_lists_the_kinds():
    with pytest.raises(ConfigurationError) as caught:
        Registrar().get("flavour", "x")
    assert caught.value.details["kinds"] == list(KINDS)


# -- duplicates and replace --


@pytest.mark.parametrize("kind", KINDS)
def test_a_duplicate_name_names_the_kind_and_the_name(kind: str):
    registrar = Registrar()
    first = object()
    register(registrar, kind, "mine", first)
    with pytest.raises(ConfigurationError) as caught:
        register(registrar, kind, "mine", object())
    expected = {"kind": kind, "name": "mine"}
    if kind == "provider":
        expected["function"] = "model"  # a provider is registered for a function
    assert caught.value.details == expected
    assert kind in str(caught.value) and "'mine'" in str(caught.value)
    assert registrar.get(kind, "mine") is first  # the failed registration changed nothing


def test_replace_overrides_a_name():
    registrar = Registrar()
    registrar.tokenizer("t", object())
    second = object()
    registrar.tokenizer("t", second, replace=True)
    assert registrar.get("tokenizer", "t") is second


def test_the_kind_toolkit_takes_a_class_and_a_replace():
    class Jira:
        pass

    registrar = Registrar()
    registrar.toolkit("jira", Jira)
    assert registrar.get("toolkit", "jira") is Jira
    assert registrar.names("toolkit") == ["jira"] and registrar.has("toolkit", "jira")
    with pytest.raises(ConfigurationError) as caught:
        registrar.toolkit("jira", object())
    assert caught.value.details == {"kind": "toolkit", "name": "jira"}
    second = object()
    registrar.toolkit("jira", second, replace=True)
    assert registrar.get("toolkit", "jira") is second


def test_the_kind_toolkit_has_no_profile_and_no_built_in_yet():
    registrar = Registrar()
    assert registrar.names("toolkit") == []  # no built-in toolkit is registered by this task
    registrar.toolkit("jira", object)
    assert registrar.get_profile("jira") is None
    with pytest.raises(TypeError):
        registrar.toolkit("jira", object, profile=FakeProfile("jira"), replace=True)


def test_the_same_name_in_two_kinds_is_not_a_duplicate():
    registrar = Registrar()
    registrar.provider("openai", object(), function="model")
    registrar.provider("openai", object(), function="embedding")
    registrar.backend("openai", object())


@pytest.mark.parametrize("bad", ["", None, 3])
def test_a_name_must_be_a_non_empty_string(bad):
    with pytest.raises(ConfigurationError):
        Registrar().agent(bad, object())


def test_a_target_is_required():
    with pytest.raises(ConfigurationError):
        Registrar().agent("x", None)


# -- profiles --


def test_the_same_profile_given_twice_is_accepted():
    registrar = Registrar()
    registrar.provider("acme", object, profile=FakeProfile("acme", "K"), function="model")
    registrar.provider(
        "acme", object, profile=FakeProfile("acme", "K"), function="embedding"
    )  # equal, not identical
    assert registrar.get_profile("acme") == FakeProfile("acme", "K")


def test_two_different_profiles_for_one_provider_name_raise():
    registrar = Registrar()
    registrar.provider("acme", object, profile=FakeProfile("acme", "K1"), function="model")
    with pytest.raises(ConfigurationError) as caught:
        registrar.provider("acme", object, profile=FakeProfile("acme", "K2"), function="embedding")
    assert caught.value.details["name"] == "acme"
    assert registrar.get_profile("acme") == FakeProfile("acme", "K1")
    assert registrar.names("provider", "embedding") == []  # nothing was registered


def test_replace_overrides_the_profile_too():
    registrar = Registrar()
    registrar.provider("acme", object, profile=FakeProfile("acme", "K1"), function="model")
    registrar.provider(
        "acme", object, profile=FakeProfile("acme", "K2"), replace=True, function="model"
    )
    assert registrar.get_profile("acme").key == "K2"


def test_a_provider_without_a_profile_has_none_and_does_not_drop_one():
    registrar = Registrar()
    assert registrar.get_profile("acme") is None
    registrar.provider("acme", object, profile=FakeProfile("acme"), function="model")
    registrar.provider("acme", object, function="embedding")
    assert registrar.get_profile("acme") == FakeProfile("acme")


# -- text targets, imported at the first use --


@pytest.fixture
def lazy_module(tmp_path, monkeypatch):
    """A module that records that it was imported, and never is until a name is looked up."""
    (tmp_path / "lazy_plugin_target.py").write_text(
        textwrap.dedent(
            """
            IMPORTED = True

            class Backend:
                pass

            class Outer:
                class Inner:
                    pass
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("lazy_plugin_target", None)
    yield "lazy_plugin_target"
    sys.modules.pop("lazy_plugin_target", None)


def test_a_text_target_is_not_imported_at_registration(lazy_module):
    registrar = Registrar()
    registrar.backend("lazy", f"{lazy_module}:Backend")
    assert lazy_module not in sys.modules
    assert registrar.names("backend") == ["lazy"]  # listing does not import either
    assert registrar.has("backend", "lazy")
    assert lazy_module not in sys.modules


def test_a_text_target_is_imported_at_the_first_use_and_once(lazy_module):
    registrar = Registrar()
    registrar.backend("lazy", f"{lazy_module}:Backend")
    first = registrar.get("backend", "lazy")
    assert lazy_module in sys.modules
    assert first.__name__ == "Backend"
    assert registrar.get("backend", "lazy") is first


def test_a_toolkit_text_target_is_imported_at_the_first_use(lazy_module):
    registrar = Registrar()
    registrar.toolkit("lazy", f"{lazy_module}:Backend")
    assert lazy_module not in sys.modules
    assert registrar.names("toolkit") == ["lazy"]
    assert lazy_module not in sys.modules
    assert registrar.get("toolkit", "lazy").__name__ == "Backend"
    assert lazy_module in sys.modules


def test_a_dotted_attribute_is_followed(lazy_module):
    registrar = Registrar()
    registrar.backend("inner", f"{lazy_module}:Outer.Inner")
    assert registrar.get("backend", "inner").__name__ == "Inner"


def test_a_text_that_does_not_import_raises_with_the_cause():
    registrar = Registrar()
    registrar.backend("broken", "no_such_module_for_plugins:Thing")
    with pytest.raises(ConfigurationError) as caught:
        registrar.get("backend", "broken")
    assert isinstance(caught.value.__cause__, ImportError)
    assert caught.value.details["target"] == "no_such_module_for_plugins:Thing"
    assert "no_such_module_for_plugins" in str(caught.value)


def test_a_text_with_a_missing_attribute_raises_with_the_cause(lazy_module):
    registrar = Registrar()
    registrar.backend("broken", f"{lazy_module}:Missing")
    with pytest.raises(ConfigurationError) as caught:
        registrar.get("backend", "broken")
    assert isinstance(caught.value.__cause__, AttributeError)


def test_a_failed_import_is_not_cached(lazy_module, tmp_path):
    registrar = Registrar()
    registrar.backend("late", "lazy_plugin_target_later:Thing")
    with pytest.raises(ConfigurationError):
        registrar.get("backend", "late")
    (tmp_path / "lazy_plugin_target_later.py").write_text("class Thing: ...\n", encoding="utf-8")
    import importlib

    importlib.invalidate_caches()
    try:
        assert registrar.get("backend", "late").__name__ == "Thing"
    finally:
        sys.modules.pop("lazy_plugin_target_later", None)


@pytest.mark.parametrize("text", ["nocolon", "a:b:c", ":x", "x:", "a b:c", "a:1b"])
def test_a_text_that_is_not_module_colon_attribute_is_refused_at_registration(text):
    with pytest.raises(ConfigurationError):
        Registrar().backend("x", text)


# -- the default registrar and a private one --


def test_the_default_registrar_is_one_per_process():
    assert get_registrar() is get_registrar()


def test_a_private_registrar_leaves_the_default_untouched():
    default_before = {kind: get_registrar().names(kind) for kind in KINDS}
    private = Registrar()
    for kind in KINDS:
        register(private, kind, "only-in-private", object())
    assert {kind: get_registrar().names(kind) for kind in KINDS} == default_before
    assert all("only-in-private" not in get_registrar().names(kind) for kind in KINDS)


# -- the built-in plugins of the owners, loaded at the first use (plugins:4.2)
# ------------------------------------


@pytest.fixture
def builtin_modules(tmp_path, monkeypatch):
    """Two fake owner modules that count how often their ``register`` runs, and a helper to add
    more."""
    (tmp_path / "fake_owner_a.py").write_text(
        textwrap.dedent(
            """
            CALLS = []

            def register(registrar):
                CALLS.append(1)
                registrar.backend("memory", "fake_owner_a:Backend")
                registrar.provider("fake", "fake_owner_a:Backend", profile=None, function="model")

            class Backend: ...
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / "fake_owner_b.py").write_text(
        "CALLS = []\n\ndef register(registrar):\n    CALLS.append(1)\n    "
        "registrar.tokenizer('tok', 'fake_owner_a:Backend')\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in ("fake_owner_a", "fake_owner_b"):
        sys.modules.pop(name, None)
    yield tmp_path
    for name in ("fake_owner_a", "fake_owner_b", "fake_owner_broken", "fake_owner_deep"):
        sys.modules.pop(name, None)


def test_the_builtin_plugins_are_the_owners_and_never_imported_by_base():
    owners = ("models", "store", "auth", "router", "tools", "prompts", "agents")
    expected = [f"skye.{owner}.plugins:register" for owner in owners]
    expected.insert(
        owners.index("tools"), "skye.tools.engines:register"
    )  # the MCP clients of tools (O80 option D)
    assert BUILTIN_PLUGINS == tuple(expected)
    assert all(_TEXT_RE.match(text) for text in BUILTIN_PLUGINS)


def test_a_private_registrar_loads_no_builtin_plugin():
    registrar = Registrar()
    assert all(registrar.names(kind) == [] for kind in KINDS)
    assert registrar._builtin_plugins == ()


def test_builtins_are_not_imported_when_the_registrar_is_built(builtin_modules):
    Registrar(builtin_plugins=("fake_owner_a:register",))
    assert "fake_owner_a" not in sys.modules


@pytest.mark.parametrize("first_call", ["get", "names", "has", "get_profile", "register"])
def test_the_first_use_loads_the_builtins_once(builtin_modules, first_call):
    registrar = Registrar(builtin_plugins=("fake_owner_a:register", "fake_owner_b:register"))
    calls = {
        "get": lambda: registrar.get("backend", "memory"),
        "names": lambda: registrar.names("backend"),
        "has": lambda: registrar.has("backend", "memory"),
        "get_profile": lambda: registrar.get_profile("fake"),
        "register": lambda: registrar.agent("mine", object()),
    }
    calls[first_call]()
    registrar.names("tokenizer")
    registrar.get("backend", "memory")
    assert sys.modules["fake_owner_a"].CALLS == [1] and sys.modules["fake_owner_b"].CALLS == [1]
    assert registrar.names("backend") == ["memory"] and registrar.names("tokenizer") == ["tok"]


def test_a_builtin_name_is_a_duplicate_for_a_registration_made_first(builtin_modules):
    """As today: ``register_backend("memory", ...)`` without ``replace`` fails because the built-in
    is known."""
    registrar = Registrar(builtin_plugins=("fake_owner_a:register",))
    with pytest.raises(ConfigurationError) as caught:
        registrar.backend("memory", dict)
    assert caught.value.details == {"kind": "backend", "name": "memory"}
    registrar.backend("memory", dict, replace=True)
    assert registrar.get("backend", "memory") is dict


def test_a_builtin_text_target_is_still_lazy(builtin_modules):
    registrar = Registrar(builtin_plugins=("fake_owner_a:register",))
    registrar.names("backend")
    assert "fake_owner_a" in sys.modules  # the plugin module ran, but it registered a text...
    assert registrar.get("backend", "memory").__name__ == "Backend"  # ...that resolves only now


def test_an_owner_without_a_plugin_module_is_skipped_silently(builtin_modules):
    registrar = Registrar(
        builtin_plugins=("no_such_owner._plugin:register", "fake_owner_a:register")
    )
    assert registrar.names("backend") == ["memory"]  # the next owner still registered


def test_a_plugin_module_that_fails_to_import_something_else_raises(builtin_modules):
    (builtin_modules / "fake_owner_broken.py").write_text(
        "import not_a_real_dependency_of_the_plugin\n", encoding="utf-8"
    )
    registrar = Registrar(builtin_plugins=("fake_owner_broken:register",))
    with pytest.raises(ModuleNotFoundError, match="not_a_real_dependency_of_the_plugin"):
        registrar.names("backend")


def test_a_plugin_module_inside_a_missing_package_is_skipped_only_when_the_module_itself_is_missing(
    builtin_modules,
):
    """``exc.name`` is the module asked for: a missing parent package of the owner is the same case,
    a missing dependency is not."""
    registrar = Registrar(builtin_plugins=("fake_owner_deep.sub._plugin:register",))
    assert (
        registrar.names("backend") == []
    )  # `fake_owner_deep` itself is missing: the owner is not there yet


def test_a_register_that_fails_raises_its_own_error(builtin_modules):
    (builtin_modules / "fake_owner_broken.py").write_text(
        "def register(registrar):\n    raise RuntimeError('bad plugin')\n", encoding="utf-8"
    )
    registrar = Registrar(builtin_plugins=("fake_owner_broken:register",))
    with pytest.raises(RuntimeError, match="bad plugin"):
        registrar.names("backend")


def test_a_builtin_that_registers_through_the_registrar_does_not_recurse(builtin_modules):
    """``register`` calls registration methods, which would ask for the built-ins again: the flag is
    set first."""
    registrar = Registrar(builtin_plugins=("fake_owner_a:register",))
    registrar.get_profile("anything")
    assert sys.modules["fake_owner_a"].CALLS == [1]


def test_the_default_registrar_is_built_with_the_scan_and_the_builtins(monkeypatch):
    import skye.base.plugins as module

    monkeypatch.setattr(module, "_default", None)
    registrar = module.get_registrar()
    assert registrar._scan is True and registrar._builtin_plugins == BUILTIN_PLUGINS
    assert registrar is module.get_registrar()


# -- unregister (not part of the Port)
# --------------------------------------------------------------------------


def test_unregister_removes_a_name_and_says_whether_it_was_there():
    registrar = Registrar()
    registrar.tokenizer("t", object())
    assert registrar.unregister("tokenizer", "t") is True
    assert registrar.names("tokenizer") == []
    assert registrar.unregister("tokenizer", "t") is False


def test_unregister_leaves_the_other_kinds_and_the_profile():
    registrar = Registrar()
    registrar.provider("acme", object, profile=FakeProfile("acme"), function="model")
    registrar.provider("acme", object, function="embedding")
    assert registrar.unregister("provider", "acme", "model") is True
    assert registrar.names("provider", "embedding") == ["acme"]
    assert registrar.get_profile("acme") == FakeProfile("acme")


def test_a_name_can_be_registered_again_after_unregister():
    registrar = Registrar()
    registrar.agent("a", object())
    registrar.unregister("agent", "a")
    registrar.agent("a", object())  # no duplicate error


def test_a_toolkit_can_be_unregistered():
    registrar = Registrar()
    registrar.toolkit("jira", object)
    assert registrar.unregister("toolkit", "jira") is True
    assert registrar.names("toolkit") == []
    assert registrar.unregister("toolkit", "jira") is False


def test_unregister_of_an_unknown_kind_raises():
    with pytest.raises(ConfigurationError):
        Registrar().unregister("flavour", "x")


def test_unregister_is_not_a_method_of_the_port():
    assert "unregister" not in KINDS and not hasattr(RegistrarInterface, "unregister")
