"""tests/test_key_pool.py — Unit tests for KeyPoolManager."""

import time
from harness.adapters.key_pool import KeyPoolManager


def test_key_pool_initialization_and_dedup():
    keys = [
        "key1",
        "  key2  ",
        "key1",  # duplicate
        "",      # empty
        "REPLACE_WITH_KEY",  # placeholder
        "key3",
    ]
    pool = KeyPoolManager(keys=keys)
    assert pool.total_keys == 3
    assert pool.keys == ["key1", "key2", "key3"]


def test_key_pool_round_robin():
    pool = KeyPoolManager(keys=["k1", "k2", "k3"])
    k, idx = pool.get_next_key()
    assert (k, idx) == ("k1", 0)

    k, idx = pool.get_next_key()
    assert (k, idx) == ("k2", 1)

    k, idx = pool.get_next_key()
    assert (k, idx) == ("k3", 2)

    # Wrap around
    k, idx = pool.get_next_key()
    assert (k, idx) == ("k1", 0)


def test_key_pool_skip_cooldown():
    pool = KeyPoolManager(keys=["k1", "k2", "k3"])

    # Put k1 in cooldown for 30s
    pool.mark_rate_limited("k1", retry_delay=15.0)
    assert pool._stats["k1"].is_cooling_down is True

    # Next key should skip k1 and return k2
    k, idx = pool.get_next_key()
    assert (k, idx) == ("k2", 1)

    # Then k3
    k, idx = pool.get_next_key()
    assert (k, idx) == ("k3", 2)

    # Then k2 again (since k1 is still cooling down)
    k, idx = pool.get_next_key()
    assert (k, idx) == ("k2", 1)


def test_key_pool_all_cooling_down_picks_soonest():
    pool = KeyPoolManager(keys=["k1", "k2"])
    now = time.time()

    # k1 expires in 20s, k2 expires in 5s
    pool._stats["k1"].cooldown_until = now + 20
    pool._stats["k2"].cooldown_until = now + 5

    assert pool.all_cooling_down() is True
    # Should pick k2 as soonest to recover
    k, idx = pool.get_next_key()
    assert (k, idx) == ("k2", 1)


def test_retry_delay_parser():
    pool = KeyPoolManager(keys=["k1"])

    # Google genai detail format
    msg1 = "{'error': {'details': [{'retryDelay': '18s'}]}}"
    assert pool.parse_retry_delay(msg1) == 18.0

    # JSON formatted
    msg2 = '{"error": {"details": [{"retryDelay": "14.5s"}]}}'
    assert pool.parse_retry_delay(msg2) == 14.5

    # Text format
    msg3 = "Resource exhausted: retry in 22 seconds."
    assert pool.parse_retry_delay(msg3) == 22.0

    # None if unparseable
    assert pool.parse_retry_delay("Generic 429 error") is None


def test_key_pool_auth_error_cooldown():
    pool = KeyPoolManager(keys=["k1"])
    pool.mark_auth_error("k1")
    assert pool._stats["k1"].cooldown_remaining_sec > 250.0
    assert pool._stats["k1"].errors == 1


def test_key_pool_status():
    pool = KeyPoolManager(keys=["MOCK_SAMPLE_KEY_1234567890_ABCD", "shortkey"])
    pool.record_call(pool.keys[0])
    pool.mark_rate_limited(pool.keys[1], retry_delay=10.0)

    status = pool.get_status()
    assert status["total_keys"] == 2
    assert status["active_keys"] == 1
    assert status["cooling_down_keys"] == 1
    assert len(status["keys"]) == 2
    assert status["keys"][0]["calls"] == 1
    assert status["keys"][1]["cooling_down"] is True
