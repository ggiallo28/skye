"""AWS Bedrock through ``skye.provider("bedrock")``: completion and streaming.

Requests are signed with SigV4 from the standard AWS credentials (environment variables or a profile); there is no AWS SDK to install. The
model is a Bedrock model id. Several models (Claude, Titan) differ only in that id. Without AWS credentials a scripted client answers and
the example says so.
"""

import os
import sys
from pathlib import Path

from skye import SystemMessage, UserMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the shared offline helper lives in examples/
from _offline import provider_or_scripted  # noqa: E402

MODEL = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"


def main() -> None:
    ready = bool(os.getenv("AWS_ACCESS_KEY_ID") or os.getenv("AWS_PROFILE"))
    client = provider_or_scripted("bedrock", ready, "configure AWS credentials", region=os.getenv("AWS_REGION", "us-east-1"))

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
