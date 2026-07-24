"""
src/core/profit_engine.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Core profit decision engine.

For each PI chain in the database it computes two competing values:

  SELL RAW
      Net ISK received if you sell all required input P1/P2 materials
      directly on the Jita market right now.

  PROCESS & MANUFACTURE
      Net ISK received after processing those inputs into the finished
      P3/P4 output and selling that instead.

Both sides are calculated AFTER deducting:
  - Sales tax       (reduced by character Accounting skill level)
  - Broker fees     (reduced by character Broker Relations skill level)
  - Transport risk  (manual fraction of cargo value, modelling low-sec haul loss)
  - POCO tax        (Planetary Customs Office export tax, applied to both sides)

The engine emits a DecisionResult per chain, including the numeric delta
and a binary RECOMMENDATION: "SELL RAW" or "PROCESS & MANUFACTURE".

Moved from src/profit_engine.py in Phase 1 restructure.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Optional

from src.config import (
    BASE_BROKER_FEE_RATE,
    BASE_SALES_TAX_RATE,
    DB_PATH,
    TRANSPORT_RISK_FACTOR,
)
from src.utils.helpers import (
    effective_broker_fee,
    effective_sales_tax,
    format_isk,
    isk_per_m3,
    net_sell_value,
    total_volume,
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MaterialPrice:
    type_id: int
    name: str
    tier: int
    qty: int
    unit_price: float        # best Jita sell price per unit
    volume_m3: float
    price_source: str = "live"  # "live" | "history" | "none"

    @property
    def total_value(self) -> float:
        return self.unit_price * self.qty

    @property
    def total_volume_m3(self) -> float:
        return self.volume_m3 * self.qty


@dataclass
class DecisionResult:
    output_type_id: int
    output_name: str
    output_tier: int
    output_qty: int
    planet_types: list[str]

    # Raw inputs
    inputs: list[MaterialPrice] = field(default_factory=list)

    # Prices
    output_unit_price: float = 0.0          # best Jita sell price for finished good
    output_price_source: str = "live"       # "live" | "history" | "none"
    output_volume_m3: float = 0.0

    # Computed P&L
    sell_raw_net_isk: float = 0.0           # net ISK from selling inputs
    process_net_isk: float = 0.0            # net ISK from selling finished output
    delta_isk: float = 0.0                  # process_net - sell_raw  (positive = process wins)
    recommendation: str = "UNKNOWN"         # "SELL RAW" | "PROCESS & MANUFACTURE"

    # Hauling density metrics
    input_isk_per_m3: float = 0.0           # sell_raw_net / total input cargo volume
    output_isk_per_m3: float = 0.0          # process_net / total output cargo volume

    # Cost details for transparency
    accounting_level: int = 0
    broker_relations_level: int = 0
    applied_sales_tax: float = 0.0
    applied_broker_fee: float = 0.0
    transport_risk_factor: float = 0.0
    applied_poco_tax: float = 0.0

    def summary_line(self) -> str:
        arrow = "✔ PROCESS & MANUFACTURE" if self.recommendation == "PROCESS & MANUFACTURE" else "✘ SELL RAW"
        return (
            f"[{self.output_tier}] {self.output_name:<35}"
            f"  Raw={format_isk(self.sell_raw_net_isk):<18}"
            f"  Mfg={format_isk(self.process_net_isk):<18}"
            f"  Δ={format_isk(self.delta_isk):<18}"
            f"  {arrow}"
        )


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class ProfitEngine:
    """
    Evaluates every PI chain in the database and returns DecisionResults.

    Args:
        esi_client: An authenticated ESIClient instance.
        accounting_level: Character Accounting skill level (0–5).
        broker_relations_level: Character Broker Relations skill level (0–5).
        planet_type_filter: Optional list of planet types to restrict results.
        transport_risk_factor: Fractional cargo-loss risk from hauling.
        poco_tax: POCO export tax rate applied symmetrically to both sides (0.0–1.0).
        db_path: Path to the SQLite blueprints database.
    """

    def __init__(
        self,
        esi_client,
        accounting_level: int = 0,
        broker_relations_level: int = 0,
        planet_type_filter: Optional[list[str]] = None,
        transport_risk_factor: float = TRANSPORT_RISK_FACTOR,
        poco_tax: float = 0.05,
        db_path=DB_PATH,
    ) -> None:
        self._esi = esi_client
        self.accounting_level = accounting_level
        self.broker_relations_level = broker_relations_level
        self.planet_type_filter = [p.lower() for p in planet_type_filter] if planet_type_filter else None
        self.transport_risk_factor = transport_risk_factor
        self.poco_tax = poco_tax
        self.db_path = db_path

        self.sales_tax_rate = effective_sales_tax(accounting_level, BASE_SALES_TAX_RATE)
        self.broker_fee_rate = effective_broker_fee(broker_relations_level, BASE_BROKER_FEE_RATE)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, min_tier: int = 3) -> list[DecisionResult]:
        """
        Evaluate all chains with output tier >= min_tier.

        Args:
            min_tier: Minimum output tier to evaluate (1–4).

        Returns:
            List of DecisionResult sorted by delta_isk descending
            (best "Process & Manufacture" opportunities first).
        """
        import json

        chains = self._load_chains(min_tier)
        results: list[DecisionResult] = []

        # Collect all type IDs we need prices for in a single batch
        all_type_ids: set[int] = set()
        for chain in chains:
            all_type_ids.add(chain["output_type_id"])
            for m in chain["materials"]:
                all_type_ids.add(m["input_type_id"])

        prices = self._fetch_prices(list(all_type_ids))

        for chain in chains:
            planet_types: list[str] = json.loads(chain["planet_types"])

            # Apply planet type filter if set
            if self.planet_type_filter and planet_types != ["any"]:
                if not any(pt in self.planet_type_filter for pt in planet_types):
                    continue

            inputs = [
                MaterialPrice(
                    type_id=m["input_type_id"],
                    name=m["input_name"],
                    tier=m["input_tier"],
                    qty=m["input_qty"],
                    unit_price=prices.get(m["input_type_id"], (0.0, "none"))[0],
                    volume_m3=m["input_volume"],
                    price_source=prices.get(m["input_type_id"], (0.0, "none"))[1],
                )
                for m in chain["materials"]
            ]

            out_price_tuple = prices.get(chain["output_type_id"], (0.0, "none"))
            output_price = out_price_tuple[0]
            output_price_source = out_price_tuple[1]
            output_vol = chain["output_volume"]

            # --- SELL RAW ---
            # Net ISK from selling all inputs individually
            sell_raw = sum(
                net_sell_value(
                    gross_price=inp.unit_price,
                    units=inp.qty,
                    sales_tax_rate=self.sales_tax_rate,
                    broker_fee_rate=self.broker_fee_rate,
                    transport_risk_factor=self.transport_risk_factor,
                    poco_tax_rate=self.poco_tax,
                )
                for inp in inputs
            )

            # --- PROCESS & MANUFACTURE ---
            # Net ISK from selling the finished output
            process = net_sell_value(
                gross_price=output_price,
                units=chain["output_qty"],
                sales_tax_rate=self.sales_tax_rate,
                broker_fee_rate=self.broker_fee_rate,
                transport_risk_factor=self.transport_risk_factor,
                poco_tax_rate=self.poco_tax,
            )

            delta = process - sell_raw
            recommendation = "PROCESS & MANUFACTURE" if delta > 0 else "SELL RAW"

            # --- Hauling density ---
            total_input_vol = sum(inp.total_volume_m3 for inp in inputs)
            total_output_vol = chain["output_qty"] * output_vol
            in_density = isk_per_m3(sell_raw, total_input_vol)
            out_density = isk_per_m3(process, total_output_vol)

            result = DecisionResult(
                output_type_id=chain["output_type_id"],
                output_name=chain["output_name"],
                output_tier=chain["output_tier"],
                output_qty=chain["output_qty"],
                planet_types=planet_types,
                inputs=inputs,
                output_unit_price=output_price,
                output_price_source=output_price_source,
                output_volume_m3=output_vol,
                sell_raw_net_isk=sell_raw,
                process_net_isk=process,
                delta_isk=delta,
                recommendation=recommendation,
                input_isk_per_m3=in_density,
                output_isk_per_m3=out_density,
                accounting_level=self.accounting_level,
                broker_relations_level=self.broker_relations_level,
                applied_sales_tax=self.sales_tax_rate,
                applied_broker_fee=self.broker_fee_rate,
                transport_risk_factor=self.transport_risk_factor,
                applied_poco_tax=self.poco_tax,
            )
            results.append(result)

        results.sort(key=lambda r: r.delta_isk, reverse=True)
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_chains(self, min_tier: int) -> list[dict]:
        """Fetch blueprint chains from SQLite, joining materials and items."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            blueprints = conn.execute(
                """
                SELECT b.blueprint_id, b.output_type_id, b.output_qty, b.planet_types,
                       i.name AS output_name, i.tier AS output_tier, i.volume_m3 AS output_volume
                FROM   pi_blueprints b
                JOIN   pi_items i ON i.type_id = b.output_type_id
                WHERE  i.tier >= ?
                """,
                (min_tier,),
            ).fetchall()

            chains = []
            for bp in blueprints:
                materials = conn.execute(
                    """
                    SELECT m.input_type_id, m.input_qty,
                           i.name AS input_name, i.tier AS input_tier, i.volume_m3 AS input_volume
                    FROM   pi_materials m
                    JOIN   pi_items i ON i.type_id = m.input_type_id
                    WHERE  m.blueprint_id = ?
                    """,
                    (bp["blueprint_id"],),
                ).fetchall()
                chains.append({**dict(bp), "materials": [dict(m) for m in materials]})
            return chains
        finally:
            conn.close()

    def _fetch_prices(self, type_ids: list[int]) -> dict[int, tuple[float, str]]:
        """
        Return (price, source) for each type ID.

        source is one of:
          "live"    — lowest active Jita sell order
          "history" — 5-day average from market history (no live orders present)
          "none"    — no price data available at all
        """
        import sys
        print(f"[ProfitEngine] Fetching market prices for {len(type_ids)} items...", file=sys.stderr)
        orders = self._esi.get_market_orders(type_ids, order_type="sell")
        prices: dict[int, tuple[float, str]] = {}
        no_orders: list[int] = []

        for type_id, order_list in orders.items():
            sell_orders = [o for o in order_list if not o.get("is_buy_order", True)]
            if sell_orders:
                prices[type_id] = (min(o["price"] for o in sell_orders), "live")
            else:
                no_orders.append(type_id)

        # Fall back to market history for any items with no active sell orders
        if no_orders:
            print(
                f"[ProfitEngine] No live orders for {len(no_orders)} item(s) — "
                "falling back to 5-day market history...",
                file=sys.stderr,
            )
            history_prices = self._esi.get_market_history(no_orders)
            for type_id in no_orders:
                if type_id in history_prices:
                    prices[type_id] = (history_prices[type_id], "history")
                else:
                    prices[type_id] = (0.0, "none")

        return prices
