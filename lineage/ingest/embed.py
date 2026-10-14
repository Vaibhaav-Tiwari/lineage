"""Local sentence embeddings (no API key): BAAI/bge-small-en-v1.5, 384 dims."""

from lineage.config import settings


class Embedder:
    def __init__(self, model: str | None = None):
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model or settings().embed_model)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.embed(texts, batch_size=64)]
