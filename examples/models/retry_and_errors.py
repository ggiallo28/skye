"""Provider errors and the client's own retries (Live, no network).

A failed call raises the ``ProviderError`` subclass of the response (D104): ``RateLimitError`` (429),
``ServerError`` (5xx), ``ProviderTimeoutError`` (timeout, dropped connection), ``AuthenticationError``
(401, 403), ``BadRequestError`` (other 4xx). A client retries only the first three, ``max_retries``
times (3 by default, ``0`` = off), with backoff or the server's ``Retry-After``; a stream only before
its first chunk. The "service" is a local function that fails on purpose, and the waits are recorded
(``retry_sleep``) instead of slept. Lines with errors provoked on purpose say ``Expected``.
"""

from typing import Any

from skye import CompleteResponse, StreamChunk, TokenUsage, UserMessage
from skye.exceptions import BadRequestError, ProviderError, RateLimitError, ServerError
from skye.models import BaseModelProvider


class FlakyService(BaseModelProvider):
    """Fails with the errors it is given, one per call, then answers."""

    def __init__(self, failures: list[ProviderError], **config: Any) -> None:
        super().__init__(**config)
        self.failures, self.calls = list(failures), 0

    async def _acall_provider(self, request: dict[str, Any]) -> Any:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return {"text": f"ok after {self.calls} attempts", "model": request["model"]}

    async def _acall_provider_stream(self, request: dict[str, Any]) -> Any:
        yield await self._acall_provider(request)

    def _transform_request(self, request: Any) -> dict[str, Any]:
        return {"model": request.model}

    def _transform_response(self, response: Any) -> CompleteResponse:
        usage = TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2)
        return CompleteResponse(model=response["model"], provider="flaky", content=response["text"], finish_reason="stop", usage=usage)

    def _transform_stream_chunk(self, chunk: Any) -> StreamChunk:
        return StreamChunk(id="s", delta=chunk["text"], finish_reason="stop", index=0)

    _initialize_client = lambda self: None  # noqa: E731
    _transform_messages = _transform_capabilities = format_capability_results = lambda self, items: []  # noqa: E731
    _extract_capability_calls = lambda self, response: None  # noqa: E731

    def get_model_info(self) -> dict[str, Any]:
        return {"provider": "flaky"}


def main() -> None:
    hello, waits = [UserMessage(content="hello")], []

    # 1. A rate limit with Retry-After, then a server error: retried, then answered
    failures = [RateLimitError("slow down", provider="flaky", status_code=429, retry_after=3), ServerError("down", provider="flaky", status_code=503)]
    client = FlakyService(failures, retry_sleep=waits.append)
    print(client.complete(hello, model="m").content, f"(waited {waits} s: Retry-After, then the backoff)")

    # 2. A bad request is raised at once
    client = FlakyService([BadRequestError("bad field", provider="flaky", status_code=400)], retry_sleep=waits.append)
    try:
        client.complete(hello, model="m")
    except BadRequestError as error:
        print(f"Expected {type(error).__name__} after {client.calls} attempt (status {error.status_code})")

    # 3. max_retries=0 turns retries off (what a router does for its targets)
    client = FlakyService([RateLimitError("slow down", provider="flaky", status_code=429)], max_retries=0)
    try:
        client.complete(hello, model="m")
    except ProviderError as error:  # every provider failure is a ProviderError
        print(f"Expected {type(error).__name__} with max_retries=0 after {client.calls} attempt")

    # 4. A stream is retried before its first chunk
    client = FlakyService([ServerError("down", provider="flaky", status_code=502)], retry_sleep=waits.append)
    print("stream:", "".join(chunk.delta for chunk in client.stream(hello, model="m")))


if __name__ == "__main__":
    main()
