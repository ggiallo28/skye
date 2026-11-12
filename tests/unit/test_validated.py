"""Tests for the validated dataclasses of ``base`` (``skye.base.validated``): no pydantic needed."""

import dataclasses
import json
import sys
from datetime import datetime, timezone
from typing import Any, Literal

import pytest

from skye.base.exceptions import ValidationError
from skye.base.validated import Validated, dump, field, json_schema, validated


@validated
class Inner(Validated):
    count: int = 0


@validated
class Sample(Validated):
    name: str = field(min_length=1, description="The name")
    timeout: int = field(default=60, ge=1, le=600)
    ratio: float = 0.5
    enabled: bool = True
    mode: Literal["a", "b"] = "a"
    tags: list[str] = field(default_factory=list)
    limits: dict[str, int] = field(default_factory=dict)
    inner: Inner | None = None
    items: list[Inner] = field(default_factory=list)
    when: datetime | None = None
    anything: Any = None
    hidden: list[int] | None = field(default=None, init=False, repr=False, compare=False)


def test_valid_values_are_kept():
    sample = Sample(name="x", tags=["a"], limits={"k": 1})
    assert (sample.name, sample.timeout, sample.ratio, sample.enabled, sample.mode) == (
        "x",
        60,
        0.5,
        True,
        "a",
    )
    assert sample.tags == ["a"] and sample.hidden is None


def test_safe_conversions():
    sample = Sample(name="x", timeout="30", ratio=2, enabled="false", when="2026-01-01T00:00:00Z")
    assert sample.timeout == 30 and isinstance(sample.timeout, int)
    assert sample.ratio == 2.0 and isinstance(sample.ratio, float)
    assert sample.enabled is False
    assert sample.when == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_nested_dataclass_from_a_dict():
    sample = Sample(
        name="x", inner={"count": "3", "ignored": 1}, items=[{"count": 1}, Inner(count=2)]
    )
    assert sample.inner == Inner(count=3)
    assert [item.count for item in sample.items] == [1, 2]


@pytest.mark.parametrize(
    "kwargs, field_name",
    [
        ({"name": 5}, "name"),
        ({"name": ""}, "name"),
        ({"name": "x", "timeout": 0}, "timeout"),
        ({"name": "x", "timeout": 601}, "timeout"),
        ({"name": "x", "timeout": True}, "timeout"),
        ({"name": "x", "timeout": 1.5}, "timeout"),
        ({"name": "x", "timeout": "abc"}, "timeout"),
        ({"name": "x", "enabled": "maybe"}, "enabled"),
        ({"name": "x", "mode": "c"}, "mode"),
        ({"name": "x", "tags": "abc"}, "tags"),
        ({"name": "x", "tags": [1]}, "tags"),
        ({"name": "x", "limits": {"k": "v"}}, "limits"),
        ({"name": "x", "inner": 5}, "inner"),
        ({"name": "x", "when": "yesterday"}, "when"),
    ],
)
def test_invalid_values_name_the_field(kwargs, field_name):
    with pytest.raises(ValidationError) as caught:
        Sample(**kwargs)
    assert caught.value.details["field"] == field_name
    assert isinstance(caught.value, ValueError)


def test_missing_and_unknown_arguments_are_validation_errors():
    with pytest.raises(ValidationError) as missing:
        Sample()
    assert missing.value.details["field"] == "name"
    with pytest.raises(ValidationError) as unknown:
        Sample(name="x", nope=1)
    assert unknown.value.details["field"] == "nope"


def test_arguments_are_keywords_only():
    with pytest.raises(ValidationError):
        Sample("x")


def test_from_dict_ignores_unknown_keys_and_from_json_round_trips():
    sample = Sample.from_dict({"name": "x", "extra": 1, "timeout": 5})
    assert sample.timeout == 5
    again = Sample.from_json(sample.to_json())
    assert again == sample
    with pytest.raises(ValidationError):
        Sample.from_json("[1, 2]")


def test_to_dict_dumps_nested_models_and_skips_non_init_fields():
    sample = Sample(name="x", inner=Inner(count=2), items=[Inner(count=1)])
    data = sample.to_dict()
    assert data["inner"] == {"count": 2} and data["items"] == [{"count": 1}]
    assert "hidden" not in data
    assert json.loads(sample.to_json())["name"] == "x"


def test_dump_does_not_copy_arbitrary_objects():
    marker = object()
    assert dump({"a": [Inner(count=1)], "b": marker})["b"] is marker


def test_lists_and_dicts_given_by_the_caller_are_kept_by_reference():
    tags = ["a", "b"]
    assert Sample(name="x", tags=tags).tags is tags


def test_json_schema_describes_fields():
    schema = json_schema(Sample)
    assert schema["type"] == "object" and schema["required"] == ["name"]
    assert schema["properties"]["name"] == {
        "type": "string",
        "description": "The name",
        "minLength": 1,
    }
    assert (
        schema["properties"]["timeout"]["minimum"] == 1
        and schema["properties"]["timeout"]["maximum"] == 600
    )
    assert schema["properties"]["mode"] == {"enum": ["a", "b"]}
    assert schema["properties"]["inner"]["anyOf"][0]["title"] == "Inner"
    assert "hidden" not in schema["properties"]


def test_validated_models_are_plain_dataclasses():
    assert dataclasses.is_dataclass(Sample)
    assert Sample(name="x") == Sample(name="x")


def test_importing_the_models_does_not_import_pydantic():
    import subprocess

    code = (
        "import sys, skye.base.messages, skye.base.completion, skye.base.config, "
        "skye.base.interfaces.capability, skye.base.interfaces.safety, skye.base.log_event;"
        "sys.exit(1 if 'pydantic' in sys.modules else 0)"
    )
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


class _Color(str, __import__("enum").Enum):
    RED = "red"
    BLUE = "blue"


def test_an_enum_field_reads_its_value_and_names_the_field_when_wrong():
    @validated
    class Paint(Validated):
        color: _Color

    assert Paint(color="red").color is _Color.RED
    assert Paint(color=_Color.BLUE).color is _Color.BLUE
    with pytest.raises(ValidationError) as caught:
        Paint(color="green")
    assert caught.value.details["field"] == "color"


def test_an_enum_field_has_a_schema_and_serializes_to_its_value():
    @validated
    class Paint(Validated):
        color: _Color

    assert json_schema(Paint)["properties"]["color"] == {"enum": ["red", "blue"]}
    assert Paint(color="red").to_dict() == {"color": "red"}
    assert Paint(color="red").to_json() == '{"color": "red"}'


# -- trusted() (task 24.8) -------------------------------------------------------------------------------------------------


@validated
class _Timeout(Validated):
    seconds: int = field(default=60, ge=1)


def test_trusted_builds_without_checking_or_converting():
    from skye.base.validated import trusted

    with trusted():
        assert _Timeout(seconds="30").seconds == "30"  # not converted
        assert _Timeout(seconds=0).seconds == 0  # a constraint is not checked
    assert _Timeout(seconds="30").seconds == 30  # outside the block the object is validated again
    with pytest.raises(ValidationError):
        _Timeout(seconds=0)


def test_trusted_can_be_nested_and_leaves_the_state_as_it_was():
    from skye.base import validated as module
    from skye.base.validated import trusted

    with trusted():
        with trusted():
            assert module._TRUSTED.get() is True
        assert module._TRUSTED.get() is True
    assert module._TRUSTED.get() is False


def test_trusted_is_put_back_when_the_block_raises():
    from skye.base import validated as module
    from skye.base.validated import trusted

    with pytest.raises(RuntimeError):
        with trusted():
            raise RuntimeError("boom")
    assert module._TRUSTED.get() is False


def test_trusted_does_not_reach_another_thread():
    import threading

    from skye.base.validated import trusted

    seen: list[object] = []

    def build() -> None:
        try:
            _Timeout(seconds=0)
            seen.append("no error")
        except ValidationError:
            seen.append("validated")

    with trusted():
        thread = threading.Thread(target=build)
        thread.start()
        thread.join()
    assert seen == ["validated"]
