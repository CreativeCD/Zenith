"""harness/adapters/key_pool.py — Multi-Key Rotation Pool Manager for Gemini API.

Manages a pool of Google AI Studio API keys with:
- Fair round-robin rotation across available keys
- Per-key rate-limit (429) & server overload (503) cooldown tracking
- Intelligent retryDelay extraction from Google error responses
- Automatic skip of keys currently in cooldown
- Health and usage telemetry per key
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class KeyStats:
    """Usage and health statistics for an individual API key."""
    calls: int = 0
    errors: int = 0
    cooldown_until: float = 0.0

    @property
    def is_cooling_down(self) -> bool:
        return self.cooldown_until > time.time()

    @property
    def cooldown_remaining_sec(self) -> float:
        return max(0.0, self.cooldown_until - time.time())


class KeyPoolManager:
    """Thread-safe round-robin key pool manager with per-key cooldowns."""

    def __init__(self, keys: list[str] | None = None) -> None:
        if keys is not None:
            raw_keys = keys
        else:
            raw_keys = self._load_keys_from_env()

        # Split multi-key entries (comma, semicolon, newline) and deduplicate preserving order
        seen: set[str] = set()
        self._keys: list[str] = []
        for item in raw_keys:
            if not item:
                continue
            # Split comma/semicolon/newline-delimited keys
            tokens = re.split(r"[,;\n\r]+", str(item))
            for tok in tokens:
                cleaned = tok.strip().strip("'\"")
                if (
                    cleaned
                    and cleaned not in seen
                    and not cleaned.startswith("REPLACE_WITH")
                    and "your_" not in cleaned.lower()
                ):
                    seen.add(cleaned)
                    self._keys.append(cleaned)

        self._stats: dict[str, KeyStats] = {k: KeyStats() for k in self._keys}
        self._current_index: int = 0

    @staticmethod
    def _load_keys_from_env(prefixes: list[str] | None = None) -> list[str]:
        """Load API keys from environment for given prefixes (defaults to Gemini/AI keys)."""
        target_prefixes = prefixes or ["AI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"]
        keys: list[str] = []

        for pfx in target_prefixes:
            val = os.environ.get(pfx)
            if val:
                keys.append(val)
            # Look for numbered keys (e.g. PREFIX_1 to PREFIX_50)
            for i in range(1, 51):
                val_n = os.environ.get(f"{pfx}_{i}")
                if val_n:
                    keys.append(val_n)

        # Also search for any other env var matching any prefix
        for var_name, val in os.environ.items():
            for pfx in target_prefixes:
                if var_name.startswith(f"{pfx}_") and val:
                    keys.append(val)

        return keys

    @property
    def total_keys(self) -> int:
        return len(self._keys)

    @property
    def keys(self) -> list[str]:
        return list(self._keys)

    def get_next_key(self) -> tuple[str, int] | None:
        """Get the next available key that is not in cooldown.
        
        Returns:
            Tuple of (api_key, 0-based index), or None if no keys exist.
            If all keys are currently cooling down, returns the key with the
            soonest expiration time so caller can decide whether to wait.
        """
        if not self._keys:
            return None

        now = time.time()
        n = len(self._keys)

        # 1. Look for a key not in cooldown starting from current_index
        for offset in range(n):
            idx = (self._current_index + offset) % n
            key = self._keys[idx]
            stats = self._stats[key]
            if stats.cooldown_until <= now:
                self._current_index = (idx + 1) % n
                return key, idx

        # 2. All keys are cooling down — return the one that expires soonest
        best_idx = 0
        min_cooldown = float("inf")
        for idx, key in enumerate(self._keys):
            stats = self._stats[key]
            if stats.cooldown_until < min_cooldown:
                min_cooldown = stats.cooldown_until
                best_idx = idx

        self._current_index = (best_idx + 1) % n
        return self._keys[best_idx], best_idx

    def parse_retry_delay(self, error_msg: str) -> float | None:
        """Extract retryDelay in seconds from Google API error text or json."""
        if not error_msg:
            return None

        # Pattern 1: 'retryDelay': '17s' or "retryDelay": "17s"
        m = re.search(r"['\"]retryDelay['\"]\s*:\s*['\"](\d+(?:\.\d+)?)s?['\"]", error_msg)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass

        # Pattern 2: retry in 17s / retry in 17 seconds
        m = re.search(r"retry\s+in\s+(\d+(?:\.\d+)?)\s*(?:s|sec|seconds)?", error_msg, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass

        # Pattern 3: quota reset / limit in Xs
        m = re.search(r"reset\s+in\s+(\d+(?:\.\d+)?)\s*(?:s|sec|seconds)?", error_msg, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass

        return None

    def mark_rate_limited(self, key: str, retry_delay: float | None = None) -> float:
        """Mark a key as rate-limited (429/503).
        
        Args:
            key: The API key that failed
            retry_delay: Extracted retry delay from provider if available
            
        Returns:
            Calculated cooldown duration in seconds.
        """
        if retry_delay is not None:
            delay_sec = max(5.0, min(60.0, retry_delay + 1.0))
        else:
            delay_sec = 25.0

        if key in self._stats:
            stats = self._stats[key]
            stats.errors += 1
            stats.cooldown_until = time.time() + delay_sec

        logger.warning(
            "API key %s...%s marked cooling down for %.1fs (rate limited)",
            key[:6] if len(key) >= 6 else key,
            key[-4:] if len(key) >= 4 else "",
            delay_sec,
        )
        return delay_sec

    def mark_auth_error(self, key: str) -> None:
        """Mark key as having auth/permission error (401/403) — 5 minute cooldown."""
        if key in self._stats:
            stats = self._stats[key]
            stats.errors += 1
            stats.cooldown_until = time.time() + 300.0  # 5 minutes
        logger.error(
            "API key %s...%s marked invalid/auth failed for 300s",
            key[:6] if len(key) >= 6 else key,
            key[-4:] if len(key) >= 4 else "",
        )

    def record_call(self, key: str) -> None:
        """Record a successful or initiated call using this key."""
        if key in self._stats:
            self._stats[key].calls += 1

    def record_error(self, key: str) -> None:
        """Record a general error using this key."""
        if key in self._stats:
            self._stats[key].errors += 1

    def all_cooling_down(self) -> bool:
        """Check if every key in the pool is currently cooling down."""
        if not self._keys:
            return True
        now = time.time()
        return all(self._stats[k].cooldown_until > now for k in self._keys)

    def shortest_cooldown_remaining(self) -> float:
        """Return the shortest remaining cooldown in seconds among cooling keys."""
        if not self._keys:
            return 0.0
        now = time.time()
        remaining = [max(0.0, self._stats[k].cooldown_until - now) for k in self._keys]
        return min(remaining)

    def get_status(self) -> dict[str, Any]:
        """Return diagnostic status of all keys in pool for telemetry and health check."""
        now = time.time()
        key_statuses = []
        cooling_count = 0

        for idx, key in enumerate(self._keys):
            stats = self._stats[key]
            is_cooling = stats.cooldown_until > now
            if is_cooling:
                cooling_count += 1
            masked = f"{key[:8]}...{key[-4:]}" if len(key) >= 12 else "key_masked"
            key_statuses.append({
                "index": idx + 1,
                "prefix": masked,
                "calls": stats.calls,
                "errors": stats.errors,
                "cooling_down": is_cooling,
                "cooldown_remaining_sec": round(stats.cooldown_remaining_sec, 1),
            })

        return {
            "total_keys": len(self._keys),
            "active_keys": len(self._keys) - cooling_count,
            "cooling_down_keys": cooling_count,
            "keys": key_statuses,
        }
