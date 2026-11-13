"""Unit tests for the stdlib pieces of models/utilities (rest, streaming, retry, eventstream) and models/cost (task 4.2)."""

import datetime as dt
import io
import json
from unittest.mock import patch

import pytest

from skye.auth.plugins.aws.sigv4 import sign_request
from skye.base.exceptions import ProviderError, ServerError
from skye.base import http
from skye.models.utilities.retry import with_retry
from skye.models.utilities.streaming import SSEEvent, parse_sse


class TestSSE:
    def test_basic_events_and_multiline_data(self):
        lines = ["event: delta\n", "data: a\n", "data: b\n", "\n", ": comment\n", "data: {\"x\":1}\n", "id: 7\n", "\n"]
        assert list(parse_sse(lines)) == [
            SSEEvent("a\nb", "delta"),
            SSEEvent('{"x":1}', "message", "7"),
        ]

    def test_bytes_crlf_and_no_trailing_blank(self):
        assert list(parse_sse([b"data: hi\r\n", b"\r\n", b"data:x\r\n"])) == [SSEEvent("hi"), SSEEvent("x")]

    def test_retry_and_blank_only(self):
        assert list(parse_sse(["\n", "retry: 500\n", "data: z\n", "\n"])) == [SSEEvent("z", retry=500)]


class TestSigV4:
    def test_aws_get_vanilla_vector(self):
        out = sign_request(
            "GET",
            "https://example.amazonaws.com/",
            region="us-east-1",
            service="service",
            access_key="AKIDEXAMPLE",
            secret_key="wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
            now=dt.datetime(2015, 8, 30, 12, 36, 0, tzinfo=dt.timezone.utc),
        )
        assert out["Authorization"] == (
            "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/service/aws4_request, "
            "SignedHeaders=host;x-amz-date, "
            "Signature=5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31"
        )

    def test_session_token_is_signed(self):
        out = sign_request(
            "POST", "https://h.example.com/p?b=2&a=1", region="r", service="s",
            access_key="A", secret_key="S", session_token="T", payload=b"{}",
            now=dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc),
        )
        assert out["x-amz-security-token"] == "T"
        assert "x-amz-security-token" in out["Authorization"]


class TestRetry:
    def test_max_three_attempts(self):
        calls = []

        @with_retry(max_retries=3, min_wait=0, max_wait=0)
        def f():
            calls.append(1)
            raise ServerError("boom", provider="x", status_code=503)

        with pytest.raises(ServerError):
            f()
        assert len(calls) == 3

    def test_succeeds_after_transient(self):
        calls = []

        @with_retry(max_retries=3, min_wait=0, max_wait=0)
        def f():
            calls.append(1)
            if len(calls) < 2:
                raise ServerError("boom", provider="x", status_code=502)
            return "ok"

        assert f() == "ok" and len(calls) == 2


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class TestHttp:
    def test_request_json(self):
        with patch("urllib.request.urlopen", return_value=_Resp(b'{"a": 1}')) as m:
            assert http.request_json("http://x/y", {"q": 1}) == {"a": 1}
        req = m.call_args[0][0]
        assert json.loads(req.data) == {"q": 1} and req.get_method() == "POST"

    def test_stream_lines_feeds_sse(self):
        with patch("urllib.request.urlopen", return_value=_Resp(b"data: 1\n\ndata: 2\n\n")):
            assert [e.data for e in parse_sse(http.stream_lines("http://x"))] == ["1", "2"]

    def test_transport_error_wrapped(self):
        import urllib.error

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
            with pytest.raises(ProviderError):
                http.request_json("http://x", {})
