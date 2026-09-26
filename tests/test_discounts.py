"""tests/test_discounts.py — Unit tests for billing/discounts.py."""

from __future__ import annotations

from billing.discounts import (
    calculate_discount,
    get_available_tiers,
    get_tier_rate,
    is_valid_tier,
)


def test_get_available_tiers():
    tiers = get_available_tiers()
    assert "bronze" in tiers
    assert "silver" in tiers
    assert "gold" in tiers
    assert "platinum" in tiers


def test_is_valid_tier():
    assert is_valid_tier("gold") is True
    assert is_valid_tier("GOLD") is True
    assert is_valid_tier("invalid") is False


def test_get_tier_rate():
    assert get_tier_rate("bronze") == 0.05
    assert get_tier_rate("gold") == 0.20
    assert get_tier_rate("unknown") == 0.0


def test_bronze_tier_discount():
    customer = {"id": 1, "tier": "bronze"}
    assert calculate_discount(customer) == 0.05


def test_gold_tier_discount():
    customer = {"id": 2, "tier": "gold"}
    assert calculate_discount(customer) == 0.20


def test_unknown_tier_returns_zero():
    customer = {"id": 3, "tier": "diamond"}
    assert calculate_discount(customer) == 0.0
