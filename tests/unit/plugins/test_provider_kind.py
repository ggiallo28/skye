"""The kind ``provider``: one table keyed by name and function, the function deduced from the class (task 15.1, Requirement 56.12)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from skye.base.exceptions import ConfigurationError
from skye.base.plugins import KINDS, PROVIDER_FUNCTIONS, Plugins, Registrar


@dataclass(frozen=True)
class FakeProfile:
    name: str
    key: str = ""


class Chat:
    async def acomplete(self, request):  # a model
        return request


class SyncChat:
    def complete(self, request):  # a model that writes the sync method only
        return request


class Embedder:
    async def aencode(self, text):  # an embedding
        return [0.0]


class SyncEmbedder:
    def encode_batch(self, texts):
        return [[0.0] for _ in texts]


class Decider:
    async def decide(self, prompt, options):  # a decision
        return options[0]


class Both(Chat, Embedder):
    """The methods of two functions."""


class Silent:
    """No method of any function."""


@pytest.fixture
def registrar() -> Registrar:
    return Registrar()


# -- the kind and the words


def test_provider_is_a_kind_and_the_functions_are_the_words_of_the_builder():
    assert "provider" in KINDS
    assert PROVIDER_FUNCTIONS == ("model", "embedding", "decision")


# -- the function is deduced from the class


@pytest.mark.parametrize(
    ("cls", "function"),
    [
        (Chat, "model"),
        (SyncChat, "model"),
        (Embedder, "embedding"),
        (SyncEmbedder, "embedding"),
        (Decider, "decision"),
    ],
)
def test_the_function_is_deduced_from_the_methods(registrar, cls, function):
    registrar.provider("acme", cls)
    assert registrar.get("provider", "acme") is cls
    assert registrar.get("provider", "acme", function) is cls
    assert registrar.names("provider", function) == ["acme"]
    assert registrar.names("provider", "model" if function != "model" else "embedding") == []


def test_the_built_in_classes_are_deduced():
    from skye.models import OpenAICompatibleProvider
    from skye.models.plugins.openai.embeddings import OpenAIEmbeddingProvider
    from skye.models.plugins.typesafe.decision import JevDecisionModel

    registrar = Registrar()
    registrar.provider("chat", OpenAICompatibleProvider)
    registrar.provider("vectors", OpenAIEmbeddingProvider)
    registrar.provider("jev", JevDecisionModel)
    assert registrar.names("provider", "model") == ["chat"]
    assert registrar.names("provider", "embedding") == ["vectors"]
    assert registrar.names("provider", "decision") == ["jev"]


def test_an_object_is_read_through_its_own_methods(registrar):
    chat = Chat()
    registrar.provider("acme", chat)
    assert registrar.get("provider", "acme", "model") is chat


def test_a_factory_is_read_through_the_class_it_says_it_returns(registrar):
    def make_chat() -> Chat:
        return Chat()

    registrar.provider("acme", make_chat)
    assert registrar.get("provider", "acme", "model") is make_chat


def test_a_factory_without_a_return_annotation_needs_the_function(registrar):
    def make():
        return Chat()

    with pytest.raises(ConfigurationError, match="function="):
        registrar.provider("acme", make)
    registrar.provider("acme", make, function="model")
    assert registrar.get("provider", "acme") is make


def test_a_builtin_return_type_says_nothing(registrar):
    def make() -> str:  # str has an `encode`, and it is not an embedding provider
        return ""

    with pytest.raises(ConfigurationError, match="function="):
        registrar.provider("acme", make)


# -- a class that says two functions or none


def test_a_class_with_the_methods_of_two_functions_is_an_error(registrar):
    with pytest.raises(ConfigurationError) as caught:
        registrar.provider("acme", Both)
    text = str(caught.value)
    assert "Both" in text and "model" in text and "embedding" in text
    assert caught.value.details["found"] == ["model", "embedding"]
    assert registrar.names("provider") == []


def test_a_class_with_the_methods_of_two_functions_is_accepted_when_it_says_which(registrar):
    registrar.provider("acme", Both, function="embedding")
    assert registrar.get("provider", "acme", "embedding") is Both
    assert registrar.has("provider", "acme", "model") is False


def test_a_class_with_no_method_of_any_function_is_an_error(registrar):
    with pytest.raises(ConfigurationError, match="function=") as caught:
        registrar.provider("acme", Silent)
    assert "Silent" in str(caught.value)
    registrar.provider(
        "acme", Silent, function="decision"
    )  # the author says it, and nothing contradicts it
    assert registrar.get("provider", "acme") is Silent


# -- function= for a text target, and a wrong one


def test_a_text_target_is_not_imported_so_it_needs_the_function(registrar):
    with pytest.raises(ConfigurationError, match="function="):
        registrar.provider("acme", "no_such_module_for_this_test:Chat")
    registrar.provider(
        "acme", "no_such_module_for_this_test:Chat", function="model"
    )  # nothing is imported now
    assert registrar.has("provider", "acme", "model")
    with pytest.raises(ConfigurationError, match="cannot be imported"):
        registrar.get("provider", "acme")  # the text is imported at the first get


def test_a_text_target_is_imported_at_the_first_get(registrar):
    registrar.provider("acme", "tests.unit.plugins.test_provider_kind:Chat", function="model")
    assert registrar.get("provider", "acme") is Chat


def test_a_wrong_function_for_a_class_that_says_another_raises(registrar):
    with pytest.raises(ConfigurationError, match="says function='embedding'"):
        registrar.provider("acme", Chat, function="embedding")
    assert registrar.names("provider") == []


def test_the_function_must_be_one_of_the_three_words(registrar):
    with pytest.raises(ConfigurationError, match="model, embedding, decision"):
        registrar.provider("acme", Chat, function="chat")  # type: ignore[arg-type]


def test_function_is_only_for_the_kind_provider(registrar):
    with pytest.raises(ConfigurationError, match="only"):
        registrar.get("backend", "memory", "model")  # type: ignore[arg-type]
    with pytest.raises(ConfigurationError, match="only"):
        registrar.names("agent", "model")  # type: ignore[arg-type]
    with pytest.raises(ConfigurationError, match="only"):
        registrar.has("agent", "x", "model")  # type: ignore[arg-type]
    with pytest.raises(ConfigurationError, match="only"):
        registrar.unregister("agent", "x", "model")  # type: ignore[arg-type]
    with pytest.raises(ConfigurationError, match="only"):
        registrar._register("agent", "x", object(), False, None, "model")


# -- one name, two functions


def test_one_name_can_be_a_chat_class_and_an_embedding_class(registrar):
    registrar.provider("acme", Chat)
    registrar.provider("acme", Embedder)
    assert registrar.names("provider") == ["acme"]
    assert registrar.get("provider", "acme", "model") is Chat
    assert registrar.get("provider", "acme", "embedding") is Embedder
    assert registrar.has("provider", "acme")
    assert registrar.has("provider", "acme", "embedding")
    assert registrar.has("provider", "acme", "decision") is False


def test_a_lookup_without_the_function_is_an_error_when_the_name_has_two(registrar):
    registrar.provider("acme", Chat)
    registrar.provider("acme", Embedder)
    with pytest.raises(ConfigurationError) as caught:
        registrar.get("provider", "acme")
    assert "embedding and model" in str(caught.value)
    assert caught.value.details["functions"] == ["embedding", "model"]


def test_a_lookup_without_the_function_finds_the_only_one(registrar):
    registrar.provider("acme", Embedder)
    assert registrar.get("provider", "acme") is Embedder


def test_an_unknown_function_for_a_name_lists_the_names_of_the_function_and_says_where_the_name_is(
    registrar,
):
    registrar.provider("acme", Chat)
    with pytest.raises(ConfigurationError) as caught:
        registrar.get("provider", "acme", "decision")
    assert "decision" in str(caught.value) and "acme is registered for model".replace(
        "acme", "'acme'"
    ) in str(caught.value)
    assert caught.value.details["function"] == "decision"
    assert caught.value.details["known"] == []  # no decision provider is registered
    assert caught.value.details["functions"] == ["model"]  # but acme is a model


def test_a_duplicate_in_one_function_is_an_error_and_replace_overrides(registrar):
    registrar.provider("acme", Chat)
    with pytest.raises(ConfigurationError, match="already registered") as caught:
        registrar.provider("acme", SyncChat)
    assert caught.value.details == {"kind": "provider", "name": "acme", "function": "model"}
    assert registrar.get("provider", "acme") is Chat
    registrar.provider("acme", SyncChat, replace=True)
    assert registrar.get("provider", "acme") is SyncChat


def test_the_same_name_in_two_functions_is_not_a_duplicate(registrar):
    registrar.provider("acme", Chat)
    registrar.provider("acme", Decider)  # no error
    assert registrar.names("provider") == ["acme"]
    assert registrar.names("provider", "decision") == ["acme"]


def test_unregister_removes_one_function_and_needs_it_when_the_name_has_two(registrar):
    registrar.provider("acme", Chat)
    registrar.provider("acme", Embedder)
    with pytest.raises(ConfigurationError, match="give function="):
        registrar.unregister("provider", "acme")
    assert registrar.unregister("provider", "acme", "model") is True
    assert registrar.has("provider", "acme", "model") is False
    assert registrar.get("provider", "acme") is Embedder
    assert registrar.unregister("provider", "acme") is True  # one function left: not ambiguous
    assert registrar.unregister("provider", "acme") is False
    assert registrar.names("provider") == []


def test_a_provider_has_no_default_set(registrar):
    with pytest.raises(ConfigurationError, match="no default set"):
        registrar.default_set("provider")


# -- one profile for a name, whatever the function


def test_one_profile_per_name_across_the_functions(registrar):
    profile = FakeProfile("acme")
    registrar.provider("acme", Chat, profile=profile)
    registrar.provider("acme", Embedder, profile=profile)  # the same profile is accepted
    assert registrar.get_profile("acme") is profile
    with pytest.raises(ConfigurationError, match="different profile"):
        registrar.provider("acme", Decider, profile=FakeProfile("acme", "other"))
    assert registrar.get_profile("acme") is profile
    assert (
        registrar.has("provider", "acme", "decision") is False
    )  # the failed registration changed nothing


def test_the_profile_is_shared_with_the_old_provider_kinds(registrar):
    profile = FakeProfile("acme")
    registrar.provider(
        "acme", Chat, profile=profile, function="model"
    )  # until task 15.2 removes the old kinds
    registrar.provider("acme", Embedder, profile=profile)
    with pytest.raises(ConfigurationError, match="different profile"):
        registrar.provider("acme", Decider, profile=FakeProfile("acme", "other"))


# -- the handle


@pytest.fixture
def plugins(registrar) -> Plugins:
    return Plugins(registrar=registrar)


def test_the_handle_registers_by_call_and_by_decorator(plugins, registrar):
    plugins.provider("direct", Chat)

    @plugins.provider("decorated")
    class Mine:
        async def aencode(self, text):
            return [0.0]

    @plugins.provider("text-like", function="decision")
    class Plain:
        pass

    assert Mine().aencode and Plain()  # the decorator returned the classes unchanged
    assert registrar.get("provider", "direct") is Chat
    assert registrar.get("provider", "decorated", "embedding") is Mine
    assert registrar.get("provider", "text-like", "decision") is Plain


def test_the_handle_reads_with_the_function(plugins):
    plugins.provider("acme", Chat)
    plugins.provider("acme", Embedder)
    assert plugins.get("provider", "acme", "model") is Chat
    assert plugins.names("provider", "embedding") == ["acme"]
    assert plugins.has("provider", "acme", "embedding")
    assert plugins.unregister("provider", "acme", "embedding") is True
    assert plugins.get("provider", "acme") is Chat


def test_the_handle_passes_the_profile_and_the_function_to_a_text_target(plugins):
    profile = FakeProfile("acme")
    plugins.provider(
        "acme", "tests.unit.plugins.test_provider_kind:Chat", profile=profile, function="model"
    )
    assert plugins.get_profile("acme") is profile
    assert plugins.get("provider", "acme") is Chat
