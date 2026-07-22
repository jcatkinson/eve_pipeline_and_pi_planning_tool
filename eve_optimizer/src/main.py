"""
src/main.py
~~~~~~~~~~~
CLI entrypoint for the EVE PI Profit Engine.

Usage:
    python -m src.main [OPTIONS]

Options:
    --planet-type TEXT   Filter by planet type (barren, temperate, lava, etc.)
                         Can be repeated. Omit for all planet types.
    --tier INT           Minimum output tier to evaluate (3 or 4). Default: 3.
    --top INT            Show only the top N results by profit delta. Default: all.
    --json               Emit results as JSON to stdout.
    --no-auth            Skip ESI auth and use mock prices (for offline testing).

Architecture note:
    FastAPI router stubs are imported here but not started. When the API
    server is activated in a future phase, `uvicorn src.api:app` will be
    the entry point and this CLI will remain for direct terminal use.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.config import (
    CHARACTER_ID,
    DB_PATH,
    PLANET_TYPES,
    TRANSPORT_RISK_FACTOR,
)


# ---------------------------------------------------------------------------
# Mock ESI client for --no-auth / offline testing
# ---------------------------------------------------------------------------

class _MockESIClient:
    """Returns placeholder prices so the engine can run without ESI credentials."""

    _MOCK_PRICES: dict[int, float] = {
        # P1
        2267: 120.0, 2268: 130.0, 2306: 110.0, 2307: 115.0,
        2309: 105.0, 2310: 108.0, 2311: 102.0, 2312: 98.0,
        2313: 112.0, 2315: 118.0, 2316: 125.0, 2317: 107.0,
        2318: 122.0, 2319: 116.0, 2321: 119.0, 2322: 114.0,
        9828: 95.0,
        # P2
        44: 8500.0, 2329: 9200.0, 2327: 8800.0, 2332: 7900.0,
        9830: 9100.0, 9832: 8600.0, 2463: 9300.0, 2344: 7500.0,
        2346: 8200.0, 2348: 8700.0, 9836: 9500.0, 9838: 7800.0,
        9840: 8300.0, 9842: 8100.0, 2353: 8400.0, 2354: 8900.0,
        # P3
        2867: 85000.0, 2868: 92000.0, 2869: 78000.0, 2870: 88000.0,
        2871: 95000.0, 2872: 82000.0, 2875: 91000.0, 2876: 87000.0,
        2877: 93000.0, 2878: 80000.0, 2879: 89000.0, 2880: 96000.0,
        2881: 84000.0, 2882: 90000.0,
        # P4
        2886: 1_200_000.0, 2887: 1_150_000.0, 2888: 1_300_000.0,
        2889: 1_100_000.0, 2890: 1_250_000.0, 2891: 1_180_000.0,
        2892: 1_220_000.0, 2893: 1_270_000.0,
    }

    def get_market_orders(self, type_ids, order_type="sell", region_id=None):
        result = {}
        for tid in type_ids:
            price = self._MOCK_PRICES.get(tid, 0.0)
            result[tid] = [{"price": price, "is_buy_order": False}] if price else []
        return result

    def get_accounting_level(self) -> int:
        return 0

    def get_broker_relations_level(self) -> int:
        return 0


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _print_table(results, verbose: bool = False) -> None:
    from src.utils.helpers import format_isk

    print()
    print("=" * 110)
    print(
        f"  {'TIER':<6}{'PRODUCT':<38}{'SELL RAW (net)':<22}"
        f"{'PROCESS (net)':<22}{'DELTA':<22}{'RECOMMENDATION'}"
    )
    print("=" * 110)
    for r in results:
        delta_str = f"+{format_isk(r.delta_isk)}" if r.delta_isk >= 0 else format_isk(r.delta_isk)
        rec_str = "✔ PROCESS" if r.recommendation == "PROCESS & MANUFACTURE" else "  SELL RAW"
        print(
            f"  P{r.output_tier:<5}{r.output_name:<38}"
            f"{format_isk(r.sell_raw_net_isk):<22}"
            f"{format_isk(r.process_net_isk):<22}"
            f"{delta_str:<22}"
            f"{rec_str}"
        )
    print("=" * 110)
    print(
        f"\n  Showing {len(results)} chain(s).  "
        f"Tax={results[0].applied_sales_tax:.2%}  "
        f"BrokerFee={results[0].applied_broker_fee:.2%}  "
        f"TransportRisk={results[0].transport_risk_factor:.2%}"
        if results else ""
    )
    print()


def _to_json(results) -> str:
    from dataclasses import asdict
    return json.dumps([asdict(r) for r in results], indent=2, default=str)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.main",
        description="EVE PI Profit Engine — Jita market sell vs. manufacture decision tool",
    )
    parser.add_argument(
        "--planet-type",
        dest="planet_types",
        action="append",
        metavar="TYPE",
        choices=PLANET_TYPES,
        help="Filter chains by factory planet type (repeatable). Default: all.",
    )
    parser.add_argument(
        "--tier",
        type=int,
        choices=[3, 4],
        default=3,
        help="Minimum output tier to evaluate (default: 3).",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=None,
        metavar="N",
        help="Show only the top N results by profit delta.",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Output results as JSON.",
    )
    parser.add_argument(
        "--no-auth",
        dest="no_auth",
        action="store_true",
        help="Skip ESI OAuth2 authentication and use mock market prices (offline mode).",
    )
    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Status output — always to stderr so --json stdout stays clean
    def _log(msg: str) -> None:
        print(msg, file=sys.stderr)

    # --- Ensure database exists ---
    if not DB_PATH.exists():
        _log("[main] PI blueprint database not found. Building now...")
        from src.databaseCreator import build_database
        build_database()

    # --- ESI client setup ---
    if args.no_auth:
        _log("[main] Running in offline mode with mock prices.")
        esi = _MockESIClient()
        accounting = 0
        broker = 0
    else:
        if not CHARACTER_ID:
            _log("[main] ERROR: CHARACTER_ID not set in .env. Use --no-auth for offline mode.")
            return 1

        from src.eve_server import ESIClient
        esi = ESIClient()
        esi.authenticate()
        accounting = esi.get_accounting_level()
        broker = esi.get_broker_relations_level()
        _log(f"[main] Skills — Accounting: {accounting}, Broker Relations: {broker}")

    # --- Run profit engine ---
    from src.profit_engine import ProfitEngine

    engine = ProfitEngine(
        esi_client=esi,
        accounting_level=accounting,
        broker_relations_level=broker,
        planet_type_filter=args.planet_types,
        transport_risk_factor=TRANSPORT_RISK_FACTOR,
    )

    results = engine.run(min_tier=args.tier)

    if args.top:
        results = results[: args.top]

    if not results:
        print("[main] No chains matched the given filters.")
        return 0

    if args.as_json:
        print(_to_json(results))
    else:
        _print_table(results)

    return 0


if __name__ == "__main__":
    sys.exit(main())
