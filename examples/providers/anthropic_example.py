"""Anthropic through ``skye.provider("anthropic")``: completion and streaming.

A ``SystemMessage`` becomes the Anthropic ``system`` field; the rest of the call is the same as for every provider. With ANTHROPIC_API_KEY
set the example calls Claude; without a key a scripted client answers and the example says so.
"""

import os
import sys
from pathlib import Path

from skye import SystemMessage, UserMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the shared offline helper lives in examples/
from _offline import provider_or_scripted  # noqa: E402

MODEL = "claude-sonnet-4-5-20250929"


def main() -> None:
    key = os.getenv("ANTHROPIC_API_KEY")
    client = provider_or_scripted("anthropic", bool(key), "set ANTHROPIC_API_KEY", api_key=key)

    messages = [SystemMessage(content="You are a helpful assistant."), UserMessage(content="What is the capital of France?")]
    response = client.complete(messages=messages, model=MODEL, temperature=0.7, max_tokens=100)
    print("answer:", response.content)
    print(f"model={response.model} tokens={response.usage.total_tokens} finish={response.finish_reason}")

    print("stream: ", end="")
    for chunk in client.stream(messages=[UserMessage(content="Write a two-line poem about Python")], model=MODEL):
        print(chunk.delta, end="", flush=True)
    print()


if __name__ == "__main__":
    main()
