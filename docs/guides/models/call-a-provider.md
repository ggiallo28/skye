---
title: "Call a provider"
status: current
---

# Call a provider

This guide shows you how to create the client of each built-in provider, where each one finds its credentials, and which options
it takes.

## What you need

- Skye installed: `pip install skyeai`. Every provider below is a built-in adapter that calls the provider's HTTP API with the Python
  standard library. You install no vendor SDK and no extra for a provider.
- The credentials of the provider you call.

## One function for every provider

`skye.provider(name, **config)` returns a client. The name chooses the provider; the keyword arguments are its configuration. Every
client has the same methods: `complete`, `acomplete`, `stream` and `astream`.

| Name | Provider | Required configuration | Credentials |
|---|---|---|---|
| `openai` | OpenAI and OpenAI-compatible servers | none | `api_key=`, or `OPENAI_API_KEY` |
| `anthropic` | Anthropic | none | `api_key=`, or `ANTHROPIC_API_KEY` |
| `bedrock` | AWS Bedrock | a region: `region=`, or `AWS_REGION` / `AWS_DEFAULT_REGION` | the AWS credential chain |
| `azure` | Azure OpenAI | `azure_endpoint`, `api_version`, `deployment_name` | `api_key=`, `credentials=` (Entra ID), or the Azure variables |
| `google` | Gemini on Google Cloud (Vertex AI) | `project_id` | the Google credential chain |
| `cohere` | Cohere, embeddings only | `model` | `api_key=`, or `COHERE_API_KEY` |

A missing required argument, key or region raises `ConfigurationError` when you create the client, and the message names the
environment variable to set. The call itself is the same for every provider:

```python
response = client.complete(messages=[UserMessage(content="Hello!")], model="...", temperature=0.7, max_tokens=100)
```

## Create the client

=== "OpenAI"

    ```python
    import skye

    client = skye.provider("openai")  # the key from OPENAI_API_KEY; or api_key=os.environ["OPENAI_API_KEY"]
    response = client.complete(messages="What is the capital of France?", model="gpt-4o-mini")
    ```

    Options: `api_base` for any OpenAI-compatible server (vLLM, Ollama, LM Studio, a gateway), and `organization`, sent as the
    `OpenAI-Organization` header.

    ```python
    local = skye.provider("openai", api_key="unused", api_base="http://localhost:11434/v1")
    ```

=== "Anthropic"

    ```python
    import skye

    client = skye.provider("anthropic")  # the key from ANTHROPIC_API_KEY; or api_key="..."
    response = client.complete(messages="What is the capital of France?", model="claude-haiku-5-5", max_tokens=200)
    ```

    Options: `api_base` for an Anthropic-compatible endpoint, `timeout` in seconds (default 60). A `SystemMessage` becomes the
    Anthropic `system` field.

=== "Bedrock"

    ```python
    import skye

    client = skye.provider("bedrock", region="us-east-1")  # or leave region out and set AWS_REGION
    response = client.complete(messages="What is the capital of France?", model="anthropic.claude-3-haiku-20240307-v1:0")
    ```

    Skye signs the requests with SigV4 itself; you install no `boto3`. Credentials come, in order, from explicit arguments
    (`aws_access_key_id`, `aws_secret_access_key`, `aws_session_token`), the environment variables, web identity, a profile
    (`profile_name=` or `AWS_PROFILE`), the container endpoint and the EC2 instance metadata. A Bedrock API key works too:
    `api_key=` or `AWS_BEARER_TOKEN_BEDROCK`.

    Options: `region` (when left out, `AWS_REGION`, then `AWS_DEFAULT_REGION`; there is no default region, and none of them set
    raises `ConfigurationError`), `profile_name`, `authenticator` (one built with `skye.auth.bedrock_authenticator(region, ...)`:
    its region is used when `region` is left out), `endpoint_url` (a VPC endpoint), `timeout` in seconds (default 60). The model is
    a Bedrock model id or an inference profile id.

=== "Azure OpenAI"

    ```python
    import os

    import skye

    client = skye.provider(
        "azure",
        azure_endpoint="https://my-resource.openai.azure.com",
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version="2024-10-21",
        deployment_name="gpt-4o-mini",
    )
    response = client.complete(messages="What is the capital of France?", model="gpt-4o-mini")
    ```

    The request goes to your deployment: `deployment_name` decides the model, whatever you pass as `model`. Pass the deployment
    name as `model` too, so that logs and costs name it. A key is sent in the `api-key` header.

    Microsoft Entra ID works instead of a key: pass `credentials=` an authenticator of `skye.auth` (`AzureClientSecretAuth`,
    `AzureCertificateAuth`, `AzureFederatedTokenAuth`, `AzureManagedIdentityAuth`, `AzureCliCacheAuth`), and the client sends
    its bearer token. With neither `api_key` nor `credentials`, the client takes `AZURE_OPENAI_API_KEY`, then the Entra ID
    variables (`AZURE_TENANT_ID` and `AZURE_CLIENT_ID` with a federated token file, a client secret or a certificate), a managed
    identity, then the cache of `az login`.

    ```python
    from skye.auth import AzureManagedIdentityAuth

    client = skye.provider(
        "azure",
        azure_endpoint="https://my-resource.openai.azure.com",
        api_version="2024-10-21",
        deployment_name="gpt-4o-mini",
        credentials=AzureManagedIdentityAuth(),
    )
    ```

=== "Google"

    ```python
    import skye

    client = skye.provider("google", project_id="my-project", location="europe-west1")
    response = client.complete(messages="What is the capital of France?", model="gemini-2.5-flash")
    ```

    `location` defaults to `us-central1`; `region=` is accepted as another name for it. Use `location="global"` for the global
    endpoint.

    Credentials come, in order, from `credentials=` (an access token or an authenticator from `skye.auth`), an access token in
    `GOOGLE_OAUTH_ACCESS_TOKEN` or `CLOUDSDK_AUTH_ACCESS_TOKEN`, an API key in `GOOGLE_API_KEY`, the file named by
    `GOOGLE_APPLICATION_CREDENTIALS`, the `gcloud auth application-default login` file, and the metadata server on Google Cloud.
    A service-account key file needs the `auth` extra (`pip install skyeai[auth]`) for its RS256 signature.

=== "Cohere"

    ```python
    import skye

    embedder = skye.provider("cohere", model="embed-english-v3.0")  # the key from COHERE_API_KEY
    vectors = embedder.encode_batch(["first text", "second text"])
    ```

    Cohere is an embedding provider only, so `skye.provider("cohere", ...)` gives the embedding client without
    `provider_type="embedding"` (passing it is the same). See [Embeddings](embeddings.md).

## Options of a call

Every client takes the same options in `complete`, `acomplete`, `stream` and `astream`:

| Option | Meaning |
|---|---|
| `messages` | a list of messages, or one string (a `UserMessage`) |
| `model` | the model of the provider; required unless the client has a default model |
| `temperature`, `top_p` | sampling; defaults 0.7 and 1.0 |
| `max_tokens` | the longest answer; left out, the provider decides (Anthropic requires one: Skye sends 4096) |
| `stop` | strings that end the answer |
| `response_schema` | a dataclass or an `OutputSchema`: see [Structured output](structured-output.md) |
| `capabilities` | tools the model may call: a list of capabilities, a `CapabilityRegistry` or any `ToolProvider` (its schemas are offered); see [Local functions](../tools/local-functions.md) |

You can also build one `CompleteRequest` (from `skye`) with the same fields and pass it as the only argument.

## Errors and retries

A failed call raises the `ProviderError` subclass of the response; all of them are in `skye.exceptions` and keep `provider`,
`status_code` and `retry_after`:

| Error | When | Retried by the client |
|---|---|---|
| `RateLimitError` | 429 | yes |
| `ServerError` | 5xx | yes |
| `ProviderTimeoutError` | a timeout or a dropped connection | yes |
| `AuthenticationError` | 401, 403 | no |
| `BadRequestError` | another 4xx | no |
| `ContentPolicyError` | a content-policy refusal (a `BadRequestError`) | no |
| `UnsupportedModalityError` | the adapter does not accept the form of an input (Bedrock and an image URL); raised before anything is sent, so `status_code` is `None`; `.modality` names it | no |

A client retries a transient error up to `max_retries` times (3 by default), waiting 1, 2, 4 ... seconds (at most 20), or the
seconds of the server's `Retry-After` when it sends one (at most 60). A stream is retried only before its first chunk. Set
`max_retries` when you create the client, or on the client later; `0` turns the retries off:

```python
client = skye.provider("openai", max_retries=0)
client.max_retries = 5
```

A router turns off the retries of its targets: its own retry policy and fallbacks decide (see
[Aliases and fallbacks](../routing/aliases-and-fallbacks.md)).

## Tokens and cost

Every response carries `response.usage` and, split in what you sent and what the model wrote, `response.metadata["cost"]`. Give
your own prices with `skye.provider("openai", pricing={"prompt": 2.5, "completion": 10.0})` (USD per million tokens). A stream
carries a running count on every chunk. See [Tokens and cost](tokens-and-cost.md).

## Every example in one table

Each provider has a runnable example that makes a completion and a stream. Without credentials it runs a scripted client and says so.

| Provider | Example | Credentials it reads |
|---|---|---|
| OpenAI | [`providers/openai_example.py`](https://github.com/ggiallo28/skye/blob/main/examples/providers/openai_example.py) | `OPENAI_API_KEY` |
| Anthropic | [`providers/anthropic_example.py`](https://github.com/ggiallo28/skye/blob/main/examples/providers/anthropic_example.py) | `ANTHROPIC_API_KEY` |
| Bedrock | [`providers/bedrock_example.py`](https://github.com/ggiallo28/skye/blob/main/examples/providers/bedrock_example.py) | AWS credentials |
| Azure OpenAI | [`providers/azure_example.py`](https://github.com/ggiallo28/skye/blob/main/examples/providers/azure_example.py) | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT` |
| Google | [`providers/google_example.py`](https://github.com/ggiallo28/skye/blob/main/examples/providers/google_example.py) | `GCP_PROJECT_ID` and Google credentials |
| Ollama (local) | [`providers/ollama_example.py`](https://github.com/ggiallo28/skye/blob/main/examples/providers/ollama_example.py) | none: a local server at `http://localhost:11434` |

## See also

- [Credentials and secrets](../security/credentials.md): every credential source in detail.
- [Streaming and async](streaming.md), [Structured output](structured-output.md), [Images](images.md).
- [Custom provider](../extend/custom-provider.md): add a provider of your own.
- [`skye.models` API reference](../../reference/api/models.md).
