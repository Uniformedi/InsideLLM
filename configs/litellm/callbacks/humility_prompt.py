"""InsideLLM Humility prompt adapter — thin wrapper around humility-guardrail.

Adds InsideLLM-specific behavior:
  - Loads the active governance-tier prompt from Redis (editable via
    Governance Hub admin UI) with in-memory caching.
  - Falls back to the canonical prompt shipped in humility-guardrail.

The canonical Humility framework lives in the standalone repo:
    https://github.com/uniformedi/humility-guardrail

SAIVAS framework originally published in "Uniform Gnosis, Volume I" by Dan Medina.
See NOTICE for attribution.
"""
from __future__ import annotations

import logging
import os
import time

from humility.adapters.litellm import HumilityPromptCallback as _BaseHumilityPrompt
from humility.prompt import system_prompt as _fallback_prompt

logger = logging.getLogger("insidellm.humility_prompt")

REDIS_KEY_PREFIX = "insidellm:system_prompt:"
CACHE_TTL = 60  # seconds


def _get_redis():
    try:
        import redis
        host = os.environ.get("REDIS_HOST", "redis")
        port = int(os.environ.get("REDIS_PORT", "6379"))
        return redis.Redis(host=host, port=port, decode_responses=True, socket_timeout=1)
    except Exception:
        return None


class HumilityPromptCallback(_BaseHumilityPrompt):
    """Load the governance-hub-managed prompt from Redis per tier."""

    def __init__(self) -> None:
        tier = os.environ.get("GOVERNANCE_TIER", "tier3")
        super().__init__(tier=tier)
        self._cache: dict[str, str] = {}
        self._cache_time: dict[str, float] = {}

    def load_prompt(self) -> str:
        now = time.monotonic()
        if self.tier in self._cache and (now - self._cache_time.get(self.tier, 0)) < CACHE_TTL:
            return self._cache[self.tier]

        try:
            r = _get_redis()
            if r:
                prompt = r.get(f"{REDIS_KEY_PREFIX}{self.tier}")
                r.close()
                if prompt:
                    self._cache[self.tier] = prompt
                    self._cache_time[self.tier] = now
                    return prompt
        except Exception as e:
            logger.debug(f"Redis read failed: {e}")

        if self.tier in self._cache:
            return self._cache[self.tier]

        return _fallback_prompt(self.tier)


# Module-level instance for LiteLLM's custom_callback_path loader.
proxy_handler_instance = HumilityPromptCallback()
