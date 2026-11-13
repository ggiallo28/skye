# D110, Requirement 59.9, D104, D109
"""What a provider is written with: the two wire-format providers and the plain modules a provider builds on.

``plugins/`` holds the providers Skye offers, one folder each; this package holds the parts that more than one of them uses and that a third-party
plugin uses too. Files, not groups:

* ``openai_compatible/`` and ``anthropic_compatible/``: a complete provider for an endpoint that speaks the OpenAI chat-completions format or the
  Anthropic messages format; a plugin registers it with a ``ProviderProfile`` and needs no class of its own;
* the calls over the network: ``rest`` (JSON and server-sent events: ``post_json``, ``stream_sse_json``), ``streaming``, ``eventstream`` (the Bedrock
  framing), ``retry`` (who retries and how long it waits) and ``error_mapping`` (a failed response to the ``ProviderError`` it calls for: the mapping every provider shares; a provider's own handler is its ``errors.py``);
* the shaping of a request: ``structured`` and ``schema_check`` (structured output and the check of a reply), ``capability_choice`` (a forced choice emulated for the models that refuse one), ``prompt_parts`` and ``multimodal`` (images, audio and video);
* ``credentials``: the API key and the AWS region of a client.

The base classes are ``models/base.py``, and ``CostCalculator`` and ``TokenCounter`` are ``models/cost.py`` and ``models/token_counter.py``: they are the
component's own, not tools. The public names stay where users import them (``skye.models.BaseModelProvider``, ``OpenAICompatibleProvider``,
``post_json``). Importing this package imports nothing: import the module you use.

Raises: nothing at import; each module documents its own errors.
Missing: not applicable.
Concurrency: stateless; each module documents its own.
"""
