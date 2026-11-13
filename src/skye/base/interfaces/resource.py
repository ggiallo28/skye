# decision D26, Requirement 10.5
"""Resource Port: list resources and read one by URI (MIME type, text or bytes).

A resource is a named piece of content addressed by a URI. A
listed :class:`Resource` carries only its metadata (``uri``, ``name``, ``mime_type``,
``description``); a resource read by URI also carries its content, either ``text`` or ``data``
(bytes), never both. The MCP clients in ``tools`` implement this Port, so ``prompts`` and
``memory`` consume MCP resources through ``base`` without importing ``tools``. The Port is a
``Protocol``: any class with these two ``async`` methods is a ``ResourceProviderInterface``.

Example:
    >>> import asyncio
    >>> from skye.interfaces import Resource, ResourceProviderInterface
    >>> class Notes:
    ...     async def list_resources(self):
    ...         return [Resource(uri="note://1", name="first", mime_type="text/plain")]
    ...     async def read_resource(self, uri):
    ...         return Resource(uri=uri, name="first", mime_type="text/plain", text="hello")
    >>> isinstance(Notes(), ResourceProviderInterface)
    True
    >>> resource = asyncio.run(Notes().read_resource("note://1"))
    >>> resource.text, resource.has_content
    ('hello', True)

Raises: ``ValidationError`` for a malformed resource (both ``text`` and ``data``, an empty
    ``uri``); a ``SkyeError`` subclass (for example ``ProviderError``) when the source cannot be
    reached or does not know the URI.
Missing: ``list_resources`` returns an empty list when there is nothing to list; a listed
    resource has ``text`` and ``data`` set to ``None``.
Concurrency: both are coroutines and may run in several tasks at once; a ``Resource`` is frozen
    and safe to share.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Protocol, runtime_checkable

from skye.base.exceptions import ValidationError
from skye.base.validated import Validated, field, validated


@validated(frozen=True)
class Resource(Validated):
    """A resource: ``uri`` and ``name`` always, content only after a read.

    Attributes:
        uri: The address of the resource.
        name: A human-readable name (the URI when the source gives none).
        mime_type: The MIME type of the content, when known.
        description: What the resource holds, when given.
        text: The content as text, or ``None``.
        data: The content as bytes, or ``None``; never set together with ``text``.
    """

    uri: str = field(min_length=1, description="The address of the resource")
    name: str = field(description="A human-readable name")
    mime_type: str | None = field(default=None, description="The MIME type of the content")
    description: str | None = field(default=None, description="What the resource holds")
    text: str | None = field(default=None, description="The content as text")
    data: bytes | None = field(default=None, description="The content as bytes")

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.text is not None and self.data is not None:
            raise ValidationError(
                "Invalid value for Resource.data: 'text' and 'data' are mutually exclusive",
                field="data",
                value=self.data,
            )

    @property
    def has_content(self) -> bool:
        """``True`` once the resource was read (it carries ``text`` or ``data``)."""
        return self.text is not None or self.data is not None


@runtime_checkable
class ResourceProviderInterface(Protocol):
    """Lists the resources of a source and reads one by URI."""

    @abstractmethod
    async def list_resources(self) -> list[Resource]:
        """Return the resources the source offers, metadata only."""
        ...

    @abstractmethod
    async def read_resource(self, uri: str) -> Resource:
        """Return the resource at ``uri`` with its content (``text`` or ``data``)."""
        ...


__all__ = ["Resource", "ResourceProviderInterface"]
