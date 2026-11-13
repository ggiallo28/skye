"""Task 20.3: an embedding provider writes only async methods; ``encode`` and ``encode_batch`` are
derived from them (Requirement 56.13)."""

import asyncio
import inspect

import pytest

from skye.base.interfaces.vector_encoder import VectorEncoderInterface
from skye.models.base import BaseEmbeddingProvider


class AsyncOnlyPort(VectorEncoderInterface):
    async def aencode(self, text):
        return [float(len(text))]

    async def aencode_batch(self, texts):
        return [[float(len(t))] for t in texts]

    def get_vector_dimension(self):
        return 1


class AsyncOnlyBase(BaseEmbeddingProvider):
    def _initialize_client(self):
        return None

    async def _aencode_batch_impl(self, texts):
        await asyncio.sleep(0)
        return [[float(len(t))] for t in texts]

    def get_vector_dimension(self):
        return 1


@pytest.mark.parametrize("make", [AsyncOnlyPort, lambda: AsyncOnlyBase("m")])
def test_the_sync_methods_are_derived_from_the_async_ones(make):
    provider = make()
    assert provider.encode("abc") == [3.0]
    assert provider.encode_batch(["a", "bb"]) == [[1.0], [2.0]]


@pytest.mark.parametrize("make", [AsyncOnlyPort, lambda: AsyncOnlyBase("m")])
async def test_the_sync_methods_work_inside_a_running_loop(make):
    assert make().encode_batch(["ab"]) == [[2.0]]


def test_the_health_is_recorded_once_by_the_sync_path():
    provider = AsyncOnlyBase("m")
    provider.encode("a")
    provider.encode_batch(["a", "b"])
    assert provider.health_metrics.success_count == 2


def test_the_base_has_no_sync_implementation_hook():
    assert not hasattr(BaseEmbeddingProvider, "_encode_batch_impl")
    assert inspect.iscoroutinefunction(BaseEmbeddingProvider._aencode_batch_impl)
    assert (
        "encode" not in BaseEmbeddingProvider.__dict__
        and "encode_batch" not in BaseEmbeddingProvider.__dict__
    )


def test_a_sync_only_subclass_no_longer_instantiates():
    class Old(BaseEmbeddingProvider):
        def _initialize_client(self):
            return None

        def _encode_batch_impl(self, texts):
            return [[0.0] for _ in texts]

        def get_vector_dimension(self):
            return 1

    with pytest.raises(TypeError, match="_aencode_batch_impl"):
        Old("m")


@pytest.mark.parametrize(
    "module",
    [
        "openai.embeddings",
        "cohere.embeddings",
        "google.embeddings",
        "bedrock.embeddings",
        "google.multimodal_embeddings",
    ],
)
def test_the_built_in_adapters_keep_only_the_async_hook(module):
    import importlib

    mod = importlib.import_module(f"skye.models.plugins.{module}")
    classes = [
        c
        for c in vars(mod).values()
        if inspect.isclass(c)
        and issubclass(c, BaseEmbeddingProvider)
        and c.__module__ == mod.__name__
    ]
    assert classes
    for cls in classes:
        assert "_encode_batch_impl" not in cls.__dict__
        assert inspect.iscoroutinefunction(cls.__dict__["_aencode_batch_impl"])
