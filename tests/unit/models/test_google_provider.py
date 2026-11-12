"""Unit tests for the Google provider (stdlib REST adapter, no vendor SDK)."""

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

import skye.models.plugins.google.embeddings as emb_mod
import skye.models.plugins.google.multimodal_embeddings as mm_mod
import skye.models.plugins.google.provider as prov_mod
from skye.auth.plugins.google.source import GoogleBearerAuth
from skye.base.completion import CapabilityCall, CompleteRequest, CompleteResponse, StreamChunk
from skye.base.exceptions import ProviderError
from skye.base.messages import AssistantMessage, CapabilityMessage, SystemMessage, UserMessage
from skye.models.plugins.google.provider import GoogleProvider
from skye.models.utilities.rest import JsonObject

URL = (
    "https://us-central1-aiplatform.googleapis.com/v1/projects/my-project/locations/us-central1"
    "/publishers/google/models/gemini-1.5-pro"
)


def make(**kw: object) -> GoogleProvider:
    kw.setdefault("credentials", GoogleBearerAuth("tok"))
    return GoogleProvider(project_id="my-project", location="us-central1", **kw)


def req(**kw: object) -> CompleteRequest:
    kw.setdefault("messages", [UserMessage(content="Hello")])
    kw.setdefault("model", "gemini-1.5-pro")
    return CompleteRequest(**kw)


def gen_response(parts: list, finish: str = "STOP", usage: dict | None = None) -> JsonObject:
    data: dict = {
        "candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": finish}],
        "responseId": "r1",
        "modelVersion": "gemini-1.5-pro-002",
    }
    if usage is not None:
        data["usageMetadata"] = usage
    return JsonObject(data)


class TestNoSdk:
    def test_no_vendor_sdk_imports(self) -> None:
        for mod in (prov_mod, emb_mod, mm_mod):
            tree = ast.parse(Path(mod.__file__).read_text())
            names = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
            names += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
            assert not [n for n in names if n.startswith(("google.cloud", "vertexai", "google.auth"))]

    def test_client_is_none(self) -> None:
        assert make().client is None


class TestInit:
    def test_required(self) -> None:
        p = GoogleProvider(project_id="my-project", location="us-central1")
        assert (p.project_id, p.location, p.credentials) == ("my-project", "us-central1", None)

    def test_credentials_and_registration(self) -> None:
        import skye.models  # noqa: F401
        from skye.base.plugins import get_registrar

        p = GoogleProvider(project_id="p", location="europe-west1", credentials="token")
        assert p.credentials == "token"
        assert get_registrar().get("provider", "google", "model") is GoogleProvider

    def test_str_credentials_become_bearer(self) -> None:
        auth = GoogleProvider(project_id="p", credentials="abc").authenticator
        assert auth.apply("POST", "u", {})["Authorization"] == "Bearer abc"

    def test_global_location_host(self) -> None:
        assert prov_mod._model_url("global", "p", "m", "predict").startswith(
            "https://aiplatform.googleapis.com/v1/projects/p/locations/global/"
        )


class TestRequestTransformation:
    def test_basic(self) -> None:
        r = make()._transform_request(req(temperature=0.7))
        assert r["model"] == "gemini-1.5-pro"
        assert r["generationConfig"]["temperature"] == 0.7
        assert r["contents"] == [{"role": "user", "parts": [{"text": "Hello"}]}]
        assert "systemInstruction" not in r

    def test_system_goes_to_system_instruction(self) -> None:
        r = make()._transform_request(
            req(messages=[SystemMessage(content="Be nice"), UserMessage(content="Hi"), AssistantMessage(content="Yo")])
        )
        assert r["systemInstruction"] == {"parts": [{"text": "Be nice"}]}
        assert [c["role"] for c in r["contents"]] == ["user", "model"]

    def test_generation_config_fields(self) -> None:
        cfg = make()._transform_request(req(max_tokens=100, top_p=0.9, stop=["END"]))["generationConfig"]
        assert (cfg["maxOutputTokens"], cfg["topP"], cfg["stopSequences"]) == (100, 0.9, ["END"])

    def test_empty_messages_rejected(self) -> None:
        with pytest.raises(ValueError):
            make()._transform_request(SimpleNamespace(messages=[]))  # type: ignore[arg-type]

    def test_safety_grounding_passthrough(self) -> None:
        safety = [{"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"}]
        r = make()._transform_request(
            req(metadata={"safety_settings": safety, "grounding": {"googleSearchRetrieval": {}}, "google_cachedContent": "c"})
        )
        assert r["safetySettings"] == safety
        assert r["tools"] == [{"googleSearchRetrieval": {}}]
        assert r["cachedContent"] == "c"

    def test_capability_messages(self) -> None:
        msgs = make()._transform_messages(
            [
                AssistantMessage(content="", capability_calls=[{"id": "1", "type": "function", "function": {"name": "f", "arguments": '{"a": 1}'}}]),
                CapabilityMessage(content="ok", capability_name="f", capability_id="1"),
            ]
        )
        assert msgs[0]["parts"] == [{"functionCall": {"name": "f", "args": {"a": 1}}}]
        assert msgs[1]["parts"][0]["functionResponse"]["name"] == "f"

    def test_capabilities_and_choice(self) -> None:
        caps = [{"type": "function", "function": {"name": "w", "description": "d", "parameters": {"type": "object", "properties": {}}}}]
        p = make()
        r = p._transform_request(req(capabilities=caps))
        assert r["tools"] == [{"functionDeclarations": [{"name": "w", "description": "d", "parameters": {"type": "object", "properties": {}}}]}]
        assert "toolConfig" not in r
        cases = {
            "auto": {"mode": "AUTO"},
            "required": {"mode": "ANY"},
            "none": {"mode": "NONE"},
            "w": {"mode": "ANY", "allowedFunctionNames": ["w"]},
        }
        for choice, cfg in cases.items():
            r = p._transform_request(req(capabilities=caps, capability_choice=choice))
            assert r["toolConfig"] == {"functionCallingConfig": cfg}

    def test_capability_interface(self) -> None:
        from skye.tools import LocalFunctionCapability

        def get_weather(location: str) -> str:
            """Get weather for a location."""
            return location

        r = make()._transform_request(req(capabilities=[LocalFunctionCapability(get_weather)]))
        decl = r["tools"][0]["functionDeclarations"][0]
        assert decl["name"] == "get_weather" and decl["parameters"]["type"] == "object"


class TestResponseTransformation:
    def test_text_and_usage(self) -> None:
        resp = make()._transform_response(
            gen_response([{"text": "Hel"}, {"text": "lo"}], "MAX_TOKENS", {"promptTokenCount": 10, "candidatesTokenCount": 5, "totalTokenCount": 15})
        )
        assert isinstance(resp, CompleteResponse)
        assert (resp.content, resp.finish_reason, resp.provider) == ("Hello", "max_tokens", "google")
        assert (resp.id, resp.model) == ("r1", "gemini-1.5-pro-002")
        assert (resp.usage.prompt_tokens, resp.usage.completion_tokens, resp.usage.total_tokens) == (10, 5, 15)
        assert resp.capability_calls is None

    def test_no_usage(self) -> None:
        resp = make()._transform_response(gen_response([{"text": "x"}]))
        assert resp.usage.total_tokens == 0

    def test_plain_dict_accepted(self) -> None:
        resp = make()._transform_response({"candidates": [{"content": {"parts": [{"text": "d"}]}}]})
        assert resp.content == "d" and resp.finish_reason == "stop"

    def test_function_calls(self) -> None:
        r = gen_response([{"functionCall": {"name": "w", "args": {"city": "NYC"}}}, {"functionCall": {"name": "t", "args": {}}}])
        resp = make()._transform_response(r)
        assert resp.capability_calls == [
            CapabilityCall(id="google_call_0", name="w", arguments={"city": "NYC"}),
            CapabilityCall(id="google_call_1", name="t", arguments={}),
        ]
        assert resp.metadata["candidates"][0]["content"]["parts"][0]["functionCall"]["args"] == {"city": "NYC"}

    def test_extract_none(self) -> None:
        p = make()
        assert p._extract_capability_calls(gen_response([{"text": "x"}])) is None
        assert p._extract_capability_calls(JsonObject({})) is None

    def test_handler_parses_metadata(self) -> None:
        from skye.tools import CapabilityRegistry, LocalFunctionCapability
        from skye.tools.capability_call_handler import CapabilityCallHandler

        def get_weather(location: str) -> str:
            """Get weather for a location."""
            return location

        registry = CapabilityRegistry.get_instance()
        registry.register(LocalFunctionCapability(get_weather))
        try:
            p = make()
            resp = p._transform_response(gen_response([{"functionCall": {"name": "get_weather", "args": {"location": "NYC"}}}]))
            calls = CapabilityCallHandler(registry).parse_capability_calls(resp, p)
            assert [(c.name, c.arguments) for c in calls] == [("get_weather", {"location": "NYC"})]
        finally:
            registry.unregister("get_weather")

    def test_stream_chunk(self) -> None:
        p = make()
        c = p._transform_stream_chunk(gen_response([{"text": "Hi"}], "FINISH_REASON_UNSPECIFIED"))
        assert isinstance(c, StreamChunk) and c.delta == "Hi" and c.finish_reason is None
        c = p._transform_stream_chunk(JsonObject({"candidates": [{"content": {"parts": [{"text": "!"}]}, "finishReason": "STOP"}]}))
        assert c.delta == "!" and c.finish_reason == "stop"
        assert p._transform_stream_chunk(JsonObject({})).delta == ""


class TestCalls:
    def test_complete_rest_call(self) -> None:
        r = gen_response([{"text": "Hello!"}], usage={"promptTokenCount": 1, "candidatesTokenCount": 2, "totalTokenCount": 3})
        with patch("skye.models.utilities.rest.post_json", return_value=r) as post:
            resp = make().complete(req(messages=[SystemMessage(content="s"), UserMessage(content="Hello")], temperature=0.5))
        assert resp.content == "Hello!"
        url, body = post.call_args[0]
        assert url == URL + ":generateContent"
        assert "model" not in body
        assert body["systemInstruction"] == {"parts": [{"text": "s"}]}
        assert body["contents"] == [{"role": "user", "parts": [{"text": "Hello"}]}]
        assert body["generationConfig"]["temperature"] == 0.5
        auth = post.call_args.kwargs["authenticator"]
        assert auth.apply("POST", url, {})["Authorization"] == "Bearer tok"

    def test_complete_error(self) -> None:
        with patch("skye.models.utilities.rest.post_json", side_effect=Exception("boom")):
            with pytest.raises(ProviderError):
                make().complete(req())

    def test_stream_rest_call(self) -> None:
        events = iter([gen_response([{"text": "a"}]), gen_response([{"text": "b"}], "STOP")])
        with patch("skye.models.utilities.rest.stream_sse_json", return_value=events) as sse:
            chunks = list(make().stream(req()))
        assert [c.delta for c in chunks] == ["a", "b"]
        assert chunks[-1].finish_reason == "stop"
        assert sse.call_args[0][0] == URL + ":streamGenerateContent?alt=sse"
        assert "model" not in sse.call_args[0][1]

    def test_acomplete(self) -> None:
        with patch("skye.models.utilities.rest.post_json", return_value=gen_response([{"text": "async"}])):
            resp = asyncio.run(make().acomplete(req()))
        assert resp.content == "async"

    def test_end_to_end_headers_and_body_via_http(self) -> None:
        """Real post_json over a patched base.http.send_bytes: URL, auth header and JSON body."""
        import json

        raw = json.dumps({"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}).encode()
        with patch("skye.base.http.send_bytes", return_value=raw) as send:
            resp = make().complete(req())
        assert resp.content == "ok"
        assert send.call_args[0][0] == URL + ":generateContent"
        assert send.call_args.kwargs["headers"]["Authorization"] == "Bearer tok"
        assert json.loads(send.call_args[0][1])["contents"][0]["parts"][0]["text"] == "Hello"


class TestMisc:
    def test_model_info(self) -> None:
        info = make().get_model_info()
        assert info["provider"] == "google" and info["supports_streaming"] and info["supports_multimodal"]

    def test_format_capability_results(self) -> None:
        results = [
            Mock(name_="x", error=None, result={"a": 1}),
            Mock(error="bad", result=None),
            Mock(error=None, result='{"b": 2}'),
            Mock(error=None, result="plain"),
        ]
        for i, n in enumerate(["a", "b", "c", "d"]):
            results[i].name = n
        out = make().format_capability_results(results)
        assert [o["functionResponse"]["response"] for o in out] == [{"a": 1}, {"error": "bad"}, {"b": 2}, {"result": "plain"}]
