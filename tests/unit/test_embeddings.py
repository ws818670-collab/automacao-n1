from embeddings.service import EmbeddingService


def test_embed_returns_zero_vector_for_blank_text(monkeypatch) -> None:
    service = EmbeddingService.__new__(EmbeddingService)
    service._use_local = True
    service._local_model = None
    vector = EmbeddingService.embed(service, "   ")
    assert len(vector) > 0
    assert all(value == 0.0 for value in vector)