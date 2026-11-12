"""``Plugins``: a handle on the registrar that registers by call or by decorator, at once, from any part of the program (task 14.1)."""

from __future__ import annotations

import sys
import textwrap
import threading
from dataclasses import dataclass

import pytest

import skye.base.plugins as plugins_module
from skye.base.exceptions import ConfigurationError
from skye.base.plugins import KINDS, Plugins, Registrar, get_registrar
from tests.unit.plugins.registrar_state import restored_default_registrar

PROVIDER_KINDS = ("provider",)


def options(kind: str) -> dict[str, str]:
    """``provider`` needs the function of an object whose methods do not say it; the other kinds need nothing."""
    return {"function": "model"} if kind == "provider" else {}


@dataclass(frozen=True)
class FakeProfile:
    """Stands in for ``ProviderProfile``: the registrar only compares profiles."""

    name: str


@pytest.fixture
def private() -> Registrar:
    return Registrar()


@pytest.fixture
def plugins(private: Registrar) -> Plugins:
    return Plugins(registrar=private)


def test_every_kind_of_the_registrar_has_a_method_of_the_handle():
    assert [kind for kind in KINDS if not callable(getattr(Plugins, kind, None))] == []


# -- a direct call and a decorator, for each kind --


@pytest.mark.parametrize("kind", KINDS)
def test_a_direct_call_registers(kind: str, plugins: Plugins, private: Registrar):
    target = object()
    assert getattr(plugins, kind)("acme", target, **options(kind)) is None
    assert private.has(kind, "acme")
    assert private.get(kind, "acme") is target


@pytest.mark.parametrize("kind", KINDS)
def test_a_decorator_registers_and_returns_the_object(
    kind: str, plugins: Plugins, private: Registrar
):
    @getattr(plugins, kind)("acme", **options(kind))
    class Thing:
        pass

    assert private.get(kind, "acme") is Thing
    assert Thing.__name__ == "Thing"
    assert isinstance(Thing(), Thing)


@pytest.mark.parametrize("kind", KINDS)
def test_a_decorator_works_on_a_function_and_leaves_it_callable(
    kind: str, plugins: Plugins, private: Registrar
):
    @getattr(plugins, kind)("acme", **options(kind))
    def shout(value: str) -> str:
        return value.upper()

    assert shout("a") == "A"
    assert private.get(kind, "acme") is shout


def test_the_decorator_registers_when_it_is_applied_and_not_before(
    plugins: Plugins, private: Registrar
):
    decorator = plugins.agent("late")
    assert not private.has("agent", "late")

    @decorator
    class Late:
        pass

    assert private.has("agent", "late")


def test_a_call_with_no_target_is_not_a_call_with_a_missing_target(plugins: Plugins):
    with pytest.raises(ConfigurationError, match="missing"):
        plugins.agent("nothing", None)


# -- one table --


def test_two_handles_on_one_registrar_see_one_table(private: Registrar):
    first, second = Plugins(registrar=private), Plugins(registrar=private)
    first.agent("reverse", object())
    assert second.has("agent", "reverse")
    assert second.names("agent") == ["reverse"]


def test_two_default_handles_see_the_default_registrar():
    with restored_default_registrar() as default:
        first, second = Plugins(), Plugins()
        first.agent("handle-test-reverse", "json:dumps")
        assert second.has("agent", "handle-test-reverse")
        assert default.has("agent", "handle-test-reverse")
        assert second.get("agent", "handle-test-reverse") is not None


def test_the_default_handle_reads_the_default_registrar_at_each_call(
    monkeypatch: pytest.MonkeyPatch,
):
    handle = Plugins()
    replacement = Registrar()
    monkeypatch.setattr(plugins_module, "_default", replacement)
    handle.agent("elsewhere", object())
    assert replacement.has("agent", "elsewhere")
    assert handle.registrar is replacement


def test_a_private_registrar_leaves_the_default_untouched(plugins: Plugins):
    before = get_registrar().names("agent")
    plugins.agent("private-only", object())
    assert get_registrar().names("agent") == before


# -- duplicates, replace, profile --


@pytest.mark.parametrize("kind", KINDS)
def test_a_duplicate_raises_unless_replace(kind: str, plugins: Plugins, private: Registrar):
    first, second = object(), object()
    getattr(plugins, kind)("acme", first, **options(kind))
    with pytest.raises(ConfigurationError, match="already registered"):
        getattr(plugins, kind)("acme", second, **options(kind))
    assert private.get(kind, "acme") is first
    getattr(plugins, kind)("acme", second, replace=True, **options(kind))
    assert private.get(kind, "acme") is second


def test_a_duplicate_by_decorator_raises_and_replace_overrides(
    plugins: Plugins, private: Registrar
):
    @plugins.agent("twice")
    class First:
        pass

    with pytest.raises(ConfigurationError, match="already registered"):

        @plugins.agent("twice")
        class Second:
            pass

    @plugins.agent("twice", replace=True)
    class Third:
        pass

    assert private.get("agent", "twice") is Third


@pytest.mark.parametrize("kind", PROVIDER_KINDS)
def test_a_provider_takes_a_profile_by_call_and_by_decorator(kind: str, plugins: Plugins):
    profile = FakeProfile("acme")
    getattr(plugins, kind)("acme", object(), profile=profile, **options(kind))
    assert plugins.get_profile("acme") is profile

    other = FakeProfile("beta")

    @getattr(plugins, kind)("beta", profile=other, **options(kind))
    class Beta:
        pass

    assert plugins.get_profile("beta") is other


def test_a_provider_profile_is_one_for_a_name_whatever_the_kind(plugins: Plugins):
    profile = FakeProfile("acme")
    plugins.provider("acme", object(), profile=profile, function="model")
    plugins.provider(
        "acme", object(), profile=profile, function="embedding"
    )  # the same profile is accepted
    assert plugins.get_profile("acme") is profile
    plugins.provider("beta", object(), profile=FakeProfile("beta"), function="model")
    with pytest.raises(ConfigurationError, match="different profile"):
        plugins.provider("beta", object(), profile=FakeProfile("other"), function="embedding")


def test_a_kind_that_takes_no_profile_refuses_one(plugins: Plugins):
    with pytest.raises(TypeError):
        plugins.agent("a", object(), profile=FakeProfile("a"))  # type: ignore[call-overload]


# -- the forwarded answers --


def test_names_has_get_and_unregister_forward_to_the_registrar(plugins: Plugins):
    one, two = object(), object()
    plugins.tokenizer("b", two)
    plugins.tokenizer("a", one)
    assert plugins.names("tokenizer") == ["a", "b"]
    assert plugins.has("tokenizer", "a") and not plugins.has("tokenizer", "c")
    assert plugins.get("tokenizer", "a") is one
    assert plugins.unregister("tokenizer", "a") is True
    assert plugins.unregister("tokenizer", "a") is False
    assert plugins.names("tokenizer") == ["b"]


def test_get_of_a_name_that_is_not_registered_lists_the_names(plugins: Plugins):
    plugins.agent("reverse", object())
    with pytest.raises(ConfigurationError, match="reverse"):
        plugins.get("agent", "nope")


def test_an_unknown_kind_raises(plugins: Plugins):
    with pytest.raises(ConfigurationError, match="unknown kind"):
        plugins.names("capability")


def test_default_set_forwards_to_the_registrar(plugins: Plugins):
    shout = object()
    plugins.template_filter("shout", shout)
    assert plugins.default_set("template_filter") == {"shout": shout}


def test_get_profile_of_a_provider_with_none_is_none(plugins: Plugins):
    plugins.provider("bare", object(), function="model")
    assert plugins.get_profile("bare") is None


# -- a text target, a function, a method, the toolkit --


def test_a_text_target_is_imported_at_the_first_get_and_not_at_registration(
    plugins: Plugins, tmp_path, monkeypatch: pytest.MonkeyPatch
):
    module = "handle_lazy_module"
    (tmp_path / f"{module}.py").write_text(textwrap.dedent("VALUE = 41\n"))
    monkeypatch.syspath_prepend(str(tmp_path))
    plugins.tokenizer("lazy", f"{module}:VALUE")
    assert module not in sys.modules
    assert plugins.get("tokenizer", "lazy") == 41
    assert module in sys.modules
    sys.modules.pop(module, None)


def test_a_text_target_that_does_not_import_raises_at_the_get(plugins: Plugins):
    plugins.tokenizer("broken", "no_such_module_for_handle:thing")
    with pytest.raises(ConfigurationError, match="cannot be imported"):
        plugins.get("tokenizer", "broken")


def test_the_decorator_works_inside_a_function(plugins: Plugins, private: Registrar):
    def enable() -> None:
        @plugins.agent("from-a-function")
        class FromFunction:
            pass

    assert not private.has("agent", "from-a-function")
    enable()
    assert private.has("agent", "from-a-function")


def test_the_decorator_works_inside_a_method(plugins: Plugins, private: Registrar):
    class App:
        def start(self) -> None:
            @plugins.agent("from-a-method")
            class FromMethod:
                pass

    App().start()
    assert private.has("agent", "from-a-method")


def test_the_name_is_found_at_once_by_the_owners_of_the_kind(plugins: Plugins, private: Registrar):
    @plugins.routing_strategy("shortest")
    def shortest(models: list[str]) -> str:
        return min(models, key=len)

    assert private.get("routing_strategy", "shortest")(["abc", "a"]) == "a"


class FakeCapability:
    """Stands in for a capability made by ``@capability``: the registrar only needs ``get_schema``."""

    def __init__(self, name: str) -> None:
        self.name = name

    def get_schema(self) -> object:
        return object()


def test_a_toolkit_keeps_its_tools_beside_the_target(plugins: Plugins, private: Registrar):
    tools = [FakeCapability("a"), FakeCapability("b")]
    plugins.toolkit("jira", object(), tools=tools)
    assert private.toolkit_tools("jira") == tuple(tools)
    assert private.toolkit_tools("nope") == ()


def test_a_toolkit_with_no_tools_has_none(plugins: Plugins, private: Registrar):
    plugins.toolkit("jira", object())
    assert private.toolkit_tools("jira") == ()


def test_tools_that_are_not_capabilities_are_refused_and_nothing_is_registered(
    plugins: Plugins, private: Registrar
):
    with pytest.raises(ConfigurationError, match="@capability"):
        plugins.toolkit("text", object(), tools=[len])
    with pytest.raises(ConfigurationError, match="list of capabilities"):
        plugins.toolkit("text", object(), tools="slugify")  # type: ignore[arg-type]
    with pytest.raises(ConfigurationError, match="@capability"):
        plugins.toolkit("text", tools=[len])
    assert private.names("toolkit") == []
    assert private.toolkit_tools("text") == ()


def test_the_call_with_tools_and_no_class_registers_a_toolkit_of_those_tools(
    plugins: Plugins, private: Registrar
):
    tools = [FakeCapability("a")]
    plugins.toolkit("text", tools=tools)  # no class: the toolkit is only the list
    assert private.names("toolkit") == ["text"]
    assert private.toolkit_tools("text") == tuple(tools)
    assert (
        private.get("toolkit", "text").__name__ == "ToolSet"
    )  # the text target is imported at the first get


def test_the_decorator_gives_its_class_to_the_registration_that_the_call_made(
    plugins: Plugins, private: Registrar
):
    tools = [FakeCapability("a")]

    @plugins.toolkit("jira", tools=tools)
    class JiraToolkit:
        pass

    assert JiraToolkit.__name__ == "JiraToolkit"  # the decorator returns the class unchanged
    assert private.get("toolkit", "jira") is JiraToolkit
    assert private.toolkit_tools("jira") == tuple(tools)
    assert private.names("toolkit") == ["jira"]


def test_the_decorator_form_with_tools_refuses_a_name_that_is_taken(
    plugins: Plugins, private: Registrar
):
    plugins.toolkit("jira", object())
    with pytest.raises(ConfigurationError, match="already registered"):
        plugins.toolkit("jira", tools=[FakeCapability("a")])


def test_the_decorator_says_when_the_registration_was_replaced_in_between(
    plugins: Plugins, private: Registrar
):
    decorator = plugins.toolkit("jira", tools=[FakeCapability("a")])
    plugins.toolkit("jira", object(), replace=True)  # another registration took the name

    class JiraToolkit:
        pass

    with pytest.raises(ConfigurationError, match="registered again"):
        decorator(JiraToolkit)


def test_replace_replaces_the_tools_too_and_unregister_removes_them(
    plugins: Plugins, private: Registrar
):
    plugins.toolkit("jira", object(), tools=[FakeCapability("a")])
    plugins.toolkit("jira", object(), replace=True)
    assert private.toolkit_tools("jira") == ()
    plugins.toolkit("jira", object(), tools=[FakeCapability("a")], replace=True)
    assert private.unregister("toolkit", "jira") is True
    assert private.toolkit_tools("jira") == ()


def test_a_toolkit_registers_by_call_and_by_decorator(plugins: Plugins, private: Registrar):
    @plugins.toolkit("jira")
    class Jira:
        pass

    plugins.toolkit("text", object())
    assert private.names("toolkit") == ["jira", "text"]


def test_an_empty_name_raises(plugins: Plugins):
    with pytest.raises(ConfigurationError, match="non-empty"):

        @plugins.agent("")
        class Nameless:
            pass


# -- task 14.4: what the clauses of Requirements 56.1 to 56.7 still need ---------------------------------------------


def test_unregister_removes_and_the_name_can_be_registered_again(plugins: Plugins):
    first, second = object(), object()
    plugins.agent("again", first)
    assert plugins.unregister("agent", "again") is True
    assert not plugins.has("agent", "again")
    with pytest.raises(ConfigurationError, match="no agent named 'again'"):
        plugins.get("agent", "again")
    plugins.agent("again", second)  # no duplicate error: the name is free again
    assert plugins.get("agent", "again") is second


def test_a_decorated_class_stays_usable(plugins: Plugins, private: Registrar):
    @plugins.agent("reverse")
    class Reverse:
        """Reverses a text."""

        def __init__(self, *, loud: bool = False) -> None:
            self.loud = loud

        def run(self, text: str) -> str:
            return text[::-1].upper() if self.loud else text[::-1]

    assert Reverse(loud=True).run("skye") == "EYKS"  # it is the class, not a wrapper
    assert private.get("agent", "reverse") is Reverse
    assert (Reverse.__doc__, Reverse.__qualname__.endswith("Reverse")) == ("Reverses a text.", True)

    class Loud(Reverse):  # and it can still be subclassed
        def run(self, text: str) -> str:
            return super().run(text) + "!"

    assert isinstance(Loud(), Reverse) and Loud().run("ab") == "ba!"


def test_a_duplicate_names_the_kind_and_the_name(plugins: Plugins):
    plugins.toolkit("jira", object())
    with pytest.raises(ConfigurationError) as caught:
        plugins.toolkit("jira", object())
    assert "toolkit" in str(caught.value) and "'jira'" in str(caught.value)


def test_a_registration_is_in_memory_only(plugins: Plugins, tmp_path, monkeypatch):
    """Requirement 56.3: no file, no thread, and nothing that survives the registrar."""
    monkeypatch.chdir(tmp_path)
    threads = set(threading.enumerate())
    plugins.agent("kept-in-memory", object())
    plugins.tokenizer("also-in-memory", len)
    assert set(threading.enumerate()) <= threads  # no thread was started (one that ended is fine)
    assert list(tmp_path.iterdir()) == []
    assert Registrar().names("agent") == []  # a new registrar starts empty: nothing was kept


def test_the_built_ins_register_with_the_calls_a_plugin_uses():
    """Requirement 56.7: a built-in door registers through the methods of the registrar, and the handle sees it."""
    registrar = Registrar(builtin_plugins=("skye.agents.plugins:register",))
    handle = Plugins(registrar=registrar)
    assert handle.names("agent") == ["react"]
    assert handle.get("agent", "react").__name__ == "ReActAgent"


def test_the_idioms_of_the_examples_work_on_the_default_handle():
    from skye.tools import SkyeMCPClient

    handle = Plugins()
    assert "react" in handle.names("agent")  # plugins.names("agent") in agent_type.py
    assert handle.get("mcp_client", "skyemcp") is SkyeMCPClient
    assert {"fastmcp", "skyemcp"} <= set(handle.names("mcp_client"))
    assert {"round_robin", "least_busy"} <= set(handle.names("routing_strategy"))
    assert "memory" in handle.names("backend")
