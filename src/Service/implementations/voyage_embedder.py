"""
Voyage AI Embedder Implementation.
Uses the official voyageai SDK with support for both contextualized models
(e.g., voyage-context-4) and standard embedding models (e.g., voyage-3).
Enforces RPM rate limiting and supports both single and batch embedding.
Embeds ONLY occupation and activity (education is excluded).
"""

import time
import asyncio
import logging
from typing import List, Optional

import voyageai

log = logging.getLogger(__name__)


class VoyageEmbedder:
    """
    Implements Embedder protocol using the official voyageai SDK.
    Supports voyage-context-4 (via contextualized_embed) and standard models (via embed).
    Enforces RPM rate limiting (default 3 RPM for free tier).
    """

    def __init__(
        self,
        api_key: str,
        model: str = "voyage-context-4",
        dimension: int = 1024,
        rpm_limit: int = 3,
        tpm_limit: int = 10000,
        timeout: float = 25.0,
        max_retries: int = 3,
    ):
        self._api_key   = api_key
        self._model     = model
        self._dimension = dimension
        self._rpm_limit = rpm_limit
        self._tpm_limit = tpm_limit
        self._timeout   = timeout
        self._max_retries = max_retries

        # Rate limiting: min interval between requests (+1.0s safety margin for strict 60s windows)
        raw_interval = 60.0 / max(1, self._rpm_limit)
        self._min_interval = max(raw_interval + 1.0, 21.0)
        self._last_call_time = 0.0
        self._rate_lock = asyncio.Lock()

        # Official async SDK client
        self._client = voyageai.AsyncClient(api_key=api_key)

        log.info(f"VoyageEmbedder initialized: model={model} dim={dimension} rpm={rpm_limit} min_interval={self._min_interval:.1f}s")

    async def _throttle(self) -> None:
        """Enforces RPM minimum interval between API calls."""
        async with self._rate_lock:
            now = time.monotonic()
            elapsed = now - self._last_call_time
            if elapsed < self._min_interval:
                wait_time = self._min_interval - elapsed
                log.info(f"Voyage rate-limit throttle: sleeping {wait_time:.1f}s")
                await asyncio.sleep(wait_time)
            self._last_call_time = time.monotonic()

    async def embed(self, text: str) -> List[float]:
        """Generates embedding for a single text string."""
        results = await self.embed_batch([text])
        return results[0] if results else [0.0] * self._dimension

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Embeds a list of texts using the official Voyage SDK.
        Automatically uses contextualized_embed for context models (like voyage-context-4)
        or embed for standard embedding models.
        Handles rate limiting and retries on errors.
        """
        if not texts:
            return []

        clean_texts = [t.strip() for t in texts if t and t.strip()]
        if not clean_texts:
            return [[0.0] * self._dimension for _ in texts]

        for attempt in range(self._max_retries + 1):
            await self._throttle()
            try:
                if "context" in self._model.lower():
                    # voyage-context models (e.g. voyage-context-4) require contextualized_embed
                    # Each input text is treated as a 1-chunk document/query group
                    inputs = [[t] for t in clean_texts]
                    response = await self._client.contextualized_embed(
                        model=self._model,
                        inputs=inputs,
                        input_type="query",
                        output_dimension=self._dimension,
                    )
                    vectors = [item.embeddings[0] for item in response.results]
                else:
                    result = await self._client.embed(
                        clean_texts,
                        model=self._model,
                        input_type="query",
                    )
                    vectors = [emb for emb in result.embeddings]

                log.debug(f"Voyage embed_batch: {len(vectors)} vectors generated with dim={len(vectors[0]) if vectors else 0}")
                return vectors

            except voyageai.error.RateLimitError as e:
                backoff = max(25.0, (2 ** attempt) * 10.0)
                log.warning(f"Voyage RateLimitError (attempt {attempt+1}). Backing off {backoff:.1f}s: {e}")
                await asyncio.sleep(backoff)

            except voyageai.error.InvalidRequestError as e:
                log.error(f"Voyage InvalidRequestError (model={self._model}): {e}")
                raise

            except Exception as e:
                log.error(f"Voyage embed error attempt {attempt+1}: {type(e).__name__}: {e}")
                if attempt == self._max_retries:
                    raise
                await asyncio.sleep(3.0)

        return [[0.0] * self._dimension for _ in clean_texts]

    @property
    def dimension(self) -> int:
        return self._dimension

    async def close(self) -> None:
        """Closes the underlying SDK client."""
        if hasattr(self._client, "close"):
            try:
                await self._client.close()
            except Exception:
                pass
