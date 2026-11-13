"""``provider()`` is typed so the quickstart needs no cast (Requirement 22.9 of steering, task 4.8).

The default call returns the model client, ``provider_type="embedding"`` the embedding client and ``provider_type="decision"`` the decision model. The overloads are checked at
runtime here; the type-checker lines are the ones of the quickstart, run by mypy when it is installed.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
import typing
from pathlib import Path

import pytest

import skye
from skye.models import registry

QUICKSTART = textwrap.dedent(
    """
    import skye
    from skye import UserMessage
    from skye.interfaces import ModelInterface, VectorEncoderInterface

    client = skye.provider("openai", api_key="sk-test")
    response = client.complete(messages=[UserMessage(content="Hello")], model="gpt-4o")
    print(response.content)
    embedder = skye.provider("openai", model="text-embedding-3-small", provider_type="embedding")
    vectors = embedder.encode_batch(["a", "b"])
    """
)


@pytest.mark.parametrize("fn", [skye.provider, registry.provider])
def test_provider_has_one_overload_per_kind(fn):
    overloads = typing.get_overloads(fn)
    assert len(overloads) == 3
    # An annotation is a class when the module has no `from __future__ import annotations`, and a string when it has.
    returns = {
        getattr(o.__annotations__["return"], "__name__", None) or str(o.__annotations__["return"]).strip("'\"").split(".")[-1]
        for o in overloads
    }
    assert returns == {"ModelInterface", "VectorEncoderInterface", "DecisionModel"}


@pytest.mark.skipif(shutil.which("mypy") is None and not Path(sys.prefix, "bin", "mypy").exists(), reason="mypy not installed")
def test_quickstart_type_checks_without_cast(tmp_path):
    source = tmp_path / "quickstart_check.py"
    source.write_text(QUICKSTART, encoding="utf-8")
    exe = shutil.which("mypy") or str(Path(sys.prefix, "bin", "mypy"))
    result = subprocess.run([exe, "--ignore-missing-imports", str(source)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout
