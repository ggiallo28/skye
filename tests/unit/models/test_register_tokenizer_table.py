"""``TokenCounter.register_tokenizer`` keeps its own table and is outside the plugin interface (task 17.2, Requirement 59.11)."""

import threading

import pytest

from skye import Plugins
from skye.base.plugins import get_registrar
from skye.base.profile import ModelProfile, ProviderProfile
from skye.models.token_counter import TokenCounter


class Words:
    def encode(self, text: str) -> list[str]:
        return text.split()


class Chars:
    def encode(self, text: str) -> list[str]:
        return list(text)


@pytest.fixture(autouse=True)
def clean():
    before = dict(TokenCounter._registered)
    yield
    for name in set(TokenCounter._registered) - set(before):
        TokenCounter.unregister_tokenizer(name)


def test_the_call_does_not_write_to_the_registrar() -> None:
    names = get_registrar().names("tokenizer")
    TokenCounter.register_tokenizer("zz-own-", Words())
    assert get_registrar().names("tokenizer") == names
    assert "zz-own-" not in names


def test_the_registrar_table_holds_only_the_factories_that_profiles_name() -> None:
    names = get_registrar().names("tokenizer")
    assert "tiktoken" in names
    TokenCounter.register_tokenizer("zz-other-", Words())
    assert get_registrar().names("tokenizer") == names


def test_a_prefix_registration_wins_and_the_longest_prefix_wins() -> None:
    TokenCounter.register_tokenizer("zz-fam-", Words())
    assert TokenCounter.count_tokens("one two three", "zz-fam-1") == 3
    TokenCounter.register_tokenizer("zz-fam-big", Chars())
    assert TokenCounter.count_tokens("abc", "zz-fam-big-2") == 3
    assert TokenCounter.count_tokens("one two three", "zz-fam-small") == 3


def test_a_registered_tokenizer_wins_over_the_one_a_profile_names() -> None:
    plugins = Plugins()
    plugins.tokenizer("zz-chars-name", lambda model: Chars())
    plugins.provider(
        "zz-prov",
        object,
        function="model",
        profile=ProviderProfile(
            "zz-prov", models={"zz-m": ModelProfile(tokenizer="zz-chars-name")}
        ),
    )
    try:
        assert TokenCounter.count_tokens("abc", "zz-m") == 3  # by the profile
        TokenCounter.register_tokenizer("zz-m", Words())
        assert TokenCounter.count_tokens("abc def", "zz-m") == 2  # the registered one wins
    finally:
        plugins.unregister("provider", "zz-prov", "model")
        plugins.unregister("tokenizer", "zz-chars-name")


def test_unregister_removes_only_its_own_entries() -> None:
    plugins = Plugins()
    plugins.tokenizer("zz-factory", lambda model: Words())
    TokenCounter.register_tokenizer("zz-mine", Words())
    try:
        assert (
            TokenCounter.unregister_tokenizer("zz-factory") is False
        )  # a factory of the registrar
        assert plugins.has("tokenizer", "zz-factory")
        assert TokenCounter.unregister_tokenizer("zz-mine") is True
        assert TokenCounter.unregister_tokenizer("zz-mine") is False
    finally:
        plugins.unregister("tokenizer", "zz-factory")


def test_a_tokenizer_registered_by_name_is_counted_through_a_profile() -> None:
    """The idiom of ``examples/plugins/tokenizer.py``."""
    plugins = Plugins()

    @plugins.tokenizer("zz-words")
    def words(model: str) -> Words:
        return Words()

    plugins.provider(
        "zz-wordy",
        object,
        function="model",
        profile=ProviderProfile(
            "zz-wordy", models={"zz-wordy-1": ModelProfile(tokenizer="zz-words")}
        ),
    )
    try:
        assert TokenCounter.count_tokens("one two three four", "zz-wordy-1") == 4
    finally:
        plugins.unregister("provider", "zz-wordy", "model")
        plugins.unregister("tokenizer", "zz-words")


def test_two_threads_registering_do_not_lose_an_entry() -> None:
    barrier = threading.Barrier(8)

    def register(index: int) -> None:
        barrier.wait()
        for step in range(25):
            TokenCounter.register_tokenizer(f"zz-thread-{index}-{step}", Words())

    threads = [threading.Thread(target=register, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    registered = [name for name in TokenCounter._registered if name.startswith("zz-thread-")]
    assert len(registered) == 8 * 25
