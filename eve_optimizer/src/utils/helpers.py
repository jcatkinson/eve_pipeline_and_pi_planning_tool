"""
src/utils/helpers.py
~~~~~~~~~~~~~~~~~~~~
Shared utility functions: ISK formatting, fee math, volume calculations.
No I/O or ESI calls here — pure computation.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# ISK / currency
# ---------------------------------------------------------------------------

def format_isk(amount: float) -> str:
    """Return a human-readable ISK string, e.g. '1.23B ISK', '456.78M ISK'."""
    abs_amount = abs(amount)
    sign = "-" if amount < 0 else ""
    if abs_amount >= 1_000_000_000:
        return f"{sign}{abs_amount / 1_000_000_000:.2f}B ISK"
    if abs_amount >= 1_000_000:
        return f"{sign}{abs_amount / 1_000_000:.2f}M ISK"
    if abs_amount >= 1_000:
        return f"{sign}{abs_amount / 1_000:.2f}K ISK"
    return f"{sign}{abs_amount:.2f} ISK"


# ---------------------------------------------------------------------------
# Fee calculations
# These mirror the in-game formulas documented in the EVE University wiki.
# ---------------------------------------------------------------------------

def effective_sales_tax(accounting_level: int, base_rate: float = 0.08) -> float:
    """
    Calculate the effective sales tax after the Accounting skill.

    Each level of Accounting reduces sales tax by 11% of the base rate.
    Formula: base_rate * (1 - 0.11 * level)

    Args:
        accounting_level: Character's Accounting skill level (0–5).
        base_rate: CCP base sales tax (default 8%).

    Returns:
        Effective tax rate as a decimal fraction.
    """
    return base_rate * (1.0 - 0.11 * accounting_level)


def effective_broker_fee(broker_relations_level: int, base_rate: float = 0.03) -> float:
    """
    Calculate the effective broker fee after Broker Relations.

    Each level of Broker Relations reduces the broker fee by 3% of the base rate.
    Formula: base_rate * (1 - 0.03 * level)

    Args:
        broker_relations_level: Character's Broker Relations skill level (0–5).
        base_rate: CCP base broker fee at NPC stations (default 3%).

    Returns:
        Effective fee rate as a decimal fraction.
    """
    return base_rate * (1.0 - 0.03 * broker_relations_level)


def net_sell_value(
    gross_price: float,
    units: float,
    sales_tax_rate: float,
    broker_fee_rate: float,
    transport_risk_factor: float = 0.0,
    poco_tax_rate: float = 0.0,
) -> float:
    """
    Net ISK received after all deductions for a sell-order transaction.

    net = (gross_price * units)
          * (1 - sales_tax_rate - broker_fee_rate - transport_risk_factor - poco_tax_rate)

    Args:
        gross_price: Per-unit market sell price (ISK).
        units: Number of units being sold.
        sales_tax_rate: Effective sales tax as decimal.
        broker_fee_rate: Effective broker fee as decimal.
        transport_risk_factor: Fractional expected loss from hauling (0.0 if local).
        poco_tax_rate: POCO export tax rate (0.0 to disable). Default: 0.0.

    Returns:
        Net ISK after all deductions.
    """
    gross = gross_price * units
    return gross * (1.0 - sales_tax_rate - broker_fee_rate - transport_risk_factor - poco_tax_rate)


# ---------------------------------------------------------------------------
# Volume / logistics
# ---------------------------------------------------------------------------

def total_volume(unit_volume_m3: float, units: float) -> float:
    """Return total cargo volume in m³."""
    return unit_volume_m3 * units


def isk_per_m3(net_isk: float, volume_m3: float) -> float:
    """Return ISK/m³ efficiency metric; returns 0.0 if volume is zero."""
    if volume_m3 <= 0:
        return 0.0
    return net_isk / volume_m3
