---
title: "skye.models"
status: current
---

# `skye.models`

Provider adapters for LLMs and embeddings, the provider registry, token counting and cost. Generated from the docstrings.

::: skye.models
    options:
      show_root_heading: false
      show_submodules: false


## Write the async form only

A provider class writes `_acall_provider` and `_acall_provider_stream` (an async generator), and an embedding provider writes `aencode` and
`aencode_batch`. `complete` and `stream` are derived from `acomplete` and `astream`, and `encode` and `encode_batch` from `aencode` and
`aencode_batch`, so there is one code path. A subclass that still defines `_call_provider`, `_call_provider_stream` or `_encode_batch_impl`
does not instantiate. [Write a provider](../../guides/extend/custom-provider.md) has the steps.
