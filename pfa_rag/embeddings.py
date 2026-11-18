"""Validated batch embeddings from local Ollama."""

from math import isfinite

from .ollama import OllamaModel


class OllamaEmbeddings(OllamaModel):
    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        dimensions = None
        for offset in range(0, len(texts), 32):
            batch = texts[offset:offset + 32]
            response = self._request(
                "/api/embed", {"model": self.model, "input": batch, "truncate": False},
            )
            values = response.get("embeddings")
            if not isinstance(values, list) or len(values) != len(batch):
                raise ValueError("Ollama must return exactly one embedding per input")
            for vector in values:
                if not isinstance(vector, list) or not vector or not all(
                    type(value) in (int, float) and isfinite(value) for value in vector
                ) or not any(vector):
                    raise ValueError("Ollama embeddings must be finite and nonzero")
                if dimensions is None:
                    dimensions = len(vector)
                if len(vector) != dimensions:
                    raise ValueError("Ollama returned inconsistent embedding dimensions")
            vectors.extend(values)
        return vectors
