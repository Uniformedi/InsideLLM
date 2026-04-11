"""
Humility Prompt Callback — injects governance-managed system meta-prompts
into every LLM call routed through LiteLLM.

Reads the active prompt for the configured governance tier from Redis.
Falls back to a hardcoded minimal prompt if Redis is unavailable.

The prompt is prepended as the first system message. A sentinel marker
prevents double-injection on retries.
"""

import os
import time
import logging

from litellm.integrations.custom_logger import CustomLogger

logger = logging.getLogger("litellm.humility_prompt")

REDIS_KEY_PREFIX = "insidellm:system_prompt:"
SENTINEL = "[HUMILITY_INJECTED]"
CACHE_TTL = 60  # seconds

# Minimal fallback prompt if Redis is unavailable
FALLBACK_PROMPT = (
    "You are an AI assistant. Be transparent about your limitations, "
    "acknowledge uncertainty when present, and serve the user's genuine interests. "
    "Recommend human review for important decisions."
)

# In-memory cache
_cache = {}
_cache_time = {}


def _get_redis():
    """Get a Redis connection."""
    try:
        import redis
        host = os.environ.get("REDIS_HOST", "redis")
        port = int(os.environ.get("REDIS_PORT", "6379"))
        return redis.Redis(host=host, port=port, decode_responses=True, socket_timeout=1)
    except Exception:
        return None


def _get_prompt(tier: str) -> str:
    """Get the active prompt for a tier, with caching and fallback."""
    now = time.monotonic()

    # Check cache
    if tier in _cache and (now - _cache_time.get(tier, 0)) < CACHE_TTL:
        return _cache[tier]

    # Try Redis
    try:
        r = _get_redis()
        if r:
            prompt = r.get(f"{REDIS_KEY_PREFIX}{tier}")
            r.close()
            if prompt:
                _cache[tier] = prompt
                _cache_time[tier] = now
                return prompt
    except Exception as e:
        logger.debug(f"Redis read failed: {e}")

    # Return cached value if available (even if stale)
    if tier in _cache:
        return _cache[tier]

    # Final fallback
    return FALLBACK_PROMPT


class HumilityPromptCallback(CustomLogger):
    """LiteLLM custom callback that injects Humility system prompts."""

    def __init__(self):
        super().__init__()
        self.tier = os.environ.get("GOVERNANCE_TIER", "tier3")
        logger.info(f"HumilityPromptCallback initialized (tier: {self.tier})")

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        """Called before every LLM API call. Injects system prompt."""
        if call_type not in ("completion", "acompletion"):
            return data

        messages = data.get("messages", [])
        if not messages:
            return data

        # Check for sentinel to avoid double-injection
        if messages and messages[0].get("role") == "system":
            if SENTINEL in (messages[0].get("content") or ""):
                return data

        # Get the prompt for the configured tier
        prompt = _get_prompt(self.tier)
        if not prompt:
            return data

        # Prepend as the first system message with sentinel
        system_msg = {
            "role": "system",
            "content": f"{SENTINEL}\n{prompt}",
        }

        # If there's already a system message, merge them
        if messages and messages[0].get("role") == "system":
            existing = messages[0].get("content", "")
            messages[0]["content"] = f"{SENTINEL}\n{prompt}\n\n{existing}"
        else:
            messages.insert(0, system_msg)

        data["messages"] = messages
        return data
