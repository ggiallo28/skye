<p align="center">
  <img src=".github/assets/banner.png" alt="Skye, intelligence that travels light" width="100%">
</p>

# Skye AI

**I am sick of installing a pile of dependencies I never use every time I need a generative AI framework. So I wrote one with none.**

**A GenAI library for Python with no third-party dependencies.** One client for OpenAI, Anthropic, Bedrock, Azure OpenAI and
Google, with routing, fallbacks, tools and state on top, all written on the standard library alone.

It installs at 1.9 MB and imports in about 60 ms, so it fits wherever size and start-up time matter: serverless functions,
containers, scripts and edge. There is nothing to vendor, no layer and no image to build. AWS Lambda is the tightest case we
measure, and there a complete function deploys as a 0.56 MB zip. The limits are in [`budgets.toml`](https://github.com/ggiallo28/skye/blob/main/budgets.toml) and the CI fails any change that exceeds them.

[![PyPI](https://img.shields.io/pypi/v/skyeai?label=PyPI)](https://pypi.org/project/skyeai/)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow)](https://opensource.org/licenses/MIT)
[![Documentation](https://img.shields.io/readthedocs/skye?label=Docs)](https://skye.readthedocs.io/)
[![Lambda zip: 0.56 MB](https://img.shields.io/badge/Lambda%20zip-0.56%20MB-2EA44F)](https://skye.readthedocs.io/en/latest/project/budgets/)
[![Built with Kiro](https://img.shields.io/badge/Built%20with-Kiro-790ECB)](https://kiro.dev)

| Measured on skyeai 0.1.1 (2026-11-11) | Value | Limit the CI enforces |
|---|---|---|
| Lambda zip, library and handler ([`examples/serverless/lambda_zip`](https://github.com/ggiallo28/skye/tree/main/examples/serverless/lambda_zip)) | 0.56 MB | 1 MB (AWS: 50 MB) |
| Installed size of the core | 1.9 MB | 2 MB |
| Third-party dependencies of the core | 0 | 0 |
| `import skye` in a fresh interpreter | about 60 ms | 100 ms |

Provider calls go over REST with the standard library, and AWS requests are signed with SigV4 in the standard library, so Bedrock
needs nothing beyond the Lambda Python runtime. Every extra is optional and loaded only when used.

## Quick start (60 seconds)

```bash
pip install skyeai
export OPENAI_API_KEY=sk-...
```

```python
import skye
from skye import UserMessage

client = skye.provider("openai")  # the key from OPENAI_API_KEY
response = client.complete(messages=[UserMessage(content="Hello!")], model="gpt-4o-mini")
print(response.content)
```

The same line works for `"anthropic"`, `"bedrock"`, `"azure"` and `"google"`, each with its standard key variable.

## On AWS Lambda

[`examples/serverless/lambda_zip`](https://github.com/ggiallo28/skye/tree/main/examples/serverless/lambda_zip) is a complete function: `handler.py` calls Bedrock with the
function's role, and `build.sh` packs it with Skye into `function.zip`, 0.56 MB. Deploy it with `aws lambda create-function
--runtime python3.12 --handler handler.handler --zip-file fileb://function.zip`; the steps are in its README.

## Works today

| Component | What you can use |
|---|---|
| `models` | OpenAI, Anthropic, Bedrock, Azure OpenAI, Google; streaming and async; structured output into dataclasses; embeddings; images in messages; token count and cost |
| `router` | aliases over several models, routing strategies, fallbacks, retries, cooldown; its state in any store |
| `store` | memory, file, DynamoDB, Valkey/Redis, PostgreSQL, Lambda durable functions; one extra per driver |
| `tools` | function calling with local functions and remote APIs; a built-in MCP client |
| `prompts` | templates and few-shot examples; prompts and routers written in `.skye` files |
| `auth` | API keys, SigV4, credential sources and secret managers |
| CLI | `skye check`, `fmt`, `render`, `new` for `.skye` files |

## Roadmap

Agents, memory, safety filters (`guard`), policies, observability, a tool gateway, teams and flows are specified in
[`.kiro/specs/`](https://github.com/ggiallo28/skye/tree/main/.kiro/specs) and have no released code yet. Their state: [Status and roadmap](https://skye.readthedocs.io/en/latest/project/roadmap/).

## Examples

Runnable examples are in [`examples/`](https://github.com/ggiallo28/skye/blob/main/examples/README.md), one folder per topic:

| Folder | What it shows |
|---|---|
| [`examples/basic`](https://github.com/ggiallo28/skye/tree/main/examples/basic) | quick start, async and streaming, configuration, completion requests |
| [`examples/providers`](https://github.com/ggiallo28/skye/blob/main/examples/providers/README.md) | OpenAI, Anthropic, Azure, Bedrock, Google, embeddings, multimodal, structured output, function calling, your own adapter |
| [`examples/routing`](https://github.com/ggiallo28/skye/blob/main/examples/routing/README.md) | the router: strategies, `.skye` configuration, fallbacks, health and usage |
| [`examples/capabilities`](https://github.com/ggiallo28/skye/blob/main/examples/capabilities/README.md) | local functions, remote APIs, function calling, the MCP client |
| [`examples/advanced`](https://github.com/ggiallo28/skye/blob/main/examples/advanced/README.md) | multimodal, structured output, function calling, streaming, prompt engineering, your own provider |
| [`examples/prompts`](https://github.com/ggiallo28/skye/tree/main/examples/prompts) | templates, few-shot examples, roles, multimodal prompts |
| [`examples/serverless`](https://github.com/ggiallo28/skye/tree/main/examples/serverless) | a handler that creates its client once, and a router with external state |

Every example is run offline against a fake network by `tests/examples`, so it cannot drift from the library.

## Documentation

The documentation is online at **[skye.readthedocs.io](https://skye.readthedocs.io)**; the source of every page is in `docs/`.

| You want to | Page |
|---|---|
| Install and make a first call | [Get started](https://skye.readthedocs.io/en/latest/get-started/) |
| Call a provider, stream, get structured output | [Models guides](https://skye.readthedocs.io/en/latest/guides/models/call-a-provider/) |
| Route across models with fallbacks | [Routing guides](https://skye.readthedocs.io/en/latest/guides/routing/aliases-and-fallbacks/) |
| Write prompts and routers in `.skye` | [The .skye language](https://skye.readthedocs.io/en/latest/concepts/skye-language/), [reference](https://skye.readthedocs.io/en/latest/reference/skye-language/) |
| Keep state across invocations | [Choose a store backend](https://skye.readthedocs.io/en/latest/guides/state/choose-a-backend/) |
| Deploy on AWS Lambda | [Deploy on AWS Lambda](https://skye.readthedocs.io/en/latest/get-started/lambda/) |
| Look up a class or a function | [Python API](https://skye.readthedocs.io/en/latest/reference/api/skye/), [CLI](https://skye.readthedocs.io/en/latest/reference/cli/) |
| Understand the design | [Architecture](https://skye.readthedocs.io/en/latest/concepts/architecture/), [Serverless first](https://skye.readthedocs.io/en/latest/concepts/serverless-first/) |
| See what is planned | [Status and roadmap](https://skye.readthedocs.io/en/latest/project/roadmap/) |

How the project is specified: the requirements, the design and the decisions are in `.kiro/steering/` (`10-requirements.md`, `11-design.md`, `12-decisions.md`) and the per-component specs in `.kiro/specs/`.

## Contributing

See [CONTRIBUTING.md](https://github.com/ggiallo28/skye/blob/main/CONTRIBUTING.md). Fork, create a branch, make your changes with tests, run the code quality checks, and open a pull request.

Everyone taking part in the project follows the [Code of Conduct](https://github.com/ggiallo28/skye/blob/main/CODE_OF_CONDUCT.md).

## License

MIT License - see [LICENSE](https://github.com/ggiallo28/skye/blob/main/LICENSE) file for details.

## Support

- **Issues**: [GitHub Issues](https://github.com/ggiallo28/skye/issues)
- **Documentation**: [skye.readthedocs.io](https://skye.readthedocs.io)

## Acknowledgments

Skye AI is inspired by:
- **LangChain** - For pioneering LLM application frameworks
- **LiteLLM** - For provider abstraction patterns
- **Clean Architecture** - For architectural principles
- **Cedar** - For the policy model (principal, action, resource, context; default deny; forbid overrides permit)
