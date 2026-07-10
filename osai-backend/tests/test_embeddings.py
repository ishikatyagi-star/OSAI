import pytest

from memory.embeddings import EmbeddingsUnavailableError, UnavailableEmbeddingProvider


async def test_unavailable_embeddings_fail_explicitly():
    with pytest.raises(EmbeddingsUnavailableError, match="Embeddings are not configured"):
        await UnavailableEmbeddingProvider(768).embed_texts(["query"])
