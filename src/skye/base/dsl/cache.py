# O37
"""A small in-memory cache of built documents, keyed by a hash of the text.

Parsing and checking a ``.skye`` text is the expensive part of loading it. When the same text is
built again (the file
did not change) the cached :class:`~skye.base.dsl.build.Document` is returned and nothing is parsed.

* The key is the SHA-256 of the text, with the file name and the registry names in it (they change
  the diagnostics).
  SHA-256 is as fast as MD5 on a configuration file and it works on builds where MD5 is disabled
  (FIPS).
* The cache is bounded (least recently used leaves first), so a long-running process does not grow.
* A cached document is **read-only**: callers read the specs and never change them. Every caller
  that needs an object
  builds a new one from the specs (the router builds a new configuration dictionary each time).
* Nothing relies on the cache: a cold process (a new serverless container) parses once and fills it.
  It is an
  optimisation, never a place where state lives.

This module reads no file; the code that reads a file and also skips the read when the file did not
change is
``skye.utils.skye_files`` (the cache on disk is open decision).
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from collections.abc import Collection, Hashable
from dataclasses import dataclass

from skye.base.dsl.build import Document, build
from skye.base.dsl.include import INCLUDE_LINE, Resolver

#: How many documents are kept.
MAX_ENTRIES = 64

_Key = tuple[str, str, frozenset[str] | None, Hashable]


@dataclass(frozen=True, kw_only=True)
class CacheInfo:
    """What the cache holds and how well it works.

    Attributes:
        hits: Times a document was found.
        misses: Times a text had to be built.
        size: Documents held now.
        maxsize: The most documents held.
    """

    hits: int
    misses: int
    size: int
    maxsize: int


_lock = threading.Lock()
_entries: OrderedDict[_Key, Document] = OrderedDict()
_stats = {"hits": 0, "misses": 0}


def text_digest(text: str) -> str:
    """The SHA-256 of a text, as hexadecimal."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cache_key(
    text: str,
    filename: str | None,
    registry_names: Collection[str] | None,
    fingerprint: Hashable = None,
) -> _Key:
    """The key under which a text is cached (its digest, its file name, the registry names and the
    fingerprint of the files an include reads)."""
    names = None if registry_names is None else frozenset(registry_names)
    return (text_digest(text), filename or "", names, fingerprint)


def remember(key: _Key, document: Document) -> Document:
    """Store a document under a key and drop the least recently used one if the cache is full."""
    with _lock:
        _entries[key] = document
        _entries.move_to_end(key)
        while len(_entries) > MAX_ENTRIES:
            _entries.popitem(last=False)
    return document


def recall(key: _Key) -> Document | None:
    """The document stored under a key, or ``None`` (counts a hit or a miss)."""
    with _lock:
        document = _entries.get(key)
        if document is None:
            _stats["misses"] += 1
            return None
        _entries.move_to_end(key)
        _stats["hits"] += 1
        return document


def build_cached(
    text: str,
    *,
    filename: str | None = None,
    registry_names: Collection[str] | None = None,
    resolver: Resolver | None = None,
    key: str | None = None,
) -> Document:
    """:func:`~skye.base.dsl.build`, skipping the parse when the same text was built before.

    A text with an ``include`` or a ``from ... import`` line depends on files that the text does not
    hold, so it is cached only when the resolver has a ``fingerprint()`` (what changes when those
    files change) and the fingerprint is part of the key; without one it is built every time.

    Args:
        text: The ``.skye`` text.
        filename: The name used in diagnostics.
        registry_names: The names the caller will pass in its registry (``None`` = not checked).
        resolver: Gives the text of the files that an include names (see :func:`build`).
        key: The identity of the file for the resolver.

    Returns:
        The document. **Treat it as read-only**: it is shared by every caller that builds the same
        text.
    """
    fingerprint = None
    if INCLUDE_LINE.search(text):
        fingerprint_of = getattr(resolver, "fingerprint", None)
        if fingerprint_of is None:
            return build(
                text, filename=filename, registry_names=registry_names, resolver=resolver, key=key
            )
        fingerprint = fingerprint_of()
    entry = cache_key(text, filename, registry_names, fingerprint)
    cached = recall(entry)
    if cached is not None:
        return cached
    built = build(
        text, filename=filename, registry_names=registry_names, resolver=resolver, key=key
    )
    return remember(entry, built)


def clear_cache() -> None:
    """Forget every cached document and reset the counters."""
    with _lock:
        _entries.clear()
        _stats["hits"] = 0
        _stats["misses"] = 0


def cache_info() -> CacheInfo:
    """The counters and the size of the cache."""
    with _lock:
        return CacheInfo(
            hits=_stats["hits"], misses=_stats["misses"], size=len(_entries), maxsize=MAX_ENTRIES
        )


__all__ = [
    "MAX_ENTRIES",
    "CacheInfo",
    "build_cached",
    "cache_info",
    "cache_key",
    "clear_cache",
    "recall",
    "remember",
    "text_digest",
]
