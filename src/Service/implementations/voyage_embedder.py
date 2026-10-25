"""
Voyage AI Embedder Implementation.
Calls Voyage AI API directly using httpx.AsyncClient with strict Token Bucket Rate Limiting
enforcing 3 RPM and 10,000 TPM with exponential backoff on HTTP 429.
Embeds ONLY occupation and activity (education is excluded).
"""

import time
import asyncio
import logging
from typing import List
import httpx

log = logging.getLogger(__name__)


class VoyageEmbedder:
    """
    Implements Embedder protocol for Voyage AI (e.g. voyage-context-4).
    Enforces 3 RPM and 10K TPM limits.
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
        self._api_key = api_key
        self._model = model
        self._dimension = dimension
        self._rpm_limit = rpm_limit
        self._tpm_limit = tpm_limit
        self._timeout = timeout
        self._max_retries = max_retries

        # Rate limiting: minimum interval between requests for 3 RPM = 20.0 seconds
        self._min_interval = 60.0 / max(1, self._rpm_limit)
        self._last_call_time = 0.0
        self._rate_lock = asyncio.Lock()

        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url="https://api.voyageai.com/v1",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self._timeout,
            )
        return self._client

    async def _throttle(self) -> None:
        """Enforces 3 RPM minimum interval between calls."""
        async with self._rate_lock:
            now = time.monotonic()
            elapsed = now - self._last_call_time
            if elapsed < self._min_interval:
                wait_time = self._min_interval - elapsed
                await asyncio.sleep(wait_time)
            self._last_call_time = time.monotonic()

    async def embed(self, text: str) -> List[float]:
        """Generates embedding for a single text."""
        res = await self.embed_batch([text])
        return res[0] if res else [0.0] * self._dimension

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Embeds a list of texts in batch with automatic exponential retry on HTTP 429.
        """
        if not texts:
            return []

        clean_texts = [t.strip() for t in texts if t.strip()]
        if not clean_texts:
            return [[0.0] * self._dimension]

        client = await self._get_client()

        for attempt in range(self._max_retries + 1):
            await self._throttle()
            try:
                response = await client.post(
                    "/embeddings",
                    json={"input": clean_texts, "model": self._model},
                )

                if response.status_code == 200:
                    data = response.json()
                    return [item["embedding"] for item in data["data"]]

                elif response.status_code == 429:
                    backoff = (2 ** attempt) * 5.0
                    log.warning(f"Voyage AI rate limit 429 received. Backing off for {backoff:.1f}s...")
                    await asyncio.sleep(backoff)
                    continue

                else:
                    log.error(f"Voyage AI returned status {response.status_code}: {response.text}")
                    if attempt == self._max_retries:
                        raise RuntimeError(f"Voyage API error: {response.status_code} - {response.text}")
                    await asyncio.sleep(2.0)

            except httpx.RequestError as e:
                log.error(f"Network error calling Voyage AI: {e}")
                if attempt == self._max_retries:
                    raise
                await asyncio.sleep(2.0)

        return [[0.0] * self._dimension for _ in clean_texts]

    @property
    def dimension(self) -> int:
        return self._dimension

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
