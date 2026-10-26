import re
"""
Remote LLM Client Implementation.
Features:
- Multi-Account API key rotation with mid-batch recovery (no row loss).
- Graceful pause when all keys are exhausted with user resume capability.
- System prompt prefix caching for static 9 ISCO sections.
- Strictly operates on text names; maps selection to official candidate codes in Python.
"""

import json
import logging
import asyncio
from typing import List, Tuple, Optional, Dict
import httpx
from Service.interfaces.pipeline_context import Candidate
from Service.interfaces.base_llm import LLMUnderstandingResult
from Service.prompts.coding_prompts import (
    STATIC_SECTIONS_SYSTEM_PROMPT,
    build_understand_prompt,
    build_hierarchical_tree,
    build_selection_prompt,
)

log = logging.getLogger(__name__)

def _parse_json_safely(raw: str) -> dict:
    """Parses JSON safely even if wrapped in markdown ```json ... ``` or extra whitespace."""
    if not raw or not raw.strip():
        raise ValueError("Empty LLM response")
    clean = raw.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean)
        clean = re.sub(r"\s*```$", "", clean).strip()
    try:
        return json.loads(clean)
    except Exception:
        m = re.search(r"(\{.*\})", clean, re.DOTALL)
        if m:
            return json.loads(m.group(1))
        raise



class AllKeysExhaustedError(Exception):
    """Raised when all configured LLM API keys have exhausted their monthly quota."""
    pass


class RemoteLLMClient:
    """
    Implements LLMClient protocol.
    Works with any OpenAI-compatible API endpoint (Groq, OpenAI, Mistral, OpenRouter, etc.).
    """

    def __init__(
        self,
        base_url: str,
        api_keys: List[str],
        model: str = "gemma2-9b-it",
        concurrency: int = 4,
        temperature: float = 0.0,
        timeout: float = 35.0,
        max_tokens_per_key: int = 1000000,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_keys = [k.strip() for k in api_keys if k.strip()]
        self._model = model
        self._concurrency = concurrency
        self._temperature = temperature
        self._timeout = timeout
        self._max_tokens_per_key = max_tokens_per_key

        self._current_key_idx = 0
        self._exhausted_keys: set = set()
        self._token_counts: Dict[str, int] = {k: 0 for k in self._api_keys}
        self._lock = asyncio.Lock()

    def add_api_key_and_resume(self, new_key: str) -> None:
        """Adds a new valid key when all previous keys were exhausted."""
        k = new_key.strip()
        if k and k not in self._api_keys:
            self._api_keys.append(k)
            self._token_counts[k] = 0
            self._current_key_idx = len(self._api_keys) - 1
            log.info(f"Added new active LLM API key. Total keys: {len(self._api_keys)}")

    async def _get_current_key(self) -> str:
        """Returns the currently active API key, rotating if necessary."""
        async with self._lock:
            if not self._api_keys:
                raise AllKeysExhaustedError("No LLM API keys configured in .env.")

            # Check if all keys exhausted
            if len(self._exhausted_keys) >= len(self._api_keys):
                raise AllKeysExhaustedError(
                    "All LLM API keys have exhausted their quota. Please add a new API key to resume."
                )

            return self._api_keys[self._current_key_idx]

    async def _rotate_key(self, failed_key: str) -> str:
        """Switches to the next non-exhausted key safely."""
        async with self._lock:
            self._exhausted_keys.add(failed_key)
            log.warning(f"LLM API key marked exhausted. Total exhausted: {len(self._exhausted_keys)}/{len(self._api_keys)}")

            for idx in range(len(self._api_keys)):
                cand_idx = (self._current_key_idx + 1 + idx) % len(self._api_keys)
                cand_key = self._api_keys[cand_idx]
                if cand_key not in self._exhausted_keys:
                    self._current_key_idx = cand_idx
                    log.info(f"Switched to active LLM API key #{cand_idx + 1}")
                    return cand_key

            raise AllKeysExhaustedError(
                "All LLM API keys have exhausted their quota. Please add a new API key to resume."
            )

    async def _call_api(self, messages: list) -> str:
        """Calls the OpenAI-compatible chat completion endpoint with mid-batch key rotation."""
        while True:
            current_key = await self._get_current_key()
            headers = {
                "Authorization": f"Bearer {current_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self._model,
                "messages": messages,
                "temperature": self._temperature,
                "response_format": {"type": "json_object"},
            }

            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(
                        f"{self._base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    )

                if resp.status_code == 200:
                    data = resp.json()
                    # Track token usage
                    usage = data.get("usage", {})
                    total_tokens = usage.get("total_tokens", 0)
                    self._token_counts[current_key] = self._token_counts.get(current_key, 0) + total_tokens

                    # Check if key exceeded monthly token limit
                    if self._token_counts[current_key] >= self._max_tokens_per_key:
                        log.info(f"Key reached monthly token quota ({self._max_tokens_per_key}). Rotating...")
                        await self._rotate_key(current_key)

                    return data["choices"][0]["message"]["content"]

                elif resp.status_code in (429, 402):
                    # Rate limit or quota exceeded: rotate key and retry the SAME row immediately!
                    log.warning(f"Key returned {resp.status_code}. Rotating to next key...")
                    await self._rotate_key(current_key)
                    continue

                else:
                    log.error(f"LLM API error status {resp.status_code}: {resp.text}")
                    # If unauthorized or invalid key, rotate
                    if resp.status_code == 401:
                        await self._rotate_key(current_key)
                        continue
                    raise RuntimeError(f"LLM API error {resp.status_code}: {resp.text}")

            except httpx.RequestError as e:
                log.error(f"Network error in LLM call: {e}")
                await asyncio.sleep(2.0)
                continue

    async def understand(self, row_context: str) -> LLMUnderstandingResult:
        """
        Extracts standardized job description while strictly preserving craft keywords,
        and predicts candidate ISCO Major Sections (1 to 9).
        """
        # Parse context parameters if passed as JSON or text
        occ, act, edu = row_context, "", ""
        if "\n" in row_context:
            for line in row_context.splitlines():
                if "المهنة:" in line or "occupation:" in line.lower():
                    occ = line.split(":", 1)[-1].strip()
                elif "النشاط:" in line or "activity:" in line.lower():
                    act = line.split(":", 1)[-1].strip()
                elif "المؤهل:" in line or "education:" in line.lower():
                    edu = line.split(":", 1)[-1].strip()

        messages = [
            {"role": "system", "content": STATIC_SECTIONS_SYSTEM_PROMPT},
            {"role": "user", "content": build_understand_prompt(occ, act, edu)},
        ]

        raw_json = await self._call_api(messages)
        try:
            parsed = _parse_json_safely(raw_json)
            desc = parsed.get("work_description", row_context)
            secs = [int(s) for s in parsed.get("work_nature_sections", [5]) if str(s).isdigit()]
            return LLMUnderstandingResult(work_description=desc, work_nature_sections=secs)
        except Exception as e:
            log.warning(f"Failed to parse LLM understand response: {e}")
            return LLMUnderstandingResult(work_description=row_context, work_nature_sections=[5])

    async def select_best(
        self,
        row_context: str,
        candidates: List[Candidate]
    ) -> Tuple[str, str, float, str]:
        """
        Selects best candidate using purely text-based tree presentation.
        Maps the chosen text name back to the official Candidate object in Python.
        """
        if not candidates:
            return "", "", 0.0, "No candidates available"

        # Build name -> Candidate lookup dictionary for 100% exact code mapping
        name_map = {c.name.strip(): c for c in candidates}

        # Build tree text without codes
        tree_text = build_hierarchical_tree(candidates)

        messages = [
            {"role": "system", "content": STATIC_SECTIONS_SYSTEM_PROMPT},
            {"role": "user", "content": build_selection_prompt(row_context, tree_text)},
        ]

        raw_json = await self._call_api(messages)
        try:
            parsed = _parse_json_safely(raw_json)
            selected_name = parsed.get("selected_occ", "").strip()
            confidence = float(parsed.get("confidence", 0.90))
            reason = parsed.get("reason", "")

            # 1. Exact name match in candidate map
            if selected_name in name_map:
                cand = name_map[selected_name]
                return cand.code, cand.name, confidence, reason

            # 2. Fuzzy fallback match to closest candidate name
            for name, cand in name_map.items():
                if selected_name in name or name in selected_name:
                    return cand.code, cand.name, confidence, reason

            # 3. Default to top candidate if name was slightly rephrased
            top_cand = candidates[0]
            return top_cand.code, top_cand.name, confidence, f"{reason} (Selected: {selected_name})"

        except Exception as e:
            log.warning(f"Failed to parse LLM select response: {e}")
            top_cand = candidates[0]
            return top_cand.code, top_cand.name, top_cand.similarity, "Fallback to top candidate"

    def rotate_key_on_exhaustion(self, current_key: str) -> str:
        """Synchronous wrapper for manual rotation if needed."""
        self._exhausted_keys.add(current_key)
        for cand in self._api_keys:
            if cand not in self._exhausted_keys:
                return cand
        return current_key

    @property
    def concurrency_limit(self) -> int:
        return self._concurrency
