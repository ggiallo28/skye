---
title: "Provider profile"
status: current
---

# Provider profile

The profile is where everything specific to one provider is declared, once: how its key is found, where it lives, what each of its models
costs and how to count its tokens. Skye reads it for cost, token counting, the client and the region; no other place names a provider, a
key variable or a price.

A profile is a `ProviderProfile` that holds a `ModelProfile` for each model, and optionally a `RegionRule`. All three are importable from
`skye.plugins`. The built-in providers declare theirs in a `profile.toml` next to the adapter; a plugin passes it with `profile=` when it
registers, or ships a TOML file of the same shape.

## `ProviderProfile`

| Field | Type | Default | Meaning |
|---|---|---|---|
| `name` | string | required | the registered provider name, the one `skye.provider` uses |
| `api_key_variables` | tuple of strings | `()` | the environment variables the key is read from, in order |
| `region` | `RegionRule` or none | none | where the region comes from; none when the provider has no region |
| `default_api_base` | string or none | none | the endpoint used when none is given |
| `client_settings` | mapping | empty | renames a generic setting to the name the provider uses, for example `{"api_base": "azure_endpoint"}` |
| `model_is_deployment` | boolean | `false` | the model name is a deployment name (Azure) |
| `models` | mapping of name to `ModelProfile` | empty | what is known about each model |
| `map_error` | function or `"module:attribute"` text | none | turns a failed response into a `ProviderError` |

## `ModelProfile`

| Field | Type | Default | Meaning |
|---|---|---|---|
| `prompt_price` | number or none | none | USD per million input tokens, 0 or more; none when unknown |
| `completion_price` | number or none | none | USD per million output tokens, 0 or more; none when unknown |
| `tokenizer` | string or none | none | the name of a registered tokenizer; a model that names none gets the estimate |
| `message_overhead` | integer | `0` | tokens added for each message, 0 or more |
| `info` | mapping | empty | merged into what `get_model_info()` returns, for example `{"supports_structured_output": True}` |

A value that is not valid for its field raises `ValidationError` when the profile is built.

## `RegionRule`

| Field | Type | Default | Meaning |
|---|---|---|---|
| `variables` | tuple of strings | required | the environment variables that hold the region, read in order |
| `required` | boolean | `true` | when true and no region is found, resolving it raises `ConfigurationError` naming the variables |

The order is: the region you pass, then the region of the authenticator, then each variable in turn.

## `profile.toml`

The same fields, as a file. The `name` is the provider name; each model is a table named after it, and `info` is a nested table:

```toml
name = "acme"
default_api_base = "https://api.acme.example/v1"
api_key_variables = ["ACME_API_KEY"]

[region]
variables = ["ACME_REGION"]
required = false

[models."acme-small"]
prompt_price = 0.10
completion_price = 0.40

[models."acme-large"]
prompt_price = 2.00
completion_price = 8.00
message_overhead = 3

[models."acme-large".info]
supports_structured_output = true
```

## Change a profile that exists

`plugins.profile(provider, models=..., **fields)` merges a change into the profile of a provider that is already registered and leaves
the rest as it was. The profile is frozen: a new one is built and published as a whole, so a read sees the old profile or the new one and
never half of a change, and a call that raises changes nothing.

```python
--8<-- "examples/plugins/tokenizer.py:34:35"
```

| What you pass | What changes |
|---|---|
| a mapping for a model, `{"tokenizer": "words"}` | only the fields in the mapping |
| a `ModelProfile` for a model | the fields that differ from the defaults of the class; the others stay, so `ModelProfile(tokenizer="words")` does not erase a price |
| `info` in either form | merged key by key into the `info` of the model; a key cannot be removed this way |
| a model the profile does not have | added |
| a field of the provider (`api_key_variables`, `region`, `default_api_base`, `client_settings`, `model_is_deployment`, `map_error`) as a keyword | replaced, checked as the constructor checks it |

A field cannot be set back to its default with a `ModelProfile`, because a default looks like "not given"; the mapping form with the value
does it.

The errors: a provider with no profile raises `ConfigurationError` listing the providers that have one; a name that is not a field raises
`TypeError`; a value that is not valid raises `ValidationError`.

## Where it is read

| Who | Reads |
|---|---|
| `skye.provider(name)` | `api_key_variables`, `default_api_base`, `client_settings`, `model_is_deployment` |
| cost calculation | the prices of the model |
| token counting | `tokenizer` and `message_overhead` of the model, else the estimate |
| the region of a client | `region` |
| `get_model_info()` | `info` of the model |
| errors | `map_error` |

The look-up functions `find_model_profile` and `resolve_region` are in [`skye.plugins`](api/plugins.md).
