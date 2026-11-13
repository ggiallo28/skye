"""``register_backend`` and ``backend`` are a view of the ``backend`` table of the registrar
(plugins:7.1, Requirement 56.6, 56.7).

Every call to the registry of today works as before, on a private registrar so the default one is
not touched.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from skye.base.exceptions import ConfigurationError
from skye.base.plugins import Registrar, get_registrar
from skye.store import InMemoryBackend, available_backends, backend, factory, register_backend
from skye.store import plugins as store_plugin

BUILTIN = ["durable_function", "dynamodb", "file", "memory", "postgres", "redis", "valkey"]


@pytest.fixture
def private(monkeypatch: pytest.MonkeyPatch) -> Registrar:
    registrar = Registrar()
    store_plugin.register(registrar)
    monkeypatch.setattr(factory, "_registrar", lambda: registrar)
    return registrar


def test_the_plugin_registers_the_seven_built_in_names_by_text():
    registrar = Registrar()
    store_plugin.register(registrar)
    assert registrar.names("backend") == BUILTIN
    assert all(isinstance(t, str) and ":" in t for t in store_plugin.BACKENDS.values())


def test_registering_the_built_ins_imports_no_backend_module():
    code = (
        "import sys\n"
        "from skye.base.plugins import Registrar\n"
        "from skye.store import plugins as _plugin\n"
        "before = {m for m in sys.modules if m.startswith('skye.store.')}\n"
        "_plugin.register(Registrar())\n"
        "after = {m for m in sys.modules if m.startswith('skye.store.')}\n"
        "assert after == before, after - before\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_available_backends_lists_the_registered_names_sorted(private):
    assert available_backends() == BUILTIN
    register_backend("scratch", lambda **config: InMemoryBackend())
    assert available_backends() == sorted([*BUILTIN, "scratch"])


def test_a_built_in_name_builds_its_backend(private):
    assert isinstance(backend("memory"), InMemoryBackend)
    assert type(backend("valkey", redis_url="redis://h:6379/0")).__name__ == "RedisBackend"


def test_a_registered_factory_receives_the_config_as_keywords(private):
    seen: dict[str, object] = {}

    def make(**config: object) -> InMemoryBackend:
        seen.update(config)
        return InMemoryBackend()

    register_backend("mine", make)
    assert isinstance(backend("mine", size=3), InMemoryBackend)
    assert seen == {"size": 3}


def test_a_duplicate_name_is_refused_and_replace_overrides_it(private):
    register_backend("mine", InMemoryBackend)
    with pytest.raises(ConfigurationError, match="already registered"):
        register_backend("mine", InMemoryBackend)
    with pytest.raises(ConfigurationError, match="already registered"):
        register_backend("memory", InMemoryBackend)  # a built-in name too
    register_backend("memory", lambda **config: "replaced", replace=True)  # type: ignore[arg-type, return-value]
    assert backend("memory") == "replaced"


def test_an_unknown_name_lists_the_known_ones(private):
    with pytest.raises(
        ConfigurationError, match="unknown store backend 'nope'; known: durable_function, dynamodb"
    ):
        backend("nope")


@pytest.mark.parametrize("bad", ["", None, 3])
def test_a_name_must_be_a_non_empty_string(private, bad):
    with pytest.raises(ConfigurationError, match="non-empty string"):
        register_backend(bad, InMemoryBackend)


def test_a_factory_must_be_callable(private):
    with pytest.raises(ConfigurationError, match="not callable"):
        register_backend("mine", 42)  # type: ignore[arg-type]


def test_a_registration_through_the_view_is_visible_to_the_registrar(private):
    register_backend("mine", InMemoryBackend)
    assert private.get("backend", "mine") is InMemoryBackend


def test_a_text_that_does_not_import_keeps_its_cause(private):
    private.backend("broken", "no_such_store_module:Thing")
    with pytest.raises(ConfigurationError) as caught:
        backend("broken")
    assert isinstance(caught.value.__cause__, ImportError)


def test_the_view_uses_the_default_registrar_unless_replaced():
    assert factory._registrar() is get_registrar()
