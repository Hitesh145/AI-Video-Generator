"""Gemini Embedding 2 adapter for consistent document and query vectors."""

from __future__ import annotations

import math
import os
from collections.abc import Sequence
from typing import Any

from rag.storage_config import EMBEDDING_DIMENSIONS, embedding_model_from_env


class EmbeddingError(RuntimeError):
    """Raised when the embedding provider fails or returns an invalid vector."""


def prepare_document_embedding_text(title: str | None, content: str) -> str:
    """Format a document for Gemini Embedding 2 asymmetric retrieval."""
    clean_title = (title or "none").strip() or "none"
    return f"title: {clean_title} | text: {content.strip()}"


def prepare_query_embedding_text(query: str) -> str:
    """Format a natural-language question for Gemini Embedding 2 retrieval."""
    clean_query = query.strip()
    if not clean_query:
        raise ValueError("Query must not be empty.")
    return f"task: question answering | query: {clean_query}"


class GeminiEmbeddingService:
    """Generate fixed-width vectors with lazy SDK loading and injectable client.

    The initial PostgreSQL migration uses VECTOR(1536). To change dimensions,
    create a migration and rebuild all embeddings; changing only the environment
    or model name is not enough.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str | None = None,
        dimensions: int = EMBEDDING_DIMENSIONS,
        client: Any | None = None,
        config_factory: Any | None = None,
    ) -> None:
        if dimensions != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"This schema expects {EMBEDDING_DIMENSIONS}-dimension vectors; "
                "change the migration before changing dimensions."
            )
        self.dimensions = dimensions
        self._client = client
        self._config_factory = config_factory

        if self._client is None:
            try:
                from dotenv import load_dotenv

                load_dotenv()
            except ImportError:
                pass
        self.model_name = model_name or embedding_model_from_env()

        if self._client is None:
            resolved_key = api_key or os.getenv("GEMINI_API_KEY")
            if not resolved_key:
                raise EmbeddingError(
                    "GEMINI_API_KEY is missing. Configure it in your environment/.env "
                    "before generating embeddings."
                )
            try:
                from google import genai
                from google.genai import types
            except ImportError as exc:
                raise EmbeddingError(
                    "Embedding generation requires google-genai. Install the backend dependencies."
                ) from exc
            self._client = genai.Client(api_key=resolved_key)
            self._config_factory = types.EmbedContentConfig

    def embed_document(self, content: str, title: str | None = None) -> list[float]:
        if not content.strip():
            raise ValueError("Cannot embed an empty document chunk.")
        return self.embed_prepared_text(prepare_document_embedding_text(title, content))

    def embed_query(self, query: str) -> list[float]:
        return self.embed_prepared_text(prepare_query_embedding_text(query))

    def embed_prepared_text(self, formatted_text: str) -> list[float]:
        """Embed one already-formatted text input (Gemini Embedding 2 aggregates lists)."""
        if not formatted_text.strip():
            raise ValueError("Embedding input must not be empty.")
        try:
            config = (
                self._config_factory(output_dimensionality=self.dimensions)
                if self._config_factory is not None
                else self._default_config()
            )
            response = self._client.models.embed_content(
                model=self.model_name,
                contents=formatted_text,
                config=config,
            )
            embeddings = getattr(response, "embeddings", None) or []
            if len(embeddings) != 1:
                raise EmbeddingError(
                    f"Expected exactly one embedding from {self.model_name}, got {len(embeddings)}."
                )
            values = getattr(embeddings[0], "values", None)
            return self._validate_vector(values)
        except EmbeddingError:
            raise
        except Exception as exc:
            raise EmbeddingError(f"Embedding request failed: {exc}") from exc

    def _default_config(self) -> Any:
        try:
            from google.genai import types
        except ImportError as exc:
            raise EmbeddingError("google-genai is not installed.") from exc
        return types.EmbedContentConfig(output_dimensionality=self.dimensions)

    def _validate_vector(self, values: Sequence[float] | None) -> list[float]:
        if values is None:
            raise EmbeddingError("The embedding provider returned no vector values.")
        try:
            vector = [float(value) for value in values]
        except (TypeError, ValueError) as exc:
            raise EmbeddingError("The embedding provider returned non-numeric vector data.") from exc
        if len(vector) != self.dimensions:
            raise EmbeddingError(
                f"Expected {self.dimensions} dimensions, received {len(vector)}."
            )
        if not all(math.isfinite(value) for value in vector):
            raise EmbeddingError("Embedding contains NaN or infinite values.")
        return vector
