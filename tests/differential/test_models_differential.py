"""Model adapters: built-in REST vs the official SDK, against a local fake server (Requirement 9.4, D14).

The vendor SDKs (dev group) are the oracle. Both sides talk to one fake server that speaks the provider's wire format, so the
comparison needs no credentials and no network. Only the subset Skye consumes is compared: text, finish reason and token usage
by equality (token counts with an epsilon of 0), and the category of an error (authentication, rate limit) by its HTTP status.

Google is not covered: the Vertex SDK authenticates with Application Default Credentials and talks to ``googleapis.com`` over
its own transport, so it cannot be pointed at a local server. Its adapter is covered by `tests/unit/models/test_google_provider.py`.
"""

from __future__ import annotations

import pytest

import skye
from skye.base.exceptions import ProviderError
from skye.base.messages import UserMessage
from tests.differential.fake_model_server import COMPLETION_TOKENS, PROMPT_TOKENS, TEXT, FakeModelServer

EPS = 0
SDK_MODULES = {"openai", "anthropic", "boto3", "botocore", "s3transfer", "jmespath", "distro", "jiter", "docstring_parser"}


@pytest.fixture(scope="module", autouse=True)
def _leave_no_sdk_imported():
    """Other tests assert that no vendor SDK is imported; drop what these tests loaded once they are done."""
    import sys

    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        if name.split(".")[0] in SDK_MODULES:
            del sys.modules[name]


@pytest.fixture(scope="module")
def server():
    with FakeModelServer() as s:
        yield s


@pytest.fixture(autouse=True)
def _no_retry_wait(monkeypatch):
    """The adapters retry a failure with a wait of seconds; the comparison does not need to wait."""
    monkeypatch.setattr("skye.models.utilities.retry.time.sleep", lambda seconds: None)


def _rest(provider: str, server: FakeModelServer):
    if provider == "openai":
        return skye.provider("openai", api_key="k", api_base=f"{server.url}/v1")
    if provider == "anthropic":
        return skye.provider("anthropic", api_key="k", api_base=server.url)
    return skye.provider(
        "bedrock", region_name="us-east-1", aws_access_key_id="a", aws_secret_access_key="b", endpoint_url=server.url
    )


def _sdk(provider: str, model: str, server: FakeModelServer):
    """One completion through the vendor SDK: ``(text, finish_reason, prompt_tokens, completion_tokens)``."""
    if provider == "openai":
        openai = pytest.importorskip("openai")
        r = openai.OpenAI(base_url=f"{server.url}/v1", api_key="k", max_retries=0).chat.completions.create(
            model=model, messages=[{"role": "user", "content": "hi"}]
        )
        return r.choices[0].message.content, r.choices[0].finish_reason, r.usage.prompt_tokens, r.usage.completion_tokens
    if provider == "anthropic":
        anthropic = pytest.importorskip("anthropic")
        r = anthropic.Anthropic(base_url=server.url, api_key="k", max_retries=0).messages.create(
            model=model, max_tokens=16, messages=[{"role": "user", "content": "hi"}]
        )
        return r.content[0].text, r.stop_reason, r.usage.input_tokens, r.usage.output_tokens
    boto3 = pytest.importorskip("boto3")
    client = boto3.client(
        "bedrock-runtime", region_name="us-east-1", endpoint_url=server.url,
        aws_access_key_id="a", aws_secret_access_key="b",
    )
    r = client.converse(modelId=model, messages=[{"role": "user", "content": [{"text": "hi"}]}])
    return (
        r["output"]["message"]["content"][0]["text"], r["stopReason"],
        r["usage"]["inputTokens"], r["usage"]["outputTokens"],
    )


def _sdk_status(provider: str, model: str, server: FakeModelServer) -> int:
    """HTTP status of the error the vendor SDK raises for ``model``."""
    try:
        _sdk(provider, model, server)
    except Exception as e:  # the SDK's own exception class differs per provider
        status = getattr(e, "status_code", None)
        if status is None and hasattr(e, "response"):  # botocore ClientError
            status = e.response["ResponseMetadata"]["HTTPStatusCode"]
        assert status is not None, f"no status on {type(e).__name__}"
        return int(status)
    raise AssertionError("the SDK raised nothing")


PROVIDERS = ["openai", "anthropic", "bedrock"]
# The Bedrock adapter names the normal end of a turn "stop", as OpenAI does; the SDK passes Bedrock's "end_turn" through.
FINISH_REASON = {"bedrock": {"end_turn": "stop"}}


@pytest.mark.parametrize("provider", PROVIDERS)
def test_rest_and_sdk_return_the_same_text_finish_reason_and_usage(provider, server):
    text, finish, prompt, completion = _sdk(provider, "m", server)
    response = _rest(provider, server).complete(messages=[UserMessage(content="hi")], model="m")
    assert response.content == text == TEXT
    assert response.finish_reason == FINISH_REASON.get(provider, {}).get(finish, finish)
    assert response.usage.prompt_tokens == pytest.approx(prompt, abs=EPS) == PROMPT_TOKENS
    assert response.usage.completion_tokens == pytest.approx(completion, abs=EPS) == COMPLETION_TOKENS
    assert response.usage.total_tokens == PROMPT_TOKENS + COMPLETION_TOKENS


@pytest.mark.parametrize("model, status", [("auth-error", 401), ("rate-limited", 429)])
@pytest.mark.parametrize("provider", PROVIDERS)
def test_rest_and_sdk_report_the_same_error_category(provider, model, status, server):
    assert _sdk_status(provider, model, server) == status
    with pytest.raises(ProviderError) as caught:
        _rest(provider, server).complete(messages=[UserMessage(content="hi")], model=model)
    assert caught.value.details["status_code"] == status


@pytest.mark.parametrize("provider", PROVIDERS)
def test_both_send_the_same_user_text(provider, server):
    start = len(server.requests)
    _sdk(provider, "m", server)
    _rest(provider, server).complete(messages=[UserMessage(content="hi")], model="m")
    sdk_body, rest_body = (r["body"] for r in server.requests[start:start + 2])
    assert "hi" in str(sdk_body["messages"]) and "hi" in str(rest_body["messages"])
