# Requirement 62.7, D111
"""``OpenApiToolkit``: the built-in toolkit ``openapi``, one tool for each operation of an OpenAPI
document.

The option ``spec`` is required: a mapping (a document already loaded), the path of a JSON file, or
an ``http`` or ``https`` address of a JSON
document (read once, at construction). There is no YAML. Each operation that has an ``operationId``
is a tool of that name. When ``allow`` is not
given only the GET operations are tools; ``allow`` lists the ``operationId`` values that are tools,
whatever their method. The tools take the path and
the query parameters and, for an operation with a JSON body, a ``body`` object. A call goes only to
``base_url`` (the first ``servers`` entry of the
document when the option is not given): a path parameter is encoded as one path segment and cannot
change the host. The headers are sent and never
returned: no error and no log holds them.

Example:
    >>> import asyncio
    >>> parameter = {"name": "id", "in": "path", "schema": {"type": "integer"}}
    >>> get = {"operationId": "getPet", "summary": "Get a pet", "parameters": [parameter]}
    >>> paths = {"/pets/{id}": {"get": get}}
    >>> doc = {"openapi": "3.0.0", "servers": [{"url": "https://api.example.com"}], "paths": paths}
    >>> [schema.name for schema in asyncio.run(OpenApiToolkit(spec=doc).list_schemas())]
    ['openapi_getPet']

Raises: ``ValidationError`` at construction when ``spec`` is missing, cannot be read, is YAML or is
not an OpenAPI document, when no ``base_url`` is
    known, or an option is not valid; a tool raises ``CapabilityError`` for a missing or unknown
    argument and for an HTTP status of 400 or more, and
    ``run`` turns it into a message whose status is ``error``.
Missing: the bytes of a long response past ``max_bytes`` are not returned, and the result says so;
an operation with no ``operationId`` is not a tool.
Concurrency: the toolkit holds only its settings and the tools made at construction, so several
tasks may call it at once (a call runs in a thread).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import urllib.parse
from collections.abc import Mapping
from typing import Any

from skye.base import http
from skye.base.exceptions import CapabilityError, ProviderError, ValidationError
from skye.base.interfaces.capability import CapabilityInterface, CapabilitySchema
from skye.tools.toolkit import Toolkit

_METHODS = ("get", "post", "put", "patch", "delete")
# : How many ``$ref`` a resolved node may follow; a deeper one, or a cyclic one, is replaced by a
# plain object.
_REF_DEPTH = 5
_OBJECT: dict[str, Any] = {"type": "object"}


def _deref(node: Any, doc: Mapping[str, Any], chain: tuple[str, ...] = ()) -> Any:
    """``node`` with every ``#/components/...`` reference replaced by what it points at, to the
    depth of ``_REF_DEPTH``."""
    if isinstance(node, list):
        return [_deref(item, doc, chain) for item in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if ref is None:
        return {key: _deref(value, doc, chain) for key, value in node.items()}
    if (
        not isinstance(ref, str)
        or not ref.startswith("#/components/")
        or ref in chain
        or len(chain) >= _REF_DEPTH
    ):
        return dict(_OBJECT)
    target: Any = doc
    for part in ref[2:].split("/"):
        target = (
            target.get(part.replace("~1", "/").replace("~0", "~"))
            if isinstance(target, dict)
            else None
        )
    return _deref(target, doc, (*chain, ref)) if isinstance(target, dict) else dict(_OBJECT)


def _read(spec: Any, timeout: float) -> Mapping[str, Any]:
    """The OpenAPI document of the option ``spec``."""
    if spec is None or spec == "":
        raise ValidationError(
            "the toolkit 'openapi' needs the option spec, the OpenAPI document",
            field="spec",
            value=None,
        )
    if isinstance(spec, Mapping):
        doc: Any = spec
    else:
        where = os.fspath(spec) if isinstance(spec, os.PathLike) else spec
        if not isinstance(where, str):
            raise ValidationError(
                "the option spec must be a mapping, a path or an address",
                field="spec",
                value=type(spec).__name__,
            )
        if where.lower().endswith((".yaml", ".yml")):
            raise ValidationError(
                f"the option spec {where!r} is YAML; the toolkit 'openapi' reads JSON only",
                field="spec",
                value=where,
            )
        try:
            if where.startswith(("http://", "https://")):
                doc = http.request(where, "GET", timeout=timeout, provider="openapi").json()
            else:
                with open(where, encoding="utf-8") as handle:
                    doc = json.load(handle)
        except (OSError, ValueError, ProviderError) as error:
            raise ValidationError(
                f"the option spec {where!r} cannot be read as a JSON document: {error}",
                field="spec",
                value=where,
            ) from None
    if not isinstance(doc, Mapping) or not isinstance(doc.get("paths"), Mapping):
        raise ValidationError(
            "the option spec is not an OpenAPI document (it has no 'paths')",
            field="spec",
            value=None,
        )
    return doc


class _Operation(CapabilityInterface):
    """One operation of the document as a capability: it builds the request, sends it and returns
    the text of the response."""

    def __init__(
        self,
        toolkit: OpenApiToolkit,
        schema: CapabilitySchema,
        method: str,
        path: str,
        where: dict[str, str],
    ) -> None:
        self._toolkit, self._schema, self._method, self._path, self._where = (
            toolkit,
            schema,
            method,
            path,
            where,
        )

    def get_schema(self) -> CapabilitySchema:
        return self._schema

    def execute(self, **kwargs: Any) -> str:
        return self._toolkit._send(self._schema, self._method, self._path, self._where, kwargs)

    async def aexecute(self, **kwargs: Any) -> str:
        return await asyncio.to_thread(self.execute, **kwargs)


class OpenApiToolkit(Toolkit):
    """One tool for each operation of an OpenAPI document.

    Args:
        spec: The document: a mapping, the path of a JSON file or an ``http(s)`` address. Required.
        base_url: Where the calls go. The default is the first ``servers`` entry of the document.
        headers: Headers sent with every call, for example an ``Authorization`` key. Never returned
            or logged.
        allow: The ``operationId`` values that are tools. When ``None``, the GET operations are.
        timeout: Seconds to wait for a response (and for the document, when ``spec`` is an address).
        max_bytes: The most bytes of one response that are returned.
    """

    def __init__(
        self,
        *,
        spec: Any = None,
        base_url: str | None = None,
        headers: Mapping[str, str] | None = None,
        allow: list[str] | tuple[str, ...] | None = None,
        timeout: float = 30.0,
        max_bytes: int = 65536,
    ) -> None:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValidationError(
                "the option timeout of the toolkit 'openapi' must be a positive number",
                field="timeout",
                value=timeout,
            )
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
            raise ValidationError(
                "the option max_bytes of the toolkit 'openapi' must be a positive number",
                field="max_bytes",
                value=max_bytes,
            )
        if allow is not None and not (
            isinstance(allow, (list, tuple)) and all(isinstance(item, str) for item in allow)
        ):
            raise ValidationError(
                "the option allow must be a list of operationId values", field="allow", value=allow
            )
        if headers is not None and not (
            isinstance(headers, Mapping)
            and all(isinstance(k, str) and isinstance(v, str) for k, v in headers.items())
        ):
            raise ValidationError(
                "the option headers must map text to text", field="headers", value=None
            )
        doc = _read(spec, float(timeout))
        servers = doc.get("servers")
        url = base_url or (
            servers[0].get("url")
            if isinstance(servers, list) and servers and isinstance(servers[0], dict)
            else None
        )
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            raise ValidationError(
                "the toolkit 'openapi' needs the option base_url: the document has no server with "
                "an http(s) address",
                field="base_url",
                value=url,
            )
        self._base = url.rstrip("/")
        self._headers = dict(headers or {})
        self._timeout, self._max_bytes = float(timeout), max_bytes
        self._add_tools(self._operations(doc, None if allow is None else set(allow)))

    def _operations(self, doc: Mapping[str, Any], allow: set[str] | None) -> list[_Operation]:
        tools: list[_Operation] = []
        for path, item in doc["paths"].items():
            item = _deref(item, doc)
            if not isinstance(item, dict) or not isinstance(path, str) or not path.startswith("/"):
                continue
            for method in _METHODS:
                op = item.get(method)
                if not isinstance(op, dict) or not isinstance(op.get("operationId"), str):
                    continue
                chosen = method == "get" if allow is None else op["operationId"] in allow
                if not chosen:
                    continue
                tools.append(self._tool(method, path, op, item.get("parameters")))
        return tools

    def _tool(self, method: str, path: str, op: dict[str, Any], shared: Any) -> _Operation:
        properties: dict[str, Any] = {}
        required: list[str] = []
        where: dict[str, str] = {}
        for param in [*(shared if isinstance(shared, list) else []), *(op.get("parameters") or [])]:
            if (
                not isinstance(param, dict)
                or param.get("in") not in ("path", "query")
                or not isinstance(param.get("name"), str)
            ):
                continue
            declared = param.get("schema")
            entry = {
                "type": declared.get("type", "string") if isinstance(declared, dict) else "string"
            }
            if param.get("description"):
                entry["description"] = str(param["description"])
            properties[param["name"]] = entry
            where[param["name"]] = param["in"]
            if param["in"] == "path" or param.get("required") is True:
                required.append(param["name"])
        request: dict[str, Any] = op.get("requestBody") or {}
        body = (request.get("content") or {}).get("application/json")
        if isinstance(body, dict):
            properties["body"] = (
                body["schema"] if isinstance(body.get("schema"), dict) else dict(_OBJECT)
            )
            if request.get("required") is True:
                required.append("body")
        text = (
            str(op.get("summary") or op.get("description") or f"{method.upper()} {path}")
            .strip()
            .splitlines()[0]
        )
        name = re.sub(r"[^A-Za-z0-9_-]", "_", op["operationId"])
        schema = CapabilitySchema(
            name=name,
            description=text,
            parameters={"type": "object", "properties": properties, "required": required},
        )
        return _Operation(self, schema, method.upper(), path, where)

    def _send(
        self,
        schema: CapabilitySchema,
        method: str,
        path: str,
        where: dict[str, str],
        arguments: dict[str, Any],
    ) -> str:
        known = schema.parameters["properties"]
        unknown = sorted(set(arguments) - set(known))
        if unknown:
            raise CapabilityError(
                f"unknown argument {unknown[0]!r}; the arguments are {sorted(known)}"
            )
        missing = [name for name in schema.parameters["required"] if name not in arguments]
        if missing:
            raise CapabilityError(f"the argument {missing[0]!r} is required")
        for name, place in where.items():
            if place == "path":
                path = path.replace(
                    "{" + name + "}", urllib.parse.quote(str(arguments[name]), safe="")
                )
        query = {
            name: arguments[name]
            for name, place in where.items()
            if place == "query" and arguments.get(name) is not None
        }
        url = self._base + path
        if urllib.parse.urlsplit(url).netloc != urllib.parse.urlsplit(self._base).netloc:
            raise CapabilityError(
                "the call would leave the base address"
            )  # pragma: no cover - the segments are encoded
        try:
            response = http.request(
                url,
                method,
                params=query or None,
                json_body=arguments.get("body"),
                headers=self._headers,
                timeout=self._timeout,
                provider="openapi",
            )
        except ProviderError as error:
            status = f"HTTP {error.status_code}" if error.status_code else "no response"
            raise CapabilityError(f"the call failed ({status}): {str(error)[:300]}") from None
        if response.status_code >= 400:
            raise CapabilityError(
                f"the call failed (HTTP {response.status_code}): {response.text[:300]}"
            )
        data = response.text.encode("utf-8")
        if len(data) <= self._max_bytes:
            return response.text
        return (
            data[: self._max_bytes].decode("utf-8", "ignore")
            + f"\n[cut: the first {self._max_bytes} of {len(data)} bytes are shown]"
        )
