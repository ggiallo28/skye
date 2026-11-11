"""Ollama through ``skye.provider("openai", api_base=...)``: completion and streaming.

Ollama speaks the OpenAI wire format, so the OpenAI client works with its ``/v1`` endpoint. Ollama ignores the API key, so any placeholder does.
With an Ollama server running on localhost the example calls it (set OLLAMA_MODEL to pick a model, otherwise the first one it lists); without
one a scripted client answers and the example says so.
"""

import json
import os
import sys
from pathlib import Path
from urllib.request import urlopen

from skye import SystemMessage, UserMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the shared offline helper lives in examples/
from _offline import provider_or_scripted  # noqa: E402

HOST = os.getenv("OLLAMA_HOST_URL", "http://localhost:11434")


def first_model() -> str | None:
    """The model to use: OLLAMA_MODEL, else the first model the local server lists, else None when no server answers."""
    try:
        with urlopen(f"{HOST}/api/tags", timeout=1) as reply:
            models = json.load(reply).get("models", [])
    except (OSError, ValueError):
        return None
    return os.getenv("OLLAMA_MODEL") or (models[0]["name"] if models else None)


def main() -> None:
    model = first_model()
    client = provider_or_scripted("openai", model is not None, "start Ollama and pull a model", api_key="ollama", api_base=f"{HOST}/v1")

    messages = [SystemMessage(content="You are a helpful assistant."), UserMessage(content="What is the capital of France?")]
    response = client.complete(messages=messages, model=model or "scripted", temperature=0.7, max_tokens=100)
    print("answer:", response.content)
    print(f"model={response.model} tokens={response.usage.total_tokens} finish={response.finish_reason}")

    print("stream: ", end="")
    for chunk in client.stream(messages=[UserMessage(content="Write a two-line poem about Python")], model=model or "scripted"):
        print(chunk.delta, end="", flush=True)
    print()


if __name__ == "__main__":
    main()
