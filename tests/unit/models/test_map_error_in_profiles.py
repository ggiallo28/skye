"""The handler of a provider is its ``map_error`` (Requirement 60.5, D104, D110): in the folder of the provider, named by the profile, imported late.

``error_mapping`` keeps the mapping every provider shares and names no provider; a plugin gives ``map_error=`` in its ``ProviderProfile``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import skye
from skye.base.exceptions import ProviderError, ProviderTimeoutError, RateLimitError
from skye.base.profile import ProviderProfile
from skye.models import OpenAICompatibleProvider
from skye.models.utilities import error_mapping
from skye.models.utilities.error_mapping import ErrorHandler
from tests.unit.plugins.registrar_state import restored_default_registrar

BUILT_IN = ("openai", "anthropic", "bedrock", "azure", "google")


class Slow(Exception):
    status_code = 429


@pytest.mark.parametrize("provider", BUILT_IN)
def test_a_built_in_profile_names_the_errors_file_of_its_folder(provider):
    with restored_default_registrar() as registrar:
        text = registrar.get_profile(provider).map_error
    assert text == f"skye.models.plugins.{provider}.errors:map_error"


@pytest.mark.parametrize("provider", BUILT_IN)
def test_the_old_handler_names_are_the_map_error_of_the_provider(provider):
    old = getattr(ErrorHandler, f"handle_{provider}_error")
    assert old is error_mapping.profile_handler(provider)
    assert old.__module__ == f"skye.models.plugins.{provider}.errors"


def test_a_provider_with_no_handler_has_no_old_handler_name():
    for provider in ("cohere", "no-such-provider"):
        with pytest.raises(AttributeError):
            getattr(ErrorHandler, f"handle_{provider}_error")


def test_wrap_provider_error_calls_the_map_error_of_the_profile():
    wrapped = ErrorHandler.wrap_provider_error(Slow("slow down"), "openai")
    assert isinstance(wrapped, RateLimitError)
    assert str(wrapped).startswith("OpenAI API error")
    wrapped = ErrorHandler.wrap_provider_error(Slow("slow down"), "azure")
    assert str(wrapped).startswith("Azure OpenAI API error")


def test_a_provider_error_is_returned_as_it_is():
    error = ProviderError("kept", provider="openai")
    assert ErrorHandler.wrap_provider_error(error, "openai") is error


def test_a_provider_with_no_handler_gets_the_common_mapping():
    wrapped = ErrorHandler.wrap_provider_error(TimeoutError("timeout"), "cohere")
    assert isinstance(wrapped, ProviderTimeoutError)
    assert str(wrapped).startswith("Provider error")


def test_a_plugin_gives_its_own_map_error_in_its_profile():
    calls = []

    def my_map_error(error, provider="acme"):
        calls.append((type(error).__name__, provider))
        return RateLimitError("mapped by acme", provider=provider)

    with restored_default_registrar():
        plugins = skye.Plugins()
        plugins.provider(
            "acme",
            OpenAICompatibleProvider,
            profile=ProviderProfile("acme", map_error=my_map_error),
        )
        wrapped = ErrorHandler.wrap_provider_error(ValueError("boom"), "acme")
        plugins.provider(
            "plain",
            OpenAICompatibleProvider,
            profile=ProviderProfile("plain"),
        )
        common = ErrorHandler.wrap_provider_error(ValueError("boom"), "plain")
    assert isinstance(wrapped, RateLimitError) and str(wrapped).startswith("mapped by acme")
    assert calls == [("ValueError", "acme")]
    assert type(common) is ProviderError and str(common).startswith("Provider error")


def test_a_plugin_gives_its_map_error_as_a_text():
    with restored_default_registrar():
        skye.Plugins().provider(
            "acme-text",
            OpenAICompatibleProvider,
            profile=ProviderProfile(
                "acme-text", map_error="skye.models.plugins.openai.errors:map_error"
            ),
        )
        wrapped = ErrorHandler.wrap_provider_error(Slow("x"), "acme-text")
    assert isinstance(wrapped, RateLimitError) and str(wrapped).startswith("OpenAI API error")


def test_error_mapping_names_no_provider():
    source = Path(error_mapping.__file__).read_text(encoding="utf-8").lower()
    for word in ("openai", "anthropic", "bedrock", "azure", "google", "cohere"):
        assert word not in source, word


def test_the_errors_files_are_imported_at_the_first_error_and_not_before():
    code = (
        "import sys\n"
        "import skye\n"
        "from skye.base.plugins import get_registrar\n"
        "from skye.models import OpenAICompatibleProvider\n"
        "registrar = get_registrar()\n"
        "assert registrar.get_profile('openai').map_error\n"
        "OpenAICompatibleProvider(model='gpt-4o-mini', api_key='k', provider_name='openai')\n"
        "late = [m for m in sys.modules if m.endswith('.errors') and m.startswith('skye.models.plugins')]\n"
        "assert not late, late\n"
        "from skye.models.utilities.error_mapping import ErrorHandler\n"
        "ErrorHandler.wrap_provider_error(ValueError('x'), 'openai')\n"
        "assert 'skye.models.plugins.openai.errors' in sys.modules\n"
        "assert 'skye.models.plugins.google.errors' not in sys.modules\n"
    )
    done = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(Path(skye.__file__).parents[1])},
    )
    assert done.returncode == 0, done.stderr[-800:]


def test_gemini_schema_lives_in_the_google_folder():
    from skye.models.plugins.google import schema
    from skye.models.utilities import structured

    assert hasattr(schema, "gemini_schema")
    assert not hasattr(structured, "gemini_schema")
