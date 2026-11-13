"""Shared by the examples, not part of the package (decision D38): the client to use with or without a provider key.

``get_client("openai")`` returns the real client when OPENAI_API_KEY is set and a scripted client otherwise, and prints which one it is.
The scripted client answers locally and has the shape of a real one: ``complete``, ``acomplete``, ``stream``, ``astream``, capability
calls and structured output. Examples import it with ``sys.path.insert(0, str(Path(__file__).resolve().parents[1]))``.
"""

import os
from typing import Any

import skye
from skye import CapabilityMessage, CompleteResponse, ProviderError, StreamChunk, TokenUsage
from skye.completion import CapabilityCall
from skye.data import from_mapping, json_schema

plugins = skye.Plugins()

KEYS = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "google": "GOOGLE_API_KEY", "cohere": "COHERE_API_KEY"}
REPLY = "Paris is the capital of France."


def _sample(schema: dict[str, Any], root: dict[str, Any]) -> Any:
    """A value that satisfies a JSON Schema: enough to build an instance of the example's dataclass."""
    if "$ref" in schema:
        return _sample(root["$defs"][schema["$ref"].rsplit("/", 1)[-1]], root)
    if "anyOf" in schema:
        return _sample(next(s for s in schema["anyOf"] if s.get("type") != "null"), root)
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "object":
        return {k: _sample(v, root) for k, v in schema.get("properties", {}).items() if k in schema.get("required", [])}
    if kind in ("integer", "number"):
        return schema.get("minimum", schema.get("exclusiveMinimum", 0) + 1)
    if kind == "array":
        return [_sample(schema["items"], root)] if "items" in schema else []
    return {"boolean": True}.get(kind, "sample")


class ScriptedClient:
    """A local stand-in for a provider client: fixed answers, no network."""

    provider_name = "scripted"

    def __init__(self, reply: str = REPLY) -> None:
        self.reply = reply

    def complete(self, messages: Any = None, model: str = "scripted", **options: Any) -> CompleteResponse:
        if hasattr(messages, "messages"):  # one request object instead of messages and options
            request = messages
            messages, model = request.messages, request.model
            options = {"capabilities": request.capabilities, "response_schema": request.response_schema, **options}
        reply: dict[str, Any] = dict(model=model, provider=self.provider_name, usage=TokenUsage(prompt_tokens=8, completion_tokens=8, total_tokens=16))
        capabilities = options.get("capabilities") or []
        results = [m for m in messages or [] if isinstance(m, CapabilityMessage)]
        if capabilities and not results:
            response = CompleteResponse(content="", finish_reason="capability_calls", capability_calls=self._calls(capabilities), **reply)
            response._capabilities = capabilities  # what a real provider does: the response can run its own calls
            return response
        text = "; ".join(f"{m.capability_name}: {m.content}" for m in results) or self.reply
        response = CompleteResponse(content=text, finish_reason="stop", **reply)
        if options.get("response_schema"):
            schema = options["response_schema"]
            response.structured_output = from_mapping(schema, _sample(json_schema(schema), json_schema(schema)))
        return response

    async def acomplete(self, messages: Any = None, model: str = "scripted", **options: Any) -> CompleteResponse:
        return self.complete(messages, model, **options)

    def stream(self, messages: Any = None, model: str = "scripted", **options: Any):
        words = self.reply.split()
        for i, word in enumerate(words):
            yield StreamChunk(id="scripted", delta=word + ("" if i == len(words) - 1 else " "), index=i, finish_reason="stop" if i == len(words) - 1 else None)

    async def astream(self, messages: Any = None, model: str = "scripted", **options: Any):
        for chunk in self.stream(messages, model, **options):
            yield chunk

    @staticmethod
    def _calls(capabilities: list[Any]) -> list[CapabilityCall]:
        calls = []
        for number, capability in enumerate(capabilities, start=1):
            schema = capability.get_schema()
            required = schema.parameters.get("required", [])
            kinds = {k: v.get("type") for k, v in schema.parameters.get("properties", {}).items()}
            arguments = {k: (1 if kinds.get(k) in ("integer", "number") else "Paris") for k in required}
            calls.append(CapabilityCall(id=f"call_{number}", name=schema.name, arguments=arguments))
        return calls


class ScriptedProvider(ScriptedClient):
    """The scripted client under a provider name, so a router can balance it: ``skye.provider`` builds it from the registered name."""

    def __init__(self, **_: Any) -> None:
        super().__init__()


class FlakyProvider(ScriptedProvider):
    """A provider that is always down, to show a fallback without a network."""

    provider_name = "flaky"

    def complete(self, messages: Any = None, model: str = "flaky", **options: Any) -> CompleteResponse:
        raise ProviderError("simulated outage", provider="flaky")


class ScriptedEmbedder:
    """A local stand-in for an embedding client: a small vector made from the letters of the text, so similar texts are close."""

    DIMENSION = 16

    def encode(self, text: str) -> list[float]:
        vector = [0.0] * self.DIMENSION
        for char in text.lower():
            if char.isalpha():
                vector[(ord(char) - 97) % self.DIMENSION] += 1.0
        return vector

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.encode(text) for text in texts]

    async def aencode(self, text: str) -> list[float]:
        return self.encode(text)

    async def aencode_batch(self, texts: list[str]) -> list[list[float]]:
        return self.encode_batch(texts)

    def get_vector_dimension(self) -> int:
        return self.DIMENSION


def get_embedder(provider: str = "openai", model: str = "text-embedding-3-small") -> Any:
    """The real embedding client of ``provider`` when its key is set, the scripted one otherwise; says which."""
    variable = KEYS.get(provider)
    if variable and os.getenv(variable):
        print(f"mode: {provider} embeddings (real, key from {variable})")
        return skye.provider(provider, model=model, api_key=os.environ[variable], provider_type="embedding")
    print(f"mode: scripted embeddings (set {variable or 'the provider key'} to call {provider})")
    return ScriptedEmbedder()


def get_client(provider: str = "openai") -> Any:
    """The real client of ``provider`` when its key is in the environment, the scripted one otherwise; says which."""
    variable = KEYS.get(provider)
    if variable and os.getenv(variable):
        print(f"mode: {provider} (real, key from {variable})")
        return skye.provider(provider, api_key=os.environ[variable])
    print(f"mode: scripted (set {variable or 'the provider key'} to call {provider})")
    return ScriptedClient()


def provider_or_scripted(provider: str, ready: bool, hint: str, **config: Any) -> Any:
    """``skye.provider(provider, **config)`` when ``ready`` (credentials are present), the scripted client otherwise; says which."""
    if ready:
        print(f"mode: {provider} (real)")
        return skye.provider(provider, **config)
    print(f"mode: scripted ({hint} to call {provider})")
    return ScriptedClient()


def router_provider(provider: str = "openai") -> str:
    """The provider name for a router target: the real one with a key, ``scripted`` (registered here) without."""
    variable = KEYS.get(provider)
    if variable and os.getenv(variable):
        return provider
    plugins.provider("scripted", ScriptedProvider, replace=True)
    return "scripted"


def register_demo_providers() -> None:
    """Register ``scripted`` (always answers) and ``flaky`` (always fails) so a router can use them as targets."""
    plugins.provider("scripted", ScriptedProvider, replace=True)
    plugins.provider("flaky", FlakyProvider, replace=True)
