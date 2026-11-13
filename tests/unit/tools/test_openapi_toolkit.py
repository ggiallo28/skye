"""The built-in toolkit ``openapi`` (task 19.2, Requirement 62.7): one tool for each operation of an
OpenAPI document."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import skye
from skye.base import http
from skye.base.exceptions import ProviderError, ValidationError
from skye.base.messages import CapabilityStatus
from skye.completion import CapabilityCall
from skye.tools.plugins.openapi import OpenApiToolkit

DOC: dict[str, Any] = {
    "openapi": "3.0.0",
    "servers": [{"url": "https://api.example.com/v1/"}],
    "paths": {
        "/pets/{petId}": {
            "get": {
                "operationId": "getPet",
                "summary": "Get a pet by its id.\nA second line.",
                "parameters": [
                    {
                        "name": "petId",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    },
                    {"name": "verbose", "in": "query", "schema": {"type": "boolean"}},
                    {"name": "X-Trace", "in": "header", "schema": {"type": "string"}},
                ],
            },
            "delete": {"operationId": "deletePet", "summary": "Delete a pet."},
        },
        "/pets": {
            "post": {
                "operationId": "addPet",
                "summary": "Add a pet.",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/Pet"}}
                    },
                },
            },
            "get": {"summary": "List the pets (no operationId: not a tool)."},
        },
    },
    "components": {
        "schemas": {
            "Pet": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "owner": {"$ref": "#/components/schemas/Owner"},
                },
            },
            "Owner": {
                "type": "object",
                "properties": {"pet": {"$ref": "#/components/schemas/Pet"}},
            },
        }
    },
}


class Recorder:
    """Stands for ``skye.base.http.request``: records each call and answers with what it was
    given."""

    def __init__(self, text: str = "ok", status: int = 200, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.text, self.status, self.error = text, status, error

    def __call__(self, url: str, method: str = "GET", **kwargs: Any) -> http.HttpResponse:
        self.calls.append({"url": url, "method": method, **kwargs})
        if self.error is not None:
            raise self.error
        return http.HttpResponse(status_code=self.status, text=self.text)


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    fake = Recorder()
    monkeypatch.setattr(http, "request", fake)
    return fake


async def call(toolkit: OpenApiToolkit, name: str, **arguments: object):
    return await toolkit.run(CapabilityCall(id="1", name=f"openapi.{name}", arguments=arguments))


async def names(toolkit: OpenApiToolkit) -> list[str]:
    return [schema.name for schema in await toolkit.list_schemas()]


# -- registration
# --------------------------------------------------------------------------------------------------


def test_the_toolkit_is_registered_as_openapi_and_built_by_name():
    assert "openapi" in skye.Plugins().names("toolkit")
    toolkit = skye.toolkit("openapi", spec=DOC)
    assert isinstance(toolkit, OpenApiToolkit)
    assert toolkit.toolkit_name == "openapi"
    assert skye.Plugins().get("toolkit", "openapi") is OpenApiToolkit


def test_a_registrar_with_the_tools_door_gets_the_text_target():
    from skye.base.plugins import Registrar
    from skye.tools import plugins

    registrar = Registrar()
    plugins.register(registrar)
    assert (
        registrar._tables["toolkit"]["openapi"].target
        == "skye.tools.plugins.openapi:OpenApiToolkit"
    )


# -- the tools of a document
# -------------------------------------------------------------------------------------------


async def test_only_the_get_operations_with_an_operation_id_are_tools_by_default():
    assert await names(OpenApiToolkit(spec=DOC)) == ["openapi.getPet"]


async def test_allow_lists_the_tools_whatever_their_method():
    toolkit = OpenApiToolkit(spec=DOC, allow=["addPet", "deletePet"])
    assert await names(toolkit) == ["openapi.addPet", "openapi.deletePet"]


async def test_the_schema_has_the_path_and_query_parameters_and_the_summary():
    schema = (await OpenApiToolkit(spec=DOC).list_schemas())[0]
    assert schema.description == "Get a pet by its id."
    assert schema.parameters["properties"] == {
        "petId": {"type": "integer"},
        "verbose": {"type": "boolean"},
    }
    assert schema.parameters["required"] == ["petId"]  # a header parameter is not an argument


async def test_a_body_parameter_comes_from_the_json_request_body_and_refs_are_resolved_to_a_depth():
    schema = (await OpenApiToolkit(spec=DOC, allow=["addPet"]).list_schemas())[0]
    body = schema.parameters["properties"]["body"]
    assert schema.parameters["required"] == ["body"]
    assert body["properties"]["name"] == {"type": "string"}
    assert (
        body["properties"]["owner"]["type"] == "object"
    )  # Pet -> Owner -> Pet is cyclic: cut to a plain object
    assert "$ref" not in json.dumps(body)


def test_a_name_is_made_of_letters_digits_underscore_and_hyphen():
    doc = {
        "paths": {"/a": {"get": {"operationId": "list pets.v1"}}},
        "servers": [{"url": "https://x.example"}],
    }
    toolkit = OpenApiToolkit(spec=doc)
    assert [t.get_schema().name for _, t in toolkit.__dict__["_skye_extra"]] == ["list_pets_v1"]


# -- the options
# --------------------------------------------------------------------------------------------------


def test_spec_is_required():
    with pytest.raises(ValidationError) as caught:
        OpenApiToolkit()
    assert caught.value.details["field"] == "spec"


def test_a_yaml_path_is_refused(tmp_path: Path):
    path = tmp_path / "api.yaml"
    path.write_text("openapi: 3.0.0\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="YAML"):
        OpenApiToolkit(spec=path)


def test_a_json_file_is_read(tmp_path: Path):
    path = tmp_path / "api.json"
    path.write_text(json.dumps(DOC), encoding="utf-8")
    assert OpenApiToolkit(spec=str(path))._base == "https://api.example.com/v1"


def test_an_unreadable_or_not_openapi_spec_is_refused(tmp_path: Path):
    with pytest.raises(ValidationError, match="cannot be read"):
        OpenApiToolkit(spec=tmp_path / "missing.json")
    with pytest.raises(ValidationError, match="no 'paths'"):
        OpenApiToolkit(spec={"info": {}})


def test_an_address_is_fetched_once_with_the_library_http_helper(recorder: Recorder):
    recorder.text = json.dumps(DOC)
    toolkit = OpenApiToolkit(spec="https://example.com/openapi.json", timeout=5)
    assert [(c["url"], c["method"], c["timeout"]) for c in recorder.calls] == [
        ("https://example.com/openapi.json", "GET", 5.0)
    ]
    assert toolkit._base == "https://api.example.com/v1"


def test_base_url_defaults_to_the_first_server_and_is_otherwise_required():
    assert (
        OpenApiToolkit(spec=DOC, base_url="https://other.example/")._base == "https://other.example"
    )
    bare = {"paths": {"/a": {"get": {"operationId": "a"}}}}
    with pytest.raises(ValidationError) as caught:
        OpenApiToolkit(spec=bare)
    assert caught.value.details["field"] == "base_url"
    with pytest.raises(ValidationError):
        OpenApiToolkit(
            spec={**bare, "servers": [{"url": "/relative"}]}
        )  # a relative server is not an address


@pytest.mark.parametrize(
    "options",
    [
        {"timeout": 0},
        {"timeout": True},
        {"max_bytes": 0},
        {"allow": "getPet"},
        {"headers": {"A": 1}},
    ],
)
def test_a_bad_option_is_a_validation_error(options: dict[str, Any]):
    with pytest.raises(ValidationError):
        OpenApiToolkit(spec=DOC, **options)


# -- a call
# --------------------------------------------------------------------------------------------------


async def test_a_call_builds_the_url_the_query_and_the_headers(recorder: Recorder):
    toolkit = OpenApiToolkit(spec=DOC, headers={"Authorization": "Bearer s3cret"}, timeout=7)
    message = await call(toolkit, "getPet", petId=42, verbose=True)
    assert message.status == CapabilityStatus.OK and message.content == "ok"
    (sent,) = recorder.calls
    assert sent["url"] == "https://api.example.com/v1/pets/42"
    assert sent["method"] == "GET" and sent["params"] == {"verbose": True}
    assert (
        sent["headers"] == {"Authorization": "Bearer s3cret"}
        and sent["timeout"] == 7.0
        and sent["json_body"] is None
    )


async def test_a_path_parameter_is_one_encoded_segment_and_cannot_change_the_host(
    recorder: Recorder,
):
    toolkit = OpenApiToolkit(spec=DOC)
    await call(toolkit, "getPet", petId="../evil.example/x?y=1#z")
    assert (
        recorder.calls[0]["url"]
        == "https://api.example.com/v1/pets/..%2Fevil.example%2Fx%3Fy%3D1%23z"
    )
    assert recorder.calls[0]["params"] is None


async def test_a_post_sends_the_json_body(recorder: Recorder):
    toolkit = OpenApiToolkit(spec=DOC, allow=["addPet"])
    await call(toolkit, "addPet", body={"name": "Rex"})
    assert recorder.calls[0]["method"] == "POST" and recorder.calls[0]["json_body"] == {
        "name": "Rex"
    }
    assert recorder.calls[0]["url"] == "https://api.example.com/v1/pets"


async def test_a_missing_or_unknown_argument_is_an_error_message_and_nothing_is_sent(
    recorder: Recorder,
):
    toolkit = OpenApiToolkit(spec=DOC)
    missing = await call(toolkit, "getPet")
    unknown = await call(toolkit, "getPet", petId=1, colour="red")
    assert missing.status == unknown.status == CapabilityStatus.ERROR
    assert (
        "'petId' is required" in missing.content and "unknown argument 'colour'" in unknown.content
    )
    assert recorder.calls == []


async def test_a_long_response_is_cut_with_a_marker(recorder: Recorder):
    recorder.text = "é" * 100  # 200 bytes
    toolkit = OpenApiToolkit(spec=DOC, max_bytes=51)
    message = await call(toolkit, "getPet", petId=1)
    body, _, marker = message.content.partition("\n")
    assert body == "é" * 25 and marker == "[cut: the first 51 of 200 bytes are shown]"


async def test_an_error_status_is_an_error_message_that_never_holds_the_headers(recorder: Recorder):
    recorder.error = ProviderError("HTTP 404: no such pet", provider="openapi", status_code=404)
    toolkit = OpenApiToolkit(spec=DOC, headers={"Authorization": "Bearer s3cret"})
    message = await call(toolkit, "getPet", petId=1)
    assert message.status == CapabilityStatus.ERROR
    assert "HTTP 404" in message.content and "no such pet" in message.content
    assert "s3cret" not in message.content and "Authorization" not in message.content


async def test_a_response_with_a_status_of_400_or_more_is_an_error_even_if_the_helper_did_not_raise(
    recorder: Recorder,
):
    recorder.status, recorder.text = 500, "boom"
    message = await call(
        OpenApiToolkit(spec=DOC, headers={"Authorization": "k"}), "getPet", petId=1
    )
    assert (
        message.status == CapabilityStatus.ERROR
        and "HTTP 500" in message.content
        and "boom" in message.content
    )


async def test_a_transport_failure_is_an_error_message(recorder: Recorder):
    recorder.error = ProviderError("Transport error: refused", provider="openapi")
    message = await call(OpenApiToolkit(spec=DOC), "getPet", petId=1)
    assert message.status == CapabilityStatus.ERROR and "no response" in message.content


async def test_the_alias_is_the_prefix():
    toolkit = skye.toolkit("openapi", spec=DOC, alias="pets")
    assert await names(toolkit) == ["pets.getPet"]


def test_importing_skye_tools_does_not_import_the_openapi_module():
    code = (
        "import sys, skye, skye.tools; assert 'skye.tools.plugins.openapi.toolkit' not in "
        "sys.modules"
    )
    done = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-500:]
