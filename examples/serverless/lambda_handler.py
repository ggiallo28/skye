"""A serverless handler: create the client once, outside the handler, so a warm invocation pays nothing.

Skye is built for serverless architectures, where the size of the library and its cold start make a difference. The core imports only
the standard library; a provider is called over REST with the standard library, so nothing else is shipped. This file shows the shape
of a handler (written for AWS Lambda, but any serverless runtime works the same way). Without AWS credentials a scripted client
answers and the example says so.
"""

import os
import sys
from pathlib import Path

from skye import UserMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the shared offline helper lives in examples/
from _offline import provider_or_scripted  # noqa: E402

READY = bool(os.getenv("AWS_ACCESS_KEY_ID") or os.getenv("AWS_PROFILE"))
# Created at cold start, reused by every warm invocation. Credentials come from the provider's standard variables.
CLIENT = provider_or_scripted("bedrock", READY, "configure AWS credentials", region=os.getenv("AWS_REGION", "us-east-1"))
MODEL = os.getenv("MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")


def handler(event: dict, context: object = None) -> dict:
    response = CLIENT.complete(messages=[UserMessage(content=event["prompt"])], model=MODEL)
    return {"response": response.content}


if __name__ == "__main__":
    print(handler({"prompt": "Say hello in one word"}))
