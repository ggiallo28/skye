---
title: "Credentials and secrets"
status: current
---

# Credentials and secrets

This guide shows you how Skye finds the credentials of a provider, how to sign AWS requests, read a secret manager, and plug in your own
credential source.

Every outbound request is authenticated through one Port, `AuthenticationInterface`: its method
`apply(method, url, headers, body=b"")` returns a new dictionary of headers with the authentication added, and never changes the input.
The [`skye.auth`](../../reference/api/auth.md) package implements it for the documented, non-interactive modes of each provider.

## What you need

- `pip install skyeai`. Every mode is standard library, except RS256 signing (Google service accounts, Azure certificates), which
  needs the extra `auth`:

=== "pip"

    ```bash
    pip install skyeai[auth]
    ```

=== "uv"

    ```bash
    uv add "skyeai[auth]"
    ```

## The rules

- **Provider-standard variables only.** Credentials come from the variables each provider documents (`OPENAI_API_KEY`, `AWS_*`,
  `GOOGLE_*`, `AZURE_*`, ...). A client created without `api_key` reads its provider's variable: `OPENAI_API_KEY`,
  `ANTHROPIC_API_KEY`, `COHERE_API_KEY`, `AZURE_OPENAI_API_KEY`; when it is not set, `ConfigurationError` names it. Skye reads two
  prefixed variables of its own, none of them a credential: `SKYE_LOG_LEVEL` and `SKYE_CONFIG` (see
  [Configuration](../configuration.md)).
- **No interactive login.** Where a mode needs an earlier `aws sso login`, `az login` or `gcloud auth application-default login`, Skye
  reads the cache that tool left. When it is missing or expired, it raises `LoginRequiredError` naming the command to run again.
- **No secret leaves the component.** None in a log, a `repr` or an error: errors name the variable or the file, never its value.
- **No background work.** Tokens are cached and refreshed on the calling thread a little before they expire: no timer, no thread.

## Modes per provider

| Provider | Modes |
|---|---|
| AWS | explicit keys, environment, web identity, profile (keys, assume-role, IAM Identity Center cache), container credentials, IMDSv2, Bedrock API key |
| Google | access token, API key, service account (RS256), authorized user, impersonation, Workload Identity Federation, metadata server, gcloud login cache |
| Microsoft Entra ID | API key, client secret, certificate (RS256), federated token file, managed identity, `az login` cache |
| OpenAI and compatible, Anthropic, Cohere | API key or bearer token |
| Any OAuth2 server | client credentials, token exchange |

## Give a provider its credentials

=== "OpenAI"

    ```python
    import skye

    client = skye.provider("openai")  # OPENAI_API_KEY; or api_key="..." from your secret store
    ```

    Anthropic (`ANTHROPIC_API_KEY`) and Cohere (`COHERE_API_KEY`) work the same way.

=== "Bedrock"

    ```python
    import skye

    # An API key (api_key= or AWS_BEARER_TOKEN_BEDROCK), else SigV4 with the AWS credential chain
    client = skye.provider("bedrock", region_name="eu-west-1", profile_name="prod")
    ```

    Without `region_name` (or `region`), the client uses `AWS_REGION`, then `AWS_DEFAULT_REGION`; there is no default region. An
    authenticator built with `bedrock_authenticator(region, ...)` can be passed as `authenticator=`, and its region is used.

=== "Google"

    ```python
    import skye

    # credentials= may be an authenticator or an access token; omitted, it is resolved from the environment
    client = skye.provider("google", project_id="my-project", location="europe-west1")
    ```

=== "Azure OpenAI"

    ```python
    import skye
    from skye.auth import AzureClientSecretAuth

    # Entra ID with a client secret; omit credentials= to resolve it from the Azure variables (below)
    client = skye.provider(
        "azure",
        azure_endpoint="https://my-resource.openai.azure.com",
        api_version="2024-10-21",
        deployment_name="gpt-4o-mini",
        credentials=AzureClientSecretAuth(tenant_id="...", client_id="...", client_secret="..."),
    )
    ```

    `credentials=` takes any authenticator of `skye.auth.plugins.azure` (client secret, certificate, federated token, managed identity, the
    `az login` cache) or an API key; `api_key=` is a key. With neither, the client tries `AZURE_OPENAI_API_KEY`, then
    `AZURE_TENANT_ID` and `AZURE_CLIENT_ID` with `AZURE_FEDERATED_TOKEN_FILE`, `AZURE_CLIENT_SECRET` or
    `AZURE_CLIENT_CERTIFICATE_PATH`, then a managed identity (`IDENTITY_ENDPOINT`), then the `az login` cache.

The AWS credential chain, in order: explicit keys, `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`, web identity
(`AWS_ROLE_ARN` with `AWS_WEB_IDENTITY_TOKEN_FILE`), the named profile, the ECS container endpoint, then the EC2 instance metadata
(IMDSv2). Google tries an access token in the environment, `GOOGLE_API_KEY`, the file named by `GOOGLE_APPLICATION_CREDENTIALS`, the
gcloud application-default file, then the metadata server.

## Sign AWS requests with SigV4

`SigV4Authenticator` signs any AWS request; `BedrockApiKeyAuthenticator` adds a Bedrock API key as a bearer token. Both only compute
headers: no network call.

```python
--8<-- "examples/auth/credential_sources.py:20:31"
```

In production, pass a `CredentialProvider` (or nothing: the chain above is the default) instead of static keys:

```python
from skye.auth import CredentialProvider, SigV4Authenticator

provider = CredentialProvider(profile_name="prod", region="eu-west-1")
auth = SigV4Authenticator(region="eu-west-1", service="bedrock", credentials=provider)
```

`aws_authenticator(region, service, **credentials)` is a shortcut: it builds a `CredentialProvider` from the keyword arguments
(`profile_name`, `role_arn`, `access_key`, ...) and returns a `SigV4Authenticator`. With `role_arn`, the provider assumes the role
(also across accounts, with `external_id`) and refreshes the temporary credentials shortly before they expire.

## Resolve a source by name

`resolve_credential_source(name, **config)` builds any registered source. The built-in names:

| Name | Returns |
|---|---|
| `openai`, `anthropic`, `cohere` | an authenticator from the key or the standard variable |
| `aws`, `bedrock` | a SigV4 (or Bedrock API key) authenticator |
| `google`, `azure` | the first usable mode, in the order above |
| `client-credentials`, `token-exchange` | an OAuth2 authenticator |
| `aws-secrets-manager`, `aws-ssm`, `azure-key-vault`, `google-secret-manager` | a secret source with `get(name)` |

```python
from skye.auth import resolve_credential_source

auth = resolve_credential_source("openai")  # reads OPENAI_API_KEY
headers = auth.apply("POST", "https://api.openai.com/v1/chat/completions", {})

vault = resolve_credential_source("aws-secrets-manager", region="eu-west-1")
password = vault.get("prod/db/password")
```

The secret managers are called over HTTP with the right authentication (SigV4 for AWS, Entra ID for Azure, Google for Google). Use them
to read a key at start-up instead of storing it in the code or the configuration file.

## Your own source

An authenticator is any object with the `apply` method: the Port is a runtime-checkable Protocol, so nothing needs to be inherited.

```python
--8<-- "examples/auth/custom_credential_source.py:14:32"
```

Register a factory under a name to resolve it like the built-in ones. A factory may also return a secret source with `get(name)`.

```python
from skye.auth import register_credential_source, resolve_credential_source

register_credential_source("static", lambda **config: StaticTokenAuthenticator(**config))
auth = resolve_credential_source("static", token="...")
```

A built-in name can only be replaced with `replace=True`.

## See also

- [Configuration](../configuration.md): `${VAR}` substitution keeps secrets out of the configuration file.
- [Remote APIs](../tools/remote-apis.md): headers and basic authentication for a capability.
- Reference: [`skye.auth`](../../reference/api/auth.md), [`skye.interfaces`](../../reference/api/interfaces.md).
- Examples: [`credential_sources.py`](https://github.com/ggiallo28/skye/blob/main/examples/auth/credential_sources.py),
  [`custom_credential_source.py`](https://github.com/ggiallo28/skye/blob/main/examples/auth/custom_credential_source.py).
