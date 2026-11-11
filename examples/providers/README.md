# providers

What you learn: providers. Read in this order:

1. `anthropic_example.py`: Anthropic through ``skye.provider("anthropic")``: completion and streaming
2. `azure_example.py`: Azure OpenAI through ``skye.provider("azure")``: completion and streaming
3. `bedrock_example.py`: AWS Bedrock through ``skye.provider("bedrock")``: completion and streaming
4. `bring_your_own_adapter.py`: Bring your own adapter: any object with ``async def invoke(self, input)`` is a ``Runnable``
5. `embeddings_example.py`: Embeddings through ``skye.provider(..., provider_type="embedding")``
6. `google_example.py`: Google (Gemini on Vertex AI) through ``skye.provider("google")``: completion and streaming
7. `multimodal_example.py`: Images in a message: from a URL, from a data URL and from a file
8. `ollama_example.py`: Ollama through ``skye.provider("openai", api_base=...)``: completion and streaming against a local model
9. `openai_example.py`: OpenAI through ``skye.provider("openai")``: completion and streaming
10. `structured_output_example.py`: Structured output with a dataclass: field constraints, lists and the request-object form

Run: `python examples/providers/anthropic_example.py`

What you see: printed results; with no key a scripted client answers and the example prints which mode ran.

What you need: `pip install skyeai`; a provider key only to call a real service.
