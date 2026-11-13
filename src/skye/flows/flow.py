# decisions D52, D61
"""A flow loaded from a ``.skye`` file: checked and ready to be read, not to be run yet.

``flows`` imports only ``base`` (and ``utils``, the file reader); a step is a ``Runnable`` found by
name in the registry the
caller passes, never by import. The flow runtime is not built yet: :meth:`Flow.run` says so (spec
``3-runtime-flows``).

Codename: stream.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Any

from skye.base.dsl import Diagnostic, Document, FlowSpec, build_cached, check_text, to_text
from skye.base.exceptions import ConfigurationError
from skye.utils.skye_files import diagnostics_error, load_document

_NOT_BUILT = (
    "The flow runtime is not built yet: a Flow can be loaded, checked and written back, but not "
    "run. "
    "The runtime belongs to the spec .kiro/specs/3-runtime-flows."
)


class Flow:
    """A validated ``flow`` block and the registry its steps are resolved from.

    Build it with :meth:`from_file` or :meth:`from_text`; both raise a ``ConfigurationError``
    listing every mistake
    (file, line, column, reason, fix) when the block is not valid.

    Args:
        spec: A validated flow (from ``skye.base.dsl``).
        registry: The steps, by name: ``registry.NAME`` in the flow means ``registry["NAME"]``.

    Attributes:
        spec: The validated :class:`~skye.base.dsl.FlowSpec`.
        registry: The dictionary of name to ``Runnable`` (empty when none was given).

    Example:
        >>> flow = Flow.from_file(
        ...     "app.skye", name="research", registry={"planner": planner}
        ... )  # doctest: +SKIP
        >>> flow.check()  # doctest: +SKIP
        []
    """

    def __init__(self, spec: FlowSpec, *, registry: Mapping[str, Any] | None = None) -> None:
        self.spec = spec
        self.registry: Mapping[str, Any] = registry if registry is not None else {}
        self._checked_names = registry is not None

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        *,
        name: str | None = None,
        registry: Mapping[str, Any] | None = None,
    ) -> Flow:
        """Load the ``flow`` block of a ``.skye`` file (an unchanged file is not parsed again).

        Args:
            path: The ``.skye`` file.
            name: The label of the flow; optional when the file holds one flow.
            registry: The steps by name. When given, every ``registry.NAME`` must be one of its
                keys.

        Raises:
            ConfigurationError: If the file is missing, has mistakes, or ``name`` is needed or
                unknown.
        """
        names = None if registry is None else list(registry)
        return cls._from_document(load_document(path, registry_names=names), name, registry)

    @classmethod
    def from_text(
        cls,
        text: str,
        *,
        name: str | None = None,
        registry: Mapping[str, Any] | None = None,
        filename: str | None = None,
    ) -> Flow:
        """Load the ``flow`` block of a ``.skye`` text.

        Args:
            text: The ``.skye`` text.
            name: The label of the flow; optional when the text holds one flow.
            registry: The steps by name. When given, every ``registry.NAME`` must be one of its
                keys.
            filename: The name shown in error messages (``<string>`` by default).

        Raises:
            ConfigurationError: If the text has mistakes, or ``name`` is needed or unknown.
        """
        names = None if registry is None else list(registry)
        return cls._from_document(
            build_cached(text, filename=filename, registry_names=names), name, registry
        )

    @classmethod
    def _from_document(
        cls, document: Document, name: str | None, registry: Mapping[str, Any] | None
    ) -> Flow:
        if document.diagnostics:
            raise diagnostics_error(document)
        try:
            spec = document.flow(name)
        except KeyError as exc:
            raise ConfigurationError(
                f"{document.filename}: {exc.args[0]}", details={"path": document.filename}
            ) from exc
        return cls(spec, registry=registry)

    @property
    def name(self) -> str:
        """The label of the flow."""
        return self.spec.name

    def check(self) -> list[Diagnostic]:
        """Check the flow again, with the keys of the registry when one was given.

        Returns:
            The mistakes (empty when the flow is valid). Useful after the registry changed.
        """
        names: Collection[str] | None = list(self.registry) if self._checked_names else None
        return check_text(self.to_text(), self.name, names)

    def to_text(self) -> str:
        """The flow written back as ``.skye`` text (comments are not kept)."""
        return to_text(self.spec)

    def run(self, *args: Any, **kwargs: Any) -> Any:
        """Run the flow. Not built yet.

        Raises:
            NotImplementedError: Always: the flow runtime is not built yet (spec
                ``3-runtime-flows``).
        """
        raise NotImplementedError(_NOT_BUILT)

    def __repr__(self) -> str:
        return f"Flow(name={self.name!r}, steps={len(self.spec.nodes)})"


__all__ = ["Flow"]
