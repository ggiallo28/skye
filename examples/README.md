# Skye examples

Every example is small, runs with no key and no network, and prints its result. Install with `pip install skyeai` (every provider is built in; extras such as `skyeai[tokens]` or `skyeai[memory]` add a library).

## Reading order

Read the folders in this order; each folder has a README with its own order.

1. `examples/basic/`: the first calls: client, completion, async and streaming, configuration
2. `examples/providers/`: one client call for every provider
3. `examples/routing/`: several models, fallbacks, health, `.skye` configuration
4. `examples/advanced/`: function calling, structured output, streaming, multimodal, prompts
5. `examples/capabilities/`: capabilities the model can call, local, remote and MCP
6. `examples/tools/`: the capability registry and MCP clients
7. `examples/models/`: tokens, cost, retry and errors
8. `examples/base/`: content chunks and the error hierarchy
9. `examples/auth/`: credential sources
10. `examples/store/`: storage backends
11. `examples/memory/`: conversation memory
12. `examples/agents/`: agents and hooks
13. `examples/teams/`: teams of runnables
14. `examples/flows/`: sequential flows
15. `examples/guard/`: safety filters
16. `examples/policy/`: authorization
17. `examples/observe/`: telemetry and exporters
18. `examples/gateway/`: a gateway over MCP
19. `examples/serverless/`: handlers and routers for AWS Lambda and similar
20. `examples/prompts/`: `.skye` prompts: roles and history, control flow, few-shot turns, output formats, the bundled prompts and a gallery of 26 prompts to copy, validation, shared parts, rendered offline
21. `examples/plugins/`: add an integration with `skye.Plugins()` and a decorator, or by an installed package with an entry point

## Running without a key

An example that calls a model uses the real provider when its key is in the environment and a scripted client otherwise, and prints which mode ran. The scripted client lives in `examples/_offline.py`; it is not part of the package.

## Create a client

One call, the same line for every provider:

```python
import skye

client = skye.provider("openai", api_key="sk-...")
response = client.complete(messages=[...], model="gpt-4")
```

## Keys

Set the variable of the provider you call (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `AZURE_OPENAI_API_KEY` with `AZURE_OPENAI_ENDPOINT`, AWS credentials for Bedrock). With no key an example prints how to set one.

## Check the examples

`tests/examples` runs every example against a fake network, and again in a subprocess with no key and no network.
