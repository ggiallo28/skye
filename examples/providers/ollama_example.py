"""Ollama through ``skye.provider("openai", api_base=...)``: completion and streaming.

Ollama serves the OpenAI wire format at ``/v1``, so the OpenAI client works with ``api_base`` pointed at it. Ollama ignores the API
key; any placeholder will do. With an Ollama server answering at ``OLLAMA_HOST`` (default ``http://localhost:11434``) the example calls
it with ``OLLAMA_MODEL`` (default ``llama3.2``, pull it first with ``ollama pull llama3.2``); without one a scripted client answers and
the example says so.
"""

import os
import sys
import urllib.request
from pathlib import Path

from skye import SystemMessage, UserMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the shared offline helper lives in examples/
from _offline import provider_or_scripted  # noqa: E402

HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")


def ollama_running() -> bool:
    """True when an Ollama server answers at HOST (``/api/version`` is Ollama's own health route)."""
    try:
        with urllib.request.urlopen(f"{HOST}/api/version", timeout=1) as response:
            return response.status == 200
    except OSError:
        return False


def main() -> None:
    client = provider_or_scripted("openai", ollama_running(), "start Ollama", api_key="ollama", api_base=f"{HOST}/v1")

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
