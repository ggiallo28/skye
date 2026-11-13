---
title: "Deploy on AWS Lambda"
status: current
---

# Deploy on AWS Lambda

This page shows you how to run Skye in an AWS Lambda function: what to package, where the credentials come from, how to keep the
cold start short, and how to keep the state of a router between invocations in DynamoDB.

## What you need

- An AWS account with access to the Bedrock models you call (or a key of another provider).
- A Lambda function on a Python runtime (3.11 or later), with an execution role.
- For a router with shared state: a DynamoDB table with a string partition key named `pk`.

## What to package

The base install is enough for every provider. Skye has no third-party dependency: the package is one pure-Python wheel, and
each provider is called over HTTPS with the standard library. Bedrock requests are signed with SigV4 by Skye itself, so neither
`boto3` nor a vendor SDK is needed for a model call.

A complete function is in [`examples/serverless/lambda_zip`](https://github.com/ggiallo28/skye/tree/main/examples/serverless/lambda_zip):
`handler.py` and `build.sh`, which writes `function.zip` with Skye and the handler, nothing else. The zip is **0.61 MB** (1.87 MB
unzipped; AWS allows 50 MB and 250 MB), and the CI fails above `[lambda] max_zip_mb` of `budgets.toml` (1 MB).

```bash
sh examples/serverless/lambda_zip/build.sh   # pip install --target build skyeai, add handler.py, zip -r9
```

The wheel has no compiled file, so you build the package on any machine, for `x86_64` or `arm64`, without a container.

Only the DynamoDB backend of the store uses `boto3`, and the Lambda Python runtime already contains it. Outside Lambda, install it
with `pip install skyeai[aws]`.

## Credentials

Inside Lambda you write no key. The execution role gives the function temporary credentials in `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY` and `AWS_SESSION_TOKEN`, and Skye reads them from the environment. Give the role the permissions it uses:

| Use | IAM actions |
|---|---|
| Bedrock `complete` | `bedrock:InvokeModel` |
| Bedrock `stream` | `bedrock:InvokeModelWithResponseStream` |
| Router state in DynamoDB | `dynamodb:GetItem`, `PutItem`, `UpdateItem`, `DeleteItem`, `BatchGetItem`, `BatchWriteItem`, `Scan` on the table |

The Bedrock client calls the region of the function: Lambda sets `AWS_REGION`, and a client created without `region` reads it
(then `AWS_DEFAULT_REGION`). For OpenAI or Anthropic, keep the key in AWS Secrets Manager and pass it as `api_key`, or in an
encrypted environment variable with its standard name (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`), which the client reads when
`api_key` is left out. [Credentials and secrets](../guides/security/credentials.md) covers the other
sources.

## A handler

Create the client once, outside the handler. Lambda runs that code at the cold start, and every warm invocation reuses the client:

```python
--8<-- "examples/serverless/lambda_handler.py"
```

Without AWS credentials the example uses a scripted client and runs on your machine. In Lambda the handler signature
`handler(event, context)` is the one the runtime calls; set the function handler to `handler.handler`.

## Cold start

The library keeps its part of the cold start small: `import skye`, importing the router and building a router with one target take
about 56 ms on a laptop, and the project's budget fails a pull request above 200 ms on a CI runner. For comparison, `import boto3`
alone costs 150 to 250 ms. `import skye` loads only the names you use: a provider, the router or a store backend is imported on first
use.

What you can do:

- create clients and routers at module level, not inside the handler;
- import only what the handler uses;
- avoid extras you do not need: each one adds a library to the package.

[Size and load budgets](../project/budgets.md) lists every number the project measures.

## Router state in DynamoDB

A router tracks the health, the cooldown and the rate-limit usage of each model. By default that state is in memory, so each
Lambda instance has its own, and a new instance starts with none. Pass a store to share it between invocations and instances:

```python
import os

from skye import UserMessage
from skye.router import FallbackConfig, ModelRouter, ModelTarget, RouteConfig
from skye.store import backend

REGION = os.environ["AWS_REGION"]
STATE = backend("dynamodb", table_name=os.environ["STATE_TABLE"])

ROUTER = ModelRouter(
    routes=[
        RouteConfig(alias="chat", targets=[
            ModelTarget(model="anthropic.claude-3-5-sonnet-20240620-v1:0", provider="bedrock", region=REGION),
        ]),
        RouteConfig(alias="chat-small", targets=[
            ModelTarget(model="anthropic.claude-3-haiku-20240307-v1:0", provider="bedrock", region=REGION),
        ]),
    ],
    fallbacks=[FallbackConfig(primary="chat", fallbacks=["chat-small"])],
    storage=STATE,
)


def handler(event, context):
    response = ROUTER.complete(messages=[UserMessage(content=event["prompt"])], model="chat")
    return {"response": response.content, "model": ROUTER.last_serving["model"]}
```

The backend creates its `boto3` client at the first call, not at import. The table needs a string partition key `pk`; enable `ttl`
as its time-to-live attribute so DynamoDB deletes expired items. The region of the table comes from the AWS configuration, which in
Lambda is `AWS_REGION`.

!!! warning
    `ModelRouter.from_file` does not take a store today: a `storage=` argument passed to it is ignored, and the router keeps its
    state in memory. Build the router in Python, as above, when its state must live in DynamoDB.

The runnable example
[`serverless/serverless_router_example.py`](https://github.com/ggiallo28/skye/blob/main/examples/serverless/serverless_router_example.py)
shows two routers that share their state through the file backend, which works the same way. [Choose a store backend](../guides/state/choose-a-backend.md)
compares DynamoDB with Valkey, Redis, PostgreSQL and the durable function backend.

## See also

- [Router state in a store](../guides/routing/router-state.md) and [Serverless first](../concepts/serverless-first.md).
- [`skye.store` API reference](../reference/api/store.md) and [`skye.router` API reference](../reference/api/router.md).
- [Extras](../reference/extras.md): what each extra installs.
- Examples: [`serverless/`](https://github.com/ggiallo28/skye/blob/main/examples/serverless/README.md).
