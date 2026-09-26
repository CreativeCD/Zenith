"""billing/discounts.py — Customer discount calculation module.

Reference: SWE-bench Archetype Issue (KeyError on missing tier).
Provides tier-based discount calculation for billing.
"""

from __future__ import annotations

from typing import Any, Dict

TIER_DISCOUNTS: Dict[str, float] = {
    "bronze": 0.05,
    "silver": 0.10,
    "gold": 0.20,
    "platinum": 0.30,
}


def get_available_tiers() -> list[str]:
    """Return all supported customer tiers."""
    return list(TIER_DISCOUNTS.keys())


def is_valid_tier(tier: str) -> bool:
    """Check if given tier name is valid."""
    return tier.lower() in TIER_DISCOUNTS


def get_tier_rate(tier: str) -> float:
    """Return discount rate for a specific tier."""
    return TIER_DISCOUNTS.get(tier.lower(), 0.0)


# Calculate discount based on customer tier
# ─────────────────────────────────────────────────────────────────────────────


def calculate_discount(customer: dict[str, Any]) -> float:
    """Calculate the discount percentage for a customer based on tier.

    Returns float discount percentage.
    """
    tier = customer.get("tier")
    if tier is None:
        return 0.0
    return TIER_DISCOUNTS.get(str(tier).lower(), 0.0)
