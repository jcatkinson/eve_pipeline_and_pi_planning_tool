"""
tests/test_main.py
~~~~~~~~~~~~~~~~~~
Unit and integration tests for the EVE PI Profit Engine.
Run with:  pytest tests/ -v

All ESI calls are mocked — no network access required.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.utils.helpers import (
    effective_broker_fee,
    effective_sales_tax,
    format_isk,
    isk_per_m3,
    net_sell_value,
    total_volume,
)


# ===========================================================================
# helpers.py — pure math
# ===========================================================================

class TestFormatISK:
    def test_billions(self):
        assert format_isk(1_500_000_000) == "1.50B ISK"

    def test_millions(self):
        assert format_isk(4_250_000) == "4.25M ISK"

    def test_thousands(self):
        assert format_isk(12_500) == "12.50K ISK"

    def test_units(self):
        assert format_isk(999) == "999.00 ISK"

    def test_negative(self):
        assert format_isk(-2_000_000) == "-2.00M ISK"


class TestEffectiveSalesTax:
    """
    Base rate 8%.  Accounting L5 should reduce it by 11% * 5 = 55%:
    0.08 * (1 - 0.55) = 0.08 * 0.45 = 0.036
    """
    def test_level_0(self):
        assert effective_sales_tax(0) == pytest.approx(0.08)

    def test_level_5(self):
        assert effective_sales_tax(5) == pytest.approx(0.08 * 0.45)

    def test_level_3(self):
        assert effective_sales_tax(3) == pytest.approx(0.08 * (1 - 0.33))


class TestEffectiveBrokerFee:
    """
    Base rate 3%.  Broker Relations L5: 0.03 * (1 - 0.15) = 0.03 * 0.85 = 0.0255
    """
    def test_level_0(self):
        assert effective_broker_fee(0) == pytest.approx(0.03)

    def test_level_5(self):
        assert effective_broker_fee(5) == pytest.approx(0.03 * 0.85)


class TestNetSellValue:
    def test_basic_no_risk(self):
        # 100 units at 1000 ISK, 8% tax, 3% broker, no transport risk, no poco
        # gross = 100_000; deductions = 11% = 11_000; net = 89_000
        val = net_sell_value(1000.0, 100, 0.08, 0.03, 0.0)
        assert val == pytest.approx(89_000.0)

    def test_with_transport_risk(self):
        # Additional 5% risk → total deductions 16%
        val = net_sell_value(1000.0, 100, 0.08, 0.03, 0.05)
        assert val == pytest.approx(84_000.0)

    def test_zero_price(self):
        assert net_sell_value(0.0, 100, 0.08, 0.03, 0.05) == 0.0

    def test_poco_tax_reduces_net(self):
        # 5% poco tax on top of 8% tax + 3% broker + 0% transport
        # total deduction = 16%, net = 84_000
        val = net_sell_value(1000.0, 100, 0.08, 0.03, 0.0, poco_tax_rate=0.05)
        assert val == pytest.approx(84_000.0)

    def test_poco_tax_default_zero(self):
        # Default poco_tax_rate=0.0 — should match original behaviour
        val_default = net_sell_value(1000.0, 100, 0.08, 0.03, 0.05)
        val_explicit = net_sell_value(1000.0, 100, 0.08, 0.03, 0.05, poco_tax_rate=0.0)
        assert val_default == pytest.approx(val_explicit)


class TestVolumeHelpers:
    def test_total_volume(self):
        assert total_volume(0.38, 100) == pytest.approx(38.0)

    def test_isk_per_m3(self):
        assert isk_per_m3(38_000.0, 38.0) == pytest.approx(1000.0)

    def test_isk_per_m3_zero_volume(self):
        assert isk_per_m3(1000.0, 0.0) == 0.0


# ===========================================================================
# databaseCreator.py (now src.core.database via shim)
# ===========================================================================

class TestDatabaseCreator:
    def test_build_and_query(self, tmp_path):
        from src.core.database import build_database

        db = tmp_path / "test_pi.db"
        build_database(db_path=db)

        conn = sqlite3.connect(db)
        count_items = conn.execute("SELECT COUNT(*) FROM pi_items").fetchone()[0]
        count_bps   = conn.execute("SELECT COUNT(*) FROM pi_blueprints").fetchone()[0]
        count_mats  = conn.execute("SELECT COUNT(*) FROM pi_materials").fetchone()[0]
        conn.close()

        assert count_items > 0,  "pi_items should be populated"
        assert count_bps > 0,    "pi_blueprints should be populated"
        assert count_mats > 0,   "pi_materials should be populated"

    def test_tiers_present(self, tmp_path):
        from src.core.database import build_database

        db = tmp_path / "test_pi.db"
        build_database(db_path=db)

        conn = sqlite3.connect(db)
        tiers = {r[0] for r in conn.execute("SELECT DISTINCT tier FROM pi_items").fetchall()}
        conn.close()

        assert 1 in tiers, "P1 items should be in database"
        assert 2 in tiers, "P2 items should be in database"
        assert 3 in tiers, "P3 items should be in database"
        assert 4 in tiers, "P4 items should be in database"

    def test_shim_import_still_works(self, tmp_path):
        """Old import path src.databaseCreator should still resolve via shim."""
        from src.databaseCreator import build_database as build_shim
        from src.core.database import build_database as build_core
        assert build_shim is build_core


# ===========================================================================
# profit_engine.py (now src.core.profit_engine via shim)
# ===========================================================================

class TestProfitEngine:
    """Tests for the ProfitEngine using a real temp database and a mock ESI client."""

    @pytest.fixture
    def db_path(self, tmp_path) -> Path:
        from src.core.database import build_database
        db = tmp_path / "engine_test.db"
        build_database(db_path=db)
        return db

    @pytest.fixture
    def mock_esi(self):
        """Mock ESI that returns static prices for all PI items."""
        from src.interfaces.cli import _MockESIClient
        return _MockESIClient()

    def test_run_returns_results(self, db_path, mock_esi):
        from src.core.profit_engine import ProfitEngine
        engine = ProfitEngine(esi_client=mock_esi, db_path=db_path)
        results = engine.run(min_tier=3)
        assert len(results) > 0

    def test_results_sorted_by_delta(self, db_path, mock_esi):
        from src.core.profit_engine import ProfitEngine
        engine = ProfitEngine(esi_client=mock_esi, db_path=db_path)
        results = engine.run(min_tier=3)
        deltas = [r.delta_isk for r in results]
        assert deltas == sorted(deltas, reverse=True)

    def test_recommendation_matches_delta(self, db_path, mock_esi):
        from src.core.profit_engine import ProfitEngine
        engine = ProfitEngine(esi_client=mock_esi, db_path=db_path)
        results = engine.run(min_tier=3)
        for r in results:
            if r.delta_isk > 0:
                assert r.recommendation == "PROCESS & MANUFACTURE"
            else:
                assert r.recommendation == "SELL RAW"

    def test_accounting_skill_reduces_tax(self, db_path, mock_esi):
        from src.core.profit_engine import ProfitEngine
        engine_l0 = ProfitEngine(esi_client=mock_esi, accounting_level=0, db_path=db_path)
        engine_l5 = ProfitEngine(esi_client=mock_esi, accounting_level=5, db_path=db_path)
        assert engine_l5.sales_tax_rate < engine_l0.sales_tax_rate

    def test_broker_relations_reduces_fee(self, db_path, mock_esi):
        from src.core.profit_engine import ProfitEngine
        engine_l0 = ProfitEngine(esi_client=mock_esi, broker_relations_level=0, db_path=db_path)
        engine_l5 = ProfitEngine(esi_client=mock_esi, broker_relations_level=5, db_path=db_path)
        assert engine_l5.broker_fee_rate < engine_l0.broker_fee_rate

    def test_planet_type_filter(self, db_path, mock_esi):
        from src.core.profit_engine import ProfitEngine
        engine = ProfitEngine(
            esi_client=mock_esi,
            planet_type_filter=["barren"],
            db_path=db_path,
        )
        results = engine.run(min_tier=3)
        # All results should involve barren-compatible chains or "any"
        for r in results:
            assert "barren" in r.planet_types or r.planet_types == ["any"]

    def test_p4_only(self, db_path, mock_esi):
        from src.core.profit_engine import ProfitEngine
        engine = ProfitEngine(esi_client=mock_esi, db_path=db_path)
        results = engine.run(min_tier=4)
        assert all(r.output_tier == 4 for r in results)

    def test_transport_risk_reduces_net(self, db_path, mock_esi):
        from src.core.profit_engine import ProfitEngine
        engine_no_risk   = ProfitEngine(esi_client=mock_esi, transport_risk_factor=0.0, db_path=db_path)
        engine_with_risk = ProfitEngine(esi_client=mock_esi, transport_risk_factor=0.10, db_path=db_path)
        r0 = engine_no_risk.run(min_tier=3)
        r1 = engine_with_risk.run(min_tier=3)
        # Both sets should have results; process net should be lower with risk
        assert r0[0].process_net_isk > r1[0].process_net_isk

    def test_shim_import_still_works(self, db_path, mock_esi):
        """Old import path src.profit_engine should still resolve via shim."""
        from src.profit_engine import ProfitEngine as PE_shim
        from src.core.profit_engine import ProfitEngine as PE_core
        assert PE_shim is PE_core


# ===========================================================================
# POCO Tax
# ===========================================================================

class TestPOCOTax:
    @pytest.fixture
    def db_path(self, tmp_path) -> Path:
        from src.core.database import build_database
        db = tmp_path / "poco_test.db"
        build_database(db_path=db)
        return db

    @pytest.fixture
    def mock_esi(self):
        from src.interfaces.cli import _MockESIClient
        return _MockESIClient()

    def test_poco_tax_default_is_5pct(self, db_path, mock_esi):
        """ProfitEngine should default to 5% POCO tax."""
        from src.core.profit_engine import ProfitEngine
        engine = ProfitEngine(esi_client=mock_esi, db_path=db_path)
        assert engine.poco_tax == pytest.approx(0.05)

    def test_poco_tax_reduces_net_isk(self, db_path, mock_esi):
        """Higher POCO tax should reduce process_net_isk compared to zero tax."""
        from src.core.profit_engine import ProfitEngine
        engine_zero = ProfitEngine(esi_client=mock_esi, poco_tax=0.0, db_path=db_path)
        engine_high = ProfitEngine(esi_client=mock_esi, poco_tax=0.10, db_path=db_path)
        r_zero = engine_zero.run(min_tier=3)
        r_high = engine_high.run(min_tier=3)
        # Match by output name for fair comparison
        zero_map = {r.output_name: r for r in r_zero}
        high_map = {r.output_name: r for r in r_high}
        for name in zero_map:
            assert zero_map[name].process_net_isk >= high_map[name].process_net_isk

    def test_poco_tax_stored_on_result(self, db_path, mock_esi):
        """applied_poco_tax field should reflect the configured rate."""
        from src.core.profit_engine import ProfitEngine
        engine = ProfitEngine(esi_client=mock_esi, poco_tax=0.07, db_path=db_path)
        results = engine.run(min_tier=3)
        for r in results:
            assert r.applied_poco_tax == pytest.approx(0.07)

    def test_poco_tax_in_json_output(self, tmp_path, capsys):
        """--json output should include applied_poco_tax field."""
        from src.interfaces.cli import main

        with patch("src.interfaces.cli.DB_PATH", tmp_path / "poco_json.db"), \
             patch("src.core.database.DB_PATH", tmp_path / "poco_json.db"), \
             patch("src.core.profit_engine.DB_PATH", tmp_path / "poco_json.db"):
            exit_code = main(["--no-auth", "--json", "--tier", "3", "--poco-tax", "0.07"])

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert exit_code == 0
        assert all("applied_poco_tax" in r for r in data)
        assert all(abs(r["applied_poco_tax"] - 0.07) < 1e-9 for r in data)

    def test_poco_tax_shown_in_footer(self, tmp_path, capsys):
        """Table footer should display POCOTax= value."""
        from src.interfaces.cli import main

        with patch("src.interfaces.cli.DB_PATH", tmp_path / "poco_footer.db"), \
             patch("src.core.database.DB_PATH", tmp_path / "poco_footer.db"), \
             patch("src.core.profit_engine.DB_PATH", tmp_path / "poco_footer.db"):
            exit_code = main(["--no-auth", "--tier", "3", "--poco-tax", "0.10"])

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "POCOTax=10.00%" in captured.out


# ===========================================================================
# ISK/m³ Hauling Density
# ===========================================================================

class TestHaulingDensity:
    @pytest.fixture
    def db_path(self, tmp_path) -> Path:
        from src.core.database import build_database
        db = tmp_path / "density_test.db"
        build_database(db_path=db)
        return db

    @pytest.fixture
    def mock_esi(self):
        from src.interfaces.cli import _MockESIClient
        return _MockESIClient()

    def test_input_density_nonzero_with_prices(self, db_path, mock_esi):
        """Chains with valid input prices should have input_isk_per_m3 > 0."""
        from src.core.profit_engine import ProfitEngine
        engine = ProfitEngine(esi_client=mock_esi, db_path=db_path, poco_tax=0.0)
        results = engine.run(min_tier=3)
        # At least some chains have non-zero sell_raw so input density > 0
        assert any(r.input_isk_per_m3 > 0 for r in results)

    def test_output_density_nonzero_with_prices(self, db_path, mock_esi):
        """Chains with valid output prices should have output_isk_per_m3 > 0."""
        from src.core.profit_engine import ProfitEngine
        engine = ProfitEngine(esi_client=mock_esi, db_path=db_path, poco_tax=0.0)
        results = engine.run(min_tier=3)
        assert any(r.output_isk_per_m3 > 0 for r in results)

    def test_density_zero_when_price_zero(self, tmp_path):
        """Zero prices should produce zero density values."""
        from src.core.profit_engine import ProfitEngine
        from src.core.database import build_database

        db = tmp_path / "zero_density.db"
        build_database(db_path=db)

        class _ZeroPriceESI:
            def get_market_orders(self, type_ids, order_type="sell", region_id=None):
                return {tid: [] for tid in type_ids}
            def get_market_history(self, type_ids, region_id=None, days=5):
                return {}

        engine = ProfitEngine(esi_client=_ZeroPriceESI(), db_path=db, poco_tax=0.0)
        results = engine.run(min_tier=3)
        for r in results:
            assert r.input_isk_per_m3 == 0.0
            assert r.output_isk_per_m3 == 0.0

    def test_density_in_json_output(self, tmp_path, capsys):
        """JSON output should contain input_isk_per_m3 and output_isk_per_m3 fields."""
        from src.interfaces.cli import main

        with patch("src.interfaces.cli.DB_PATH", tmp_path / "density_json.db"), \
             patch("src.core.database.DB_PATH", tmp_path / "density_json.db"), \
             patch("src.core.profit_engine.DB_PATH", tmp_path / "density_json.db"):
            exit_code = main(["--no-auth", "--json", "--tier", "3", "--top", "3"])

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert exit_code == 0
        assert all("input_isk_per_m3" in r for r in data)
        assert all("output_isk_per_m3" in r for r in data)

    def test_density_columns_in_table(self, tmp_path, capsys):
        """Table output should contain ISK/m³ column headers."""
        from src.interfaces.cli import main

        with patch("src.interfaces.cli.DB_PATH", tmp_path / "density_table.db"), \
             patch("src.core.database.DB_PATH", tmp_path / "density_table.db"), \
             patch("src.core.profit_engine.DB_PATH", tmp_path / "density_table.db"):
            exit_code = main(["--no-auth", "--tier", "3", "--top", "3"])

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "ISK/m³" in captured.out


# ===========================================================================
# main.py CLI integration (uses new src.interfaces.cli paths)
# ===========================================================================

class TestCLI:
    def test_no_auth_runs(self, tmp_path, capsys):
        """--no-auth should complete without errors using mock prices."""
        from src.interfaces.cli import main

        with patch("src.interfaces.cli.DB_PATH", tmp_path / "cli_test.db"), \
             patch("src.core.database.DB_PATH", tmp_path / "cli_test.db"), \
             patch("src.core.profit_engine.DB_PATH", tmp_path / "cli_test.db"):
            exit_code = main(["--no-auth", "--tier", "3"])

        assert exit_code == 0

    def test_json_output(self, tmp_path, capsys):
        """--json flag should emit valid JSON to stdout."""
        from src.interfaces.cli import main

        with patch("src.interfaces.cli.DB_PATH", tmp_path / "json_test.db"), \
             patch("src.core.database.DB_PATH", tmp_path / "json_test.db"), \
             patch("src.core.profit_engine.DB_PATH", tmp_path / "json_test.db"):
            exit_code = main(["--no-auth", "--json", "--tier", "3"])

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, list)
        assert exit_code == 0

    def test_top_flag(self, tmp_path, capsys):
        """--top 3 should return at most 3 results."""
        from src.interfaces.cli import main

        with patch("src.interfaces.cli.DB_PATH", tmp_path / "top_test.db"), \
             patch("src.core.database.DB_PATH", tmp_path / "top_test.db"), \
             patch("src.core.profit_engine.DB_PATH", tmp_path / "top_test.db"):
            exit_code = main(["--no-auth", "--json", "--top", "3"])

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert len(data) <= 3
        assert exit_code == 0

    def test_tier_1_returns_p1_chains(self, tmp_path, capsys):
        """--tier 1 should return P1 (and higher) output chains."""
        from src.interfaces.cli import main

        with patch("src.interfaces.cli.DB_PATH", tmp_path / "tier1_test.db"), \
             patch("src.core.database.DB_PATH", tmp_path / "tier1_test.db"), \
             patch("src.core.profit_engine.DB_PATH", tmp_path / "tier1_test.db"):
            exit_code = main(["--no-auth", "--json", "--tier", "1"])

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        tiers = {r["output_tier"] for r in data}
        assert exit_code == 0
        assert 1 in tiers, "P1 chains should appear with --tier 1"

    def test_tier_2_returns_p2_and_above(self, tmp_path, capsys):
        """--tier 2 should return P2, P3, and P4 chains but not P1."""
        from src.interfaces.cli import main

        with patch("src.interfaces.cli.DB_PATH", tmp_path / "tier2_test.db"), \
             patch("src.core.database.DB_PATH", tmp_path / "tier2_test.db"), \
             patch("src.core.profit_engine.DB_PATH", tmp_path / "tier2_test.db"):
            exit_code = main(["--no-auth", "--json", "--tier", "2"])

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        tiers = {r["output_tier"] for r in data}
        assert exit_code == 0
        assert 1 not in tiers, "P1 chains should not appear with --tier 2"
        assert 2 in tiers, "P2 chains should appear with --tier 2"

    def test_zero_price_chain_still_appears(self, tmp_path):
        """A chain with a zero-priced input should still be included in results."""
        from src.core.profit_engine import ProfitEngine
        from src.core.database import build_database

        db = tmp_path / "zero_price.db"
        build_database(db_path=db)

        class _ZeroPriceESI:
            def get_market_orders(self, type_ids, order_type="sell", region_id=None):
                return {tid: [] for tid in type_ids}
            def get_market_history(self, type_ids, region_id=None, days=5):
                return {}

        engine = ProfitEngine(esi_client=_ZeroPriceESI(), db_path=db)
        results = engine.run(min_tier=3)
        assert len(results) > 0, "Chains should still appear even when all prices are 0"
        for r in results:
            assert r.sell_raw_net_isk == 0.0
            assert r.process_net_isk == 0.0


    def test_history_fallback_sets_price_source(self, tmp_path):
        """When live orders return empty but history exists, price_source should be 'history'."""
        from src.core.profit_engine import ProfitEngine
        from src.core.database import build_database

        db = tmp_path / "history_fallback.db"
        build_database(db_path=db)

        class _HistoryESI:
            """No live orders; history returns a fixed average price for every type."""
            def get_market_orders(self, type_ids, order_type="sell", region_id=None):
                return {tid: [] for tid in type_ids}
            def get_market_history(self, type_ids, region_id=None, days=5):
                return {tid: 50_000.0 for tid in type_ids}

        engine = ProfitEngine(esi_client=_HistoryESI(), db_path=db)
        results = engine.run(min_tier=3)
        assert len(results) > 0
        for r in results:
            # All items should be priced from history, not live
            assert all(inp.price_source == "history" for inp in r.inputs)
            assert r.output_price_source == "history"
            # And the prices should be non-zero (from history)
            assert all(inp.unit_price > 0.0 for inp in r.inputs)
            assert r.output_unit_price > 0.0


    def test_warning_marker_in_table_output(self, tmp_path, capsys):
        """Table output should include the ⚠ legend when any item has no market data."""
        from src.interfaces.cli import main

        with patch("src.interfaces.cli.DB_PATH", tmp_path / "warn_test.db"), \
             patch("src.core.database.DB_PATH", tmp_path / "warn_test.db"), \
             patch("src.core.profit_engine.DB_PATH", tmp_path / "warn_test.db"):
            exit_code = main(["--no-auth", "--tier", "1"])

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "⚠" in captured.out, "Warning marker should appear when price data is missing"

    def test_verbose_shows_input_breakdown(self, tmp_path, capsys):
        """--verbose should print indented input material rows under each chain."""
        from src.interfaces.cli import main

        with patch("src.interfaces.cli.DB_PATH", tmp_path / "verbose_test.db"), \
             patch("src.core.database.DB_PATH", tmp_path / "verbose_test.db"), \
             patch("src.core.profit_engine.DB_PATH", tmp_path / "verbose_test.db"):
            exit_code = main(["--no-auth", "--tier", "3", "--top", "2", "--verbose"])

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "└" in captured.out, "Verbose mode should show └ input material rows"
        assert "ISK" in captured.out, "Input rows should include ISK price"

    def test_verbose_flags_zero_price_inputs(self, tmp_path, capsys):
        """--verbose should show '⚠ no market data' next to inputs with no price."""
        from src.interfaces.cli import main

        with patch("src.interfaces.cli.DB_PATH", tmp_path / "verbose_warn_test.db"), \
             patch("src.core.database.DB_PATH", tmp_path / "verbose_warn_test.db"), \
             patch("src.core.profit_engine.DB_PATH", tmp_path / "verbose_warn_test.db"):
            exit_code = main(["--no-auth", "--tier", "1", "--verbose"])

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "no market data" in captured.out, \
            "Verbose mode should flag inputs with missing market data"


# ===========================================================================
# UserService
# ===========================================================================

class TestUserService:
    """Tests for UserService using a mocked Supabase admin client."""

    def _make_mock_db(self, rows: dict | None = None):
        """Return a MagicMock Supabase client pre-configured with fluent chain."""
        from unittest.mock import MagicMock
        db = MagicMock()

        # Default empty responses unless rows provided
        empty = MagicMock()
        empty.data = []

        def _chain(*args, **kwargs):
            return MagicMock(**{"execute.return_value": empty,
                                "select.return_value": MagicMock(**{"execute.return_value": empty,
                                    "eq.return_value": MagicMock(**{"execute.return_value": empty,
                                        "order.return_value": MagicMock(**{"execute.return_value": empty,
                                            "limit.return_value": MagicMock(**{"execute.return_value": empty})}),
                                        "gt.return_value": MagicMock(**{"execute.return_value": empty}),
                                        "lt.return_value": MagicMock(**{"execute.return_value": empty}),
                                    })
                                })
                               })
        db.table.return_value = _chain()
        return db

    def test_character_limit_error_message(self):
        from src.core.user_service import CharacterLimitError
        err = CharacterLimitError(current=2, limit=2, tier="free")
        assert "2/2" in str(err)
        assert "free" in str(err)

    def test_subscription_days_remaining(self):
        from src.core.user_service import Subscription
        from datetime import datetime, timedelta, timezone
        future = (datetime.now(timezone.utc) + timedelta(days=45)).isoformat()
        sub = Subscription(
            id="x", user_id="y", tier="premium",
            starts_at="2025-01-01T00:00:00+00:00",
            expires_at=future, is_active=True, renewed_count=0,
        )
        assert 44 <= sub.days_remaining <= 45

    def test_subscription_days_remaining_expired(self):
        from src.core.user_service import Subscription
        past = "2020-01-01T00:00:00+00:00"
        sub = Subscription(
            id="x", user_id="y", tier="premium",
            starts_at="2019-01-01T00:00:00+00:00",
            expires_at=past, is_active=False, renewed_count=0,
        )
        assert sub.days_remaining == 0

    def test_tier_char_limits_config(self):
        from src.config import TIER_CHAR_LIMITS
        assert TIER_CHAR_LIMITS["free"] == 2
        assert TIER_CHAR_LIMITS["premium"] == 10
        assert TIER_CHAR_LIMITS["corporate"] is None

    def test_get_or_create_user_new(self):
        """get_or_create_user creates both a user row and primary character row."""
        from unittest.mock import MagicMock, call, patch
        from src.core.user_service import UserService

        user_row = {
            "id": "uuid-1", "character_id": 12345,
            "character_name": "Test Char", "tier": "free",
            "tier_char_limit": 2, "created_at": "2025-01-01T00:00:00+00:00",
        }
        db = MagicMock()
        # First select returns empty (user not found), insert returns new user
        select_result = MagicMock()
        select_result.data = []
        insert_result = MagicMock()
        insert_result.data = [user_row]

        table_mock = MagicMock()
        table_mock.select.return_value.eq.return_value.execute.return_value = select_result
        table_mock.insert.return_value.execute.return_value = insert_result
        db.table.return_value = table_mock

        svc = UserService(db)
        user = svc.get_or_create_user(12345, "Test Char")

        assert user.id == "uuid-1"
        assert user.character_id == 12345
        assert user.tier == "free"

    def test_add_character_at_limit_raises(self):
        """add_character raises CharacterLimitError when at free tier limit."""
        from unittest.mock import MagicMock
        from src.core.user_service import UserService, CharacterLimitError, User, Character

        user = User(
            id="uuid-1", character_id=11111, character_name="Main",
            tier="free", tier_char_limit=2,
            created_at="2025-01-01T00:00:00+00:00",
        )
        char1 = Character(
            id="c1", user_id="uuid-1", character_id=11111, character_name="Main",
            is_primary=True, access_token=None, refresh_token=None, token_expiry=None,
            accounting_level=0, broker_level=0, last_synced=None,
            added_at="2025-01-01T00:00:00+00:00",
        )
        char2 = Character(
            id="c2", user_id="uuid-1", character_id=22222, character_name="Alt",
            is_primary=False, access_token=None, refresh_token=None, token_expiry=None,
            accounting_level=0, broker_level=0, last_synced=None,
            added_at="2025-01-01T00:00:00+00:00",
        )

        db = MagicMock()
        svc = UserService(db)

        # Patch the methods called by add_character
        svc.get_user_by_id = MagicMock(return_value=user)
        svc.get_characters = MagicMock(return_value=[char1, char2])

        with pytest.raises(CharacterLimitError) as exc_info:
            svc.add_character("uuid-1", 33333, "New Alt")

        assert exc_info.value.limit == 2
        assert exc_info.value.current == 2

    def test_remove_primary_raises(self):
        """remove_character raises ValueError for the primary character."""
        from unittest.mock import MagicMock
        from src.core.user_service import UserService, Character

        primary = Character(
            id="c1", user_id="uuid-1", character_id=11111, character_name="Main",
            is_primary=True, access_token=None, refresh_token=None, token_expiry=None,
            accounting_level=0, broker_level=0, last_synced=None,
            added_at="2025-01-01T00:00:00+00:00",
        )
        db = MagicMock()
        svc = UserService(db)
        svc.get_character = MagicMock(return_value=primary)

        with pytest.raises(ValueError, match="primary"):
            svc.remove_character("uuid-1", 11111)


# ===========================================================================
# CorpWalletClient
# ===========================================================================

class TestCorpWalletClient:

    def test_get_journal_returns_entries(self):
        """get_journal collects entries across pages and stops early on short page."""
        from unittest.mock import MagicMock, patch
        from src.core.esi_client import CorpWalletClient

        entries_p1 = [{"id": i, "ref_type": "player_donation", "amount": 500_000_000,
                        "first_party_id": 99} for i in range(50)]
        entries_p2 = [{"id": i + 50, "ref_type": "player_donation", "amount": 500_000_000,
                        "first_party_id": 99} for i in range(10)]  # short page → stop

        mock_resp_p1 = MagicMock()
        mock_resp_p1.status_code = 200
        mock_resp_p1.json.return_value = entries_p1

        mock_resp_p2 = MagicMock()
        mock_resp_p2.status_code = 200
        mock_resp_p2.json.return_value = entries_p2

        client = CorpWalletClient(
            access_token="token",
            refresh_token="refresh",
            token_expiry=9999999999.0,
        )
        client._session = MagicMock()
        client._session.get.side_effect = [mock_resp_p1, mock_resp_p2]

        entries = client.get_journal(corp_id=12345, division=1, pages=3)
        assert len(entries) == 60  # 50 + 10

    def test_get_journal_raises_on_403(self):
        """get_journal raises PermissionError on a 403 response."""
        from unittest.mock import MagicMock
        from src.core.esi_client import CorpWalletClient

        mock_resp = MagicMock()
        mock_resp.status_code = 403

        client = CorpWalletClient(
            access_token="token",
            refresh_token="refresh",
            token_expiry=9999999999.0,
        )
        client._session = MagicMock()
        client._session.get.return_value = mock_resp

        with pytest.raises(PermissionError):
            client.get_journal(corp_id=12345)


# ===========================================================================
# PaymentVerifier
# ===========================================================================

class TestPaymentVerifier:

    def _make_journal_entry(
        self,
        journal_id: int,
        character_id: int,
        amount: int,
        ref_type: str = "player_donation",
    ) -> dict:
        return {
            "id":              journal_id,
            "ref_type":        ref_type,
            "first_party_id":  character_id,
            "first_party_name": "Test Char",
            "amount":          float(amount),
        }

    def test_granted_premium(self):
        """Matching 500M donation grants premium."""
        from unittest.mock import MagicMock
        from src.core.payment_verifier import PaymentVerifier, VerificationResult
        from src.config import CORP_PAYMENT_AMOUNT_PREMIUM

        wallet = MagicMock()
        wallet.get_journal.return_value = [
            self._make_journal_entry(1001, 12345, CORP_PAYMENT_AMOUNT_PREMIUM)
        ]

        svc = MagicMock()
        svc.get_active_subscription.return_value = None

        dup_result = MagicMock()
        dup_result.data = []
        svc._db.table.return_value.select.return_value.eq.return_value.execute.return_value = dup_result

        sub_result = MagicMock()
        svc.grant_subscription.return_value = sub_result

        verifier = PaymentVerifier(corp_wallet=wallet, user_service=svc)
        result = verifier.check(user_id="uuid-1", character_id=12345)

        assert result == VerificationResult.GRANTED
        svc.grant_subscription.assert_called_once()
        call_kwargs = svc.grant_subscription.call_args
        assert call_kwargs.kwargs["tier"] == "premium"

    def test_granted_corporate(self):
        """Matching 1B donation grants corporate."""
        from unittest.mock import MagicMock
        from src.core.payment_verifier import PaymentVerifier, VerificationResult
        from src.config import CORP_PAYMENT_AMOUNT_CORPORATE

        wallet = MagicMock()
        wallet.get_journal.return_value = [
            self._make_journal_entry(2001, 12345, CORP_PAYMENT_AMOUNT_CORPORATE)
        ]

        svc = MagicMock()
        svc.get_active_subscription.return_value = None

        dup_result = MagicMock()
        dup_result.data = []
        svc._db.table.return_value.select.return_value.eq.return_value.execute.return_value = dup_result

        verifier = PaymentVerifier(corp_wallet=wallet, user_service=svc)
        result = verifier.check(user_id="uuid-1", character_id=12345)

        assert result == VerificationResult.GRANTED
        call_kwargs = svc.grant_subscription.call_args
        assert call_kwargs.kwargs["tier"] == "corporate"

    def test_not_found_wrong_character(self):
        """Entry from a different character returns NOT_FOUND."""
        from unittest.mock import MagicMock
        from src.core.payment_verifier import PaymentVerifier, VerificationResult
        from src.config import CORP_PAYMENT_AMOUNT_PREMIUM

        wallet = MagicMock()
        wallet.get_journal.return_value = [
            self._make_journal_entry(1001, 99999, CORP_PAYMENT_AMOUNT_PREMIUM)  # wrong char
        ]

        svc = MagicMock()
        svc.get_active_subscription.return_value = None

        verifier = PaymentVerifier(corp_wallet=wallet, user_service=svc)
        result = verifier.check(user_id="uuid-1", character_id=12345)
        assert result == VerificationResult.NOT_FOUND

    def test_not_found_wrong_amount(self):
        """Entry with wrong amount returns NOT_FOUND."""
        from unittest.mock import MagicMock
        from src.core.payment_verifier import PaymentVerifier, VerificationResult

        wallet = MagicMock()
        wallet.get_journal.return_value = [
            self._make_journal_entry(1001, 12345, 100_000_000)  # 100M, not valid
        ]

        svc = MagicMock()
        svc.get_active_subscription.return_value = None

        verifier = PaymentVerifier(corp_wallet=wallet, user_service=svc)
        result = verifier.check(user_id="uuid-1", character_id=12345)
        assert result == VerificationResult.NOT_FOUND

    def test_already_active(self):
        """Returns ALREADY_ACTIVE if user has an active subscription."""
        from unittest.mock import MagicMock
        from src.core.payment_verifier import PaymentVerifier, VerificationResult
        from src.core.user_service import Subscription
        from datetime import datetime, timedelta, timezone

        wallet = MagicMock()
        svc = MagicMock()
        future = (datetime.now(timezone.utc) + timedelta(days=300)).isoformat()
        svc.get_active_subscription.return_value = Subscription(
            id="s1", user_id="uuid-1", tier="premium",
            starts_at="2025-01-01T00:00:00+00:00",
            expires_at=future, is_active=True, renewed_count=0,
        )

        verifier = PaymentVerifier(corp_wallet=wallet, user_service=svc)
        result = verifier.check(user_id="uuid-1", character_id=12345)
        assert result == VerificationResult.ALREADY_ACTIVE
        wallet.get_journal.assert_not_called()  # fast-path, no ESI call

    def test_duplicate_journal_entry(self):
        """Already-processed journal entry returns DUPLICATE."""
        from unittest.mock import MagicMock
        from src.core.payment_verifier import PaymentVerifier, VerificationResult
        from src.config import CORP_PAYMENT_AMOUNT_PREMIUM

        wallet = MagicMock()
        wallet.get_journal.return_value = [
            self._make_journal_entry(1001, 12345, CORP_PAYMENT_AMOUNT_PREMIUM)
        ]

        svc = MagicMock()
        svc.get_active_subscription.return_value = None

        # Simulate existing payment record for this journal ID
        dup_result = MagicMock()
        dup_result.data = [{"id": "existing-payment-uuid"}]
        svc._db.table.return_value.select.return_value.eq.return_value.execute.return_value = dup_result

        verifier = PaymentVerifier(corp_wallet=wallet, user_service=svc)
        result = verifier.check(user_id="uuid-1", character_id=12345)
        assert result == VerificationResult.DUPLICATE
        svc.grant_subscription.assert_not_called()

    def test_non_donation_entry_ignored(self):
        """Journal entries that are not player_donation are ignored."""
        from unittest.mock import MagicMock
        from src.core.payment_verifier import PaymentVerifier, VerificationResult
        from src.config import CORP_PAYMENT_AMOUNT_PREMIUM

        wallet = MagicMock()
        wallet.get_journal.return_value = [
            self._make_journal_entry(1001, 12345, CORP_PAYMENT_AMOUNT_PREMIUM,
                                     ref_type="bounty_prizes")  # wrong type
        ]

        svc = MagicMock()
        svc.get_active_subscription.return_value = None

        verifier = PaymentVerifier(corp_wallet=wallet, user_service=svc)
        result = verifier.check(user_id="uuid-1", character_id=12345)
        assert result == VerificationResult.NOT_FOUND


# ===========================================================================
# JWT helpers
# ===========================================================================

class TestJWTHelpers:

    def _make_mock_token(self, character_id: int, character_name: str) -> str:
        """Create a mock JWT with EVE-style claims (unsigned, for testing decode only)."""
        import base64
        import json

        header  = base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()).rstrip(b"=")
        payload = base64.urlsafe_b64encode(json.dumps({
            "sub":  f"CHARACTER:EVE:{character_id}",
            "name": character_name,
            "exp":  9999999999,
            "scp":  ["esi-skills.read_skills.v1"],
        }).encode()).rstrip(b"=")
        sig = base64.urlsafe_b64encode(b"fakesig").rstrip(b"=")
        return f"{header.decode()}.{payload.decode()}.{sig.decode()}"

    def test_character_id_from_token(self):
        from src.core.esi_client import character_id_from_token
        token = self._make_mock_token(98765, "Test Pilot")
        assert character_id_from_token(token) == 98765

    def test_character_name_from_token(self):
        from src.core.esi_client import character_name_from_token
        token = self._make_mock_token(98765, "Test Pilot")
        assert character_name_from_token(token) == "Test Pilot"

    def test_esi_client_web_mode(self):
        """ESIClient constructed with tokens does not touch .tokens.json."""
        from src.core.esi_client import ESIClient
        client = ESIClient(
            character_id=12345,
            access_token="fake_token",
            refresh_token="fake_refresh",
            token_expiry=9999999999.0,
        )
        assert client._web_mode is True
        assert client._character_id == 12345
        # authenticate() should be a no-op in web mode
        client.authenticate()  # must not raise or attempt disk access

    def test_esi_client_cli_mode(self):
        """ESIClient constructed with no args uses CLI mode."""
        from src.core.esi_client import ESIClient
        client = ESIClient()
        assert client._web_mode is False


# ===========================================================================
# Admin Tier
# ===========================================================================

class TestAdminTier:
    """Tests for the is_admin helper and admin-tier behaviour."""

    def _make_user(self, character_id: int, tier: str = "free") -> "User":
        from src.core.user_service import User
        return User(
            id="uuid-admin",
            character_id=character_id,
            character_name="Admin Char",
            tier=tier,
            tier_char_limit=2,
            created_at="2025-01-01T00:00:00+00:00",
        )

    def test_is_admin_true(self):
        """is_admin returns True when character_id matches ADMIN_CHARACTER_ID."""
        from unittest.mock import patch
        from src.core.user_service import is_admin

        user = self._make_user(character_id=999)
        with patch("src.core.user_service.ADMIN_CHARACTER_ID", 999):
            assert is_admin(user) is True

    def test_is_admin_false_wrong_char(self):
        """is_admin returns False when character_id does not match."""
        from unittest.mock import patch
        from src.core.user_service import is_admin

        user = self._make_user(character_id=12345)
        with patch("src.core.user_service.ADMIN_CHARACTER_ID", 999):
            assert is_admin(user) is False

    def test_is_admin_disabled_when_zero(self):
        """is_admin always returns False when ADMIN_CHARACTER_ID is 0."""
        from unittest.mock import patch
        from src.core.user_service import is_admin

        user = self._make_user(character_id=999)
        with patch("src.core.user_service.ADMIN_CHARACTER_ID", 0):
            assert is_admin(user) is False

    def test_expire_subscriptions_skips_admin(self):
        """expire_subscriptions must not downgrade the admin user row."""
        from unittest.mock import MagicMock, patch
        from src.core.user_service import UserService

        admin_user_id = "uuid-admin"

        # Build a fake expired subscription belonging to the admin user
        expired_row = {"id": "sub-1", "user_id": admin_user_id}

        db = MagicMock()

        # subscriptions query returns one expired row
        expired_result = MagicMock()
        expired_result.data = [expired_row]

        # users query for admin lookup returns a matching row
        admin_lookup = MagicMock()
        admin_lookup.data = [{"id": admin_user_id}]

        def _table(name):
            tbl = MagicMock()
            if name == "subscriptions":
                tbl.select.return_value.eq.return_value.lt.return_value.execute.return_value = expired_result
                tbl.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif name == "users":
                tbl.select.return_value.eq.return_value.execute.return_value = admin_lookup
                tbl.update.return_value.eq.return_value.execute.return_value = MagicMock()
            return tbl

        db.table.side_effect = _table
        svc = UserService(db)

        with patch("src.core.user_service.ADMIN_CHARACTER_ID", 999):
            count = svc.expire_subscriptions()

        # Admin row was skipped → 0 subscriptions expired
        assert count == 0
