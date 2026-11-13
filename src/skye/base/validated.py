# decision D24
"""Validated dataclasses for the base contracts, in the standard library only.

The shared contracts (messages, completion request and response, configuration) are plain
``dataclasses``. This module gives them what pydantic gave them, without importing
it: every field is checked against its annotation when the object is built, a value that can be
read safely is converted (an ``int`` where a ``float`` is expected, a numeric string where an
``int`` is expected, a ``dict`` where a nested dataclass is expected), and a value that cannot be
read raises :class:`~skye.base.exceptions.ValidationError` naming the field and the value.

Example:
    >>> from skye.base.validated import Validated, field, validated
    >>>
    >>> @validated
    ... class Limits(Validated):
    ...     timeout: int = field(default=60, ge=1)
    >>> Limits(timeout="30").timeout
    30
"""

from __future__ import annotations

import contextlib
import contextvars
import dataclasses
import enum
import datetime as _dt
import functools
import json
import re
import types
import typing
from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING, Any, Literal, Union

from skye.base.exceptions import ValidationError

#: The constraint keywords ``field()`` accepts, checked after the value is converted.
_CONSTRAINTS = ("ge", "gt", "le", "lt", "min_length", "max_length")

_MISSING: Any = dataclasses.MISSING

if TYPE_CHECKING:
    from typing_extensions import dataclass_transform
else:  # no effect at run time: a type checker reads it, so ``@validated`` classes are dataclasses

    def dataclass_transform(**_: Any) -> Any:
        return lambda target: target


_TRUSTED: contextvars.ContextVar[bool] = contextvars.ContextVar("skye_validated_trusted", default=False)


@contextlib.contextmanager
def trusted() -> Iterator[None]:
    """Build objects inside the block without checking or converting their fields.

    Use it only for data that was checked in development, such as the templates that ship with Skye: a test
    must show that the objects built with and without the block are equal. Do not use it for what a user
    writes. The block works per thread and per task (it is a ``contextvars`` value), and blocks can be nested.

    Example:
        >>> from skye.base.validated import Validated, trusted, validated
        >>> @validated
        ... class Limits(Validated):
        ...     timeout: int = 60
        >>> with trusted():
        ...     Limits(timeout="30").timeout
        '30'
        >>> Limits(timeout="30").timeout
        30
    """
    token = _TRUSTED.set(True)
    try:
        yield
    finally:
        _TRUSTED.reset(token)


_BOOL_TRUE = frozenset({"true", "1", "yes", "on", "t", "y"})
_BOOL_FALSE = frozenset({"false", "0", "no", "off", "f", "n"})


class _RejectError(Exception):
    """A value cannot be read as the annotated type (turned into a ``ValidationError``)."""


def field(
    default: Any = _MISSING,
    *,
    default_factory: Any = _MISSING,
    description: str | None = None,
    ge: float | None = None,
    gt: float | None = None,
    le: float | None = None,
    lt: float | None = None,
    min_length: int | None = None,
    max_length: int | None = None,
    init: bool = True,
    repr: bool = True,
    compare: bool = True,
) -> Any:
    """Declare a dataclass field with an optional description and value constraints.

    Args:
        default: The default value (omit it for a required field).
        default_factory: A callable that builds the default (lists, dicts, nested models).
        description: What the field means (documentation only).
        ge: The value must be greater than or equal to this.
        gt: The value must be greater than this.
        le: The value must be less than or equal to this.
        lt: The value must be less than this.
        min_length: A string, list or dict must have at least this many items.
        max_length: A string, list or dict must have at most this many items.
        init: Whether the field is an argument of ``__init__`` (other fields are not validated).
        repr: Whether the field appears in ``repr``.
        compare: Whether the field takes part in ``==``.

    Returns:
        A ``dataclasses.Field`` carrying the constraints in its metadata.
    """
    metadata: dict[str, Any] = {}
    if description is not None:
        metadata["description"] = description
    constraints = {
        "ge": ge,
        "gt": gt,
        "le": le,
        "lt": lt,
        "min_length": min_length,
        "max_length": max_length,
    }
    metadata.update({key: value for key, value in constraints.items() if value is not None})
    kwargs: dict[str, Any] = {"init": init, "repr": repr, "compare": compare, "metadata": metadata}
    if default is not _MISSING:
        kwargs["default"] = default
    if default_factory is not _MISSING:
        kwargs["default_factory"] = default_factory
    return dataclasses.field(**kwargs)


#: What ``TypeError`` says when the arguments do not fit the generated ``__init__``.
_SIGNATURE_ERROR = re.compile(
    r"(missing \d+ required|unexpected keyword argument|positional argument)"
)


@dataclass_transform(kw_only_default=True, field_specifiers=(field,))
def validated(cls: Any = None, /, **options: Any) -> Any:
    """Make a class a keyword-only dataclass whose arguments and fields are validated.

    Use it on a class that inherits :class:`Validated`. The arguments are keywords only (so a
    required field may follow a field with a default), and an argument that is missing or that the
    class does not have raises :class:`~skye.base.exceptions.ValidationError`, as does a field value
    that cannot be read as its type.

    Args:
        cls: The class (when used as ``@validated``).
        **options: Other options of ``dataclasses.dataclass`` (for example ``frozen=True``).

    Returns:
        The dataclass.
    """

    def wrap(klass: Any) -> Any:
        klass = dataclasses.dataclass(kw_only=True, **options)(klass)
        original = klass.__init__

        @functools.wraps(original)
        def init(self: Any, *args: Any, **kwargs: Any) -> None:
            try:
                original(self, *args, **kwargs)
            except TypeError as error:
                if not _SIGNATURE_ERROR.search(str(error)):
                    raise
                named = re.findall(r"'([^']+)'", str(error))
                raise ValidationError(
                    f"Invalid arguments for {klass.__name__}: {error}",
                    field=named[0] if named else "<arguments>",
                    value=None,
                ) from error

        klass.__init__ = init
        return klass

    return wrap(cls) if cls is not None else wrap


class Validated:
    """Mixin for dataclasses whose fields are validated and converted when the object is built.

    Use it with ``@validated``. A subclass that needs its own check overrides ``__post_init__``
    and calls ``super().__post_init__()`` first.
    """

    def __post_init__(self) -> None:
        """Check and convert every field against its annotation and constraints."""
        validate_instance(self)

    def to_dict(self) -> dict[str, Any]:
        """The fields as plain dicts and lists (nested models are converted too)."""
        dumped: dict[str, Any] = dump(self)
        return dumped

    def to_json(self, **options: Any) -> str:
        """The fields as a JSON string (a datetime or other non-JSON value becomes its text).

        Args:
            **options: Options of ``json.dumps`` (for example ``indent=2``).
        """
        return json.dumps(self.to_dict(), default=str, **options)

    @classmethod
    def from_json(cls, text: str) -> Any:
        """Build an instance from a JSON object, ignoring keys that are not fields.

        Args:
            text: A JSON object.

        Raises:
            ValidationError: If a value cannot be read as the type of its field.
        """
        data = json.loads(text)
        if not isinstance(data, Mapping):
            raise ValidationError(
                f"Expected a JSON object for {cls.__name__}", field="<root>", value=text
            )
        return from_mapping(cls, data)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Any:
        """Build an instance from a mapping, ignoring keys that are not fields.

        Args:
            data: The values, for example parsed from a JSON file.

        Returns:
            The validated instance.

        Raises:
            ValidationError: If a value cannot be read as the type of its field.
        """
        return from_mapping(cls, data)


def dump(value: Any) -> Any:
    """Convert a model (and any model nested in lists and dicts) to plain dicts and lists.

    Unlike ``dataclasses.asdict`` it does not deep-copy the values, so a field that holds an
    arbitrary object (a capability, a client) is returned as it is.

    Args:
        value: A dataclass instance, or a list, tuple or dict that may contain some.

    Returns:
        The same structure with every dataclass turned into a ``dict``.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: dump(getattr(value, f.name)) for f in dataclasses.fields(value) if f.init}
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, Mapping):
        return {key: dump(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [dump(item) for item in value]
    return value


def validate_instance(obj: Any) -> None:
    """Validate and convert the fields of a dataclass instance in place.

    Args:
        obj: A dataclass instance.

    Raises:
        ValidationError: If a field cannot be read as its annotated type or breaks a constraint.
    """
    if _TRUSTED.get():
        return
    cls = type(obj)
    hints = _hints(cls)
    for f in dataclasses.fields(obj):
        if not f.init:
            continue
        value = getattr(obj, f.name)
        converted = _check(value, hints.get(f.name, Any), f"{cls.__name__}.{f.name}", f.name)
        _constrain(converted, f.metadata, f"{cls.__name__}.{f.name}", f.name)
        if converted is not value:
            setattr(obj, f.name, converted)


_HINTS: dict[type, dict[str, Any]] = {}


def _hints(cls: type) -> dict[str, Any]:
    """The resolved annotations of a dataclass, cached (unresolved names: no field is checked)."""
    cached = _HINTS.get(cls)
    if cached is None:
        try:
            cached = typing.get_type_hints(cls)
        except Exception:
            cached = {}
        _HINTS[cls] = cached
    return cached


def _fail(path: str, field_name: str, value: Any, reason: str) -> ValidationError:
    """The error for a field, naming the field and the value."""
    return ValidationError(
        f"Invalid value for {path}: {reason}", field=field_name, value=value, path=path
    )


def _check(value: Any, tp: Any, path: str, field_name: str) -> Any:
    """Convert ``value`` to ``tp`` or raise a ``ValidationError`` for ``field_name``."""
    try:
        return _convert(value, tp, path)
    except _RejectError as rejection:
        raise _fail(path, field_name, value, str(rejection)) from None


def _constrain(value: Any, metadata: Mapping[str, Any], path: str, field_name: str) -> None:
    """Apply the numeric and length constraints of a field."""
    if value is None:
        return
    for key in _CONSTRAINTS:
        if key not in metadata:
            continue
        limit = metadata[key]
        if key in ("min_length", "max_length"):
            try:
                size = len(value)
            except TypeError:
                continue
            bad = size < limit if key == "min_length" else size > limit
            reason = (
                f"length {size} must be {'at least' if key == 'min_length' else 'at most'} {limit}"
            )
        else:
            try:
                bad = {
                    "ge": value < limit,
                    "gt": value <= limit,
                    "le": value > limit,
                    "lt": value >= limit,
                }[key]
            except TypeError:
                continue
            words = {"ge": ">=", "gt": ">", "le": "<=", "lt": "<"}[key]
            reason = f"{value!r} must be {words} {limit}"
        if bad:
            raise _fail(path, field_name, value, reason)


def _convert(value: Any, tp: Any, path: str) -> Any:
    """Read ``value`` as ``tp`` (an exact match first, then the safe conversions) or reject it."""
    if tp is Any or tp is object or tp is None and value is None:
        return value
    if tp is None or tp is type(None):
        if value is None:
            return None
        raise _RejectError("expected None")
    origin = typing.get_origin(tp)
    if origin is Union or origin is types.UnionType:
        arms = typing.get_args(tp)
        if value is None and type(None) in arms:
            return None
        for lax in (False, True):
            for arm in arms:
                if arm is type(None):
                    continue
                try:
                    return _convert_arm(value, arm, path, lax)
                except _RejectError:
                    continue
        raise _RejectError(f"expected {_name(tp)}, got {type(value).__name__}")
    return _convert_arm(value, tp, path, True)


def _convert_arm(value: Any, tp: Any, path: str, lax: bool) -> Any:
    """Convert to one non-union type; ``lax`` allows the safe conversions."""
    if tp is Any or tp is object:
        return value
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin is Literal:
        if value in args:
            return value
        raise _RejectError(f"expected one of {list(args)}")
    if origin is Union or origin is types.UnionType:
        return _convert(value, tp, path)
    if origin in (list, set, frozenset, tuple) or tp in (list, set, frozenset, tuple):
        return _sequence(value, origin or tp, args, path, lax)
    if origin is dict or tp is dict or origin is Mapping:
        return _mapping(value, args, path)
    if origin is type or tp is type:
        if isinstance(value, type):
            return value
        raise _RejectError("expected a class")
    if isinstance(tp, type) and issubclass(tp, enum.Enum):
        if isinstance(value, tp):
            return value
        try:
            return tp(value)
        except ValueError:
            raise _RejectError(f"expected one of {[member.value for member in tp]}") from None
    if tp is str:
        if isinstance(value, str):
            return value
        raise _RejectError(f"expected a string, got {type(value).__name__}")
    if tp is bool:
        return _boolean(value, lax)
    if tp is int:
        return _integer(value, lax)
    if tp is float:
        return _number(value, lax)
    if tp is _dt.datetime:
        return _datetime(value, lax)
    if isinstance(tp, type):
        if isinstance(value, tp):
            return value
        if dataclasses.is_dataclass(tp) and isinstance(value, Mapping) and lax:
            return _from_mapping(tp, value, path)
        raise _RejectError(f"expected {tp.__name__}, got {type(value).__name__}")
    return value  # TypeVar, Callable, Protocol, unresolved name: no check


def _name(tp: Any) -> str:
    """A readable name of a type for an error message."""
    return getattr(tp, "__name__", None) or str(tp).replace("typing.", "")


def _boolean(value: Any, lax: bool) -> bool:
    if isinstance(value, bool):
        return value
    if lax:
        if isinstance(value, str) and value.strip().lower() in _BOOL_TRUE | _BOOL_FALSE:
            return value.strip().lower() in _BOOL_TRUE
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
    raise _RejectError(f"expected a boolean, got {type(value).__name__}")


def _integer(value: Any, lax: bool) -> int:
    if isinstance(value, bool):
        raise _RejectError("expected an integer, got a boolean")
    if isinstance(value, int):
        return value
    if lax:
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                pass
    raise _RejectError(f"expected an integer, got {type(value).__name__}")


def _number(value: Any, lax: bool) -> float:
    if isinstance(value, bool):
        raise _RejectError("expected a number, got a boolean")
    if isinstance(value, float):
        return value
    if isinstance(value, int):
        return float(value)
    if lax and isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            pass
    raise _RejectError(f"expected a number, got {type(value).__name__}")


def _datetime(value: Any, lax: bool) -> _dt.datetime:
    if isinstance(value, _dt.datetime):
        return value
    if lax and isinstance(value, str):
        try:
            return _dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            pass
    raise _RejectError(f"expected a datetime, got {type(value).__name__}")


def _sequence(value: Any, kind: Any, args: tuple[Any, ...], path: str, lax: bool) -> Any:
    """A list (or set, tuple) whose items are read as the item type."""
    if isinstance(value, kind):
        items = list(value)
    elif lax and isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
    else:
        raise _RejectError(f"expected a {kind.__name__}, got {type(value).__name__}")
    if kind is tuple and args and not (len(args) == 2 and args[1] is Ellipsis):
        if len(args) != len(items):
            raise _RejectError(f"expected {len(args)} items, got {len(items)}")
        return tuple(
            _convert(item, arg, f"{path}[{i}]") for i, (item, arg) in enumerate(zip(items, args))
        )
    item_type = args[0] if args else Any
    converted = [_convert(item, item_type, f"{path}[{i}]") for i, item in enumerate(items)]
    if kind is list:
        # Keep the caller's list when no item changed, as a list is shared by reference.
        if isinstance(value, list) and all(a is b for a, b in zip(converted, value)):
            return value
        return converted
    return kind(converted)


def _mapping(value: Any, args: tuple[Any, ...], path: str) -> dict[Any, Any]:
    """A dict whose keys and values are read as the key and value types."""
    if not isinstance(value, Mapping):
        raise _RejectError(f"expected a dict, got {type(value).__name__}")
    key_type, value_type = (args + (Any, Any))[:2] if args else (Any, Any)
    result = {
        _convert(key, key_type, f"{path}.<key>"): _convert(item, value_type, f"{path}[{key!r}]")
        for key, item in value.items()
    }
    if isinstance(value, dict) and all(
        k1 is k2 and result[k1] is value[k1] for k1, k2 in zip(result, value)
    ):
        return value
    return result


def from_mapping(cls: type, data: Mapping[str, Any]) -> Any:
    """Build a dataclass from a mapping, ignoring keys that are not init fields.

    Args:
        cls: A dataclass.
        data: The values.

    Returns:
        The validated instance.
    """
    names = {f.name for f in dataclasses.fields(cls) if f.init}
    return cls(**{key: value for key, value in data.items() if key in names})


def _from_mapping(cls: type, data: Mapping[str, Any], path: str) -> Any:
    """Build a nested dataclass: through its own ``from_dict`` when it defines one."""
    builder = getattr(cls, "from_dict", None)
    if builder is not None and getattr(builder, "__func__", None) is not getattr(
        Validated.from_dict, "__func__", None
    ):
        return builder(data)
    return from_mapping(cls, data)


def json_schema(cls: type) -> dict[str, Any]:
    """The JSON Schema of a dataclass: its fields, their types, descriptions and constraints.

    Args:
        cls: A dataclass (typically a model that uses :class:`Validated`).

    Returns:
        A JSON Schema ``object`` with ``properties`` and, if fields are required, ``required``.
    """
    hints = _hints(cls)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for f in dataclasses.fields(cls):
        if not f.init:
            continue
        schema = _schema(hints.get(f.name, Any))
        if "description" in f.metadata:
            schema["description"] = f.metadata["description"]
        _schema_limits(schema, f.metadata)
        properties[f.name] = schema
        if f.default is _MISSING and f.default_factory is _MISSING:
            required.append(f.name)
    result: dict[str, Any] = {"type": "object", "title": cls.__name__, "properties": properties}
    if required:
        result["required"] = required
    return result


def _schema_limits(schema: dict[str, Any], metadata: Mapping[str, Any]) -> None:
    """Add the numeric and length constraints of a field to its schema."""
    numeric = {"ge": "minimum", "gt": "exclusiveMinimum", "le": "maximum", "lt": "exclusiveMaximum"}
    for key, word in numeric.items():
        if key in metadata:
            schema[word] = metadata[key]
    for key, strings, arrays in (
        ("min_length", "minLength", "minItems"),
        ("max_length", "maxLength", "maxItems"),
    ):
        if key in metadata:
            schema[strings if schema.get("type") == "string" else arrays] = metadata[key]


def _schema(tp: Any) -> dict[str, Any]:
    """The JSON Schema of one annotation."""
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if tp is Any or tp is object or tp is type or origin is type:
        return {}
    if tp is None or tp is type(None):
        return {"type": "null"}
    if origin is Union or origin is types.UnionType:
        return {"anyOf": [_schema(arm) for arm in args]}
    if origin is Literal:
        return {"enum": list(args)}
    if origin in (list, set, frozenset, tuple) or tp in (list, set, frozenset, tuple):
        schema: dict[str, Any] = {"type": "array"}
        if args and args[0] is not Ellipsis:
            schema["items"] = _schema(args[0])
        return schema
    if origin is dict or tp is dict:
        schema = {"type": "object"}
        if len(args) == 2:
            schema["additionalProperties"] = _schema(args[1])
        return schema
    if isinstance(tp, type) and issubclass(tp, enum.Enum):
        return {"enum": [member.value for member in tp]}
    simple = {
        str: {"type": "string"},
        bool: {"type": "boolean"},
        int: {"type": "integer"},
        float: {"type": "number"},
    }
    if tp in simple:
        return dict(simple[tp])
    if tp is _dt.datetime:
        return {"type": "string", "format": "date-time"}
    if isinstance(tp, type) and dataclasses.is_dataclass(tp):
        return json_schema(tp)
    return {}
